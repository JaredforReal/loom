use async_trait::async_trait;
use loom_core::action_broker::{ActionBroker, CapabilityProvider};
use loom_core::proto::{
    ActionCall, ActionError, ActionResult, ActionStatus, CapabilityDescriptor, ProviderKind,
    QoSLevel,
};
use loom_core::Result;
use std::sync::Arc;

struct EchoTts;

#[async_trait]
impl CapabilityProvider for EchoTts {
    fn descriptor(&self) -> CapabilityDescriptor {
        CapabilityDescriptor {
            name: "tts.echo".to_string(),
            version: "0.1.0".to_string(),
            provider: ProviderKind::ProviderNative as i32,
            metadata: Default::default(),
        }
    }

    async fn invoke(&self, call: ActionCall) -> Result<ActionResult> {
        // Expect payload to be JSON: {"text":"..."}
        let text: String = match serde_json::from_slice::<serde_json::Value>(&call.payload)
            .ok()
            .and_then(|v| {
                v.get("text")
                    .and_then(|t| t.as_str())
                    .map(|s| s.to_string())
            }) {
            Some(s) => s,
            None => {
                return Ok(ActionResult {
                    id: call.id,
                    status: ActionStatus::ActionError as i32,
                    output: Vec::new(),
                    error: Some(ActionError {
                        code: "BAD_PAYLOAD".to_string(),
                        message: "expected JSON {\"text\":\"...\"}".to_string(),
                        details: Default::default(),
                    }),
                });
            }
        };

        println!("[EchoTts] speaking: {}", text);

        Ok(ActionResult {
            id: call.id,
            status: ActionStatus::ActionOk as i32,
            output: serde_json::to_vec(&serde_json::json!({"spoken": text})).unwrap_or_default(),
            error: None,
        })
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt::init();

    let broker = ActionBroker::new();
    broker.register_provider(Arc::new(EchoTts));

    let call = ActionCall {
        id: "call_001".to_string(),
        capability: "tts.echo".to_string(),
        version: "0.1.0".to_string(),
        payload: serde_json::to_vec(&serde_json::json!({"text":"Hello Loom!"})).unwrap(),
        headers: Default::default(),
        timeout_ms: 3_000,
        correlation_id: "demo_session_1".to_string(),
        qos: QoSLevel::QosRealtime as i32,
    };

    let res = broker.invoke(call).await?;
    println!(
        "ActionResult: status={}, error={:?}, output={}",
        res.status,
        res.error,
        String::from_utf8_lossy(&res.output)
    );

    Ok(())
}
