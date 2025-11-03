use crate::proto::{ActionCall, ActionResult, ActionStatus, CapabilityDescriptor};
use crate::{LoomError, Result};
use async_trait::async_trait;
use dashmap::DashMap;
use std::sync::Arc;
use tokio::time::{timeout, Duration};
use tracing::{debug, info, warn};

/// Trait implemented by concrete capability providers (Native, WASM, gRPC/MCP adapters)
#[async_trait]
pub trait CapabilityProvider: Send + Sync {
    /// Static descriptor for discovery/registration
    fn descriptor(&self) -> CapabilityDescriptor;

    /// Invoke the capability with an ActionCall and return an ActionResult
    async fn invoke(&self, call: ActionCall) -> Result<ActionResult>;
}

/// Action/Tool Broker: centralized registry and invoker
pub struct ActionBroker {
    registry: DashMap<String, Arc<dyn CapabilityProvider>>, // capability name -> provider
}

impl ActionBroker {
    pub fn new() -> Self {
        Self {
            registry: DashMap::new(),
        }
    }

    /// Register a provider; later registrations with the same name replace the previous one
    pub fn register_provider(&self, provider: Arc<dyn CapabilityProvider>) {
        let name = provider.descriptor().name;
        info!(target: "action_broker", capability = %name, "Registering capability provider");
        self.registry.insert(name, provider);
    }

    /// List all registered capabilities
    pub fn list_capabilities(&self) -> Vec<CapabilityDescriptor> {
        self.registry
            .iter()
            .map(|entry| entry.value().descriptor())
            .collect()
    }

    /// Invoke a capability by name with timeout handling
    pub async fn invoke(&self, mut call: ActionCall) -> Result<ActionResult> {
        let cap_name = call.capability.clone();
        let call_id = call.id.clone();
        let provider = self
            .registry
            .get(&cap_name)
            .ok_or_else(|| LoomError::PluginError(format!("Capability not found: {}", cap_name)))?;

        let dur = if call.timeout_ms <= 0 {
            30_000
        } else {
            call.timeout_ms
        };
        debug!(target: "action_broker", capability = %cap_name, timeout_ms = dur, "Invoking capability");

        let fut = provider.invoke(call);
        match timeout(Duration::from_millis(dur as u64), fut).await {
            Ok(Ok(res)) => Ok(res),
            Ok(Err(err)) => {
                warn!(target: "action_broker", capability = %cap_name, error = %err, "Capability error");
                Ok(ActionResult {
                    id: call_id.clone(),
                    status: ActionStatus::ActionError as i32,
                    output: Vec::new(),
                    error: Some(crate::proto::ActionError {
                        code: "CAPABILITY_ERROR".to_string(),
                        message: err.to_string(),
                        details: Default::default(),
                    }),
                })
            }
            Err(_) => {
                warn!(target: "action_broker", capability = %cap_name, "Capability timeout");
                Ok(ActionResult {
                    id: call_id,
                    status: ActionStatus::ActionTimeout as i32,
                    output: Vec::new(),
                    error: Some(crate::proto::ActionError {
                        code: "TIMEOUT".to_string(),
                        message: "Action timed out".to_string(),
                        details: Default::default(),
                    }),
                })
            }
        }
    }
}

impl Default for ActionBroker {
    fn default() -> Self {
        Self::new()
    }
}
