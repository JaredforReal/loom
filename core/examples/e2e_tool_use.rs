use async_trait::async_trait;
use loom_core::action_broker::{ActionBroker, CapabilityProvider};
use loom_core::context::builder::{ContextBuilder, TriggerInput};
use loom_core::context::memory::InMemoryMemory;
use loom_core::context::MemoryWriter;
use loom_core::context::TokenBudget;
use loom_core::event::EventBus;
use loom_core::proto::{
    ActionCall, ActionError, ActionResult, ActionStatus, CapabilityDescriptor, Event, ProviderKind,
    QoSLevel,
};
use loom_core::Result;
use serde_json::json;
use std::sync::Arc;
use tracing::{info, warn};

// ---- Minimal capability: tts.echo ----
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
            output: serde_json::to_vec(&json!({"spoken": text})).unwrap_or_default(),
            error: None,
        })
    }
}

// ---- Minimal mock LLM that emits a tool call ----
#[derive(Clone, Debug)]
struct ToolSchema {
    name: String,
}

#[derive(Clone, Debug)]
struct LlmToolCall {
    name: String,
    arguments_json: String,
}

struct MockLlm;
impl MockLlm {
    fn infer_with_tools(instructions: &str, tools: &[ToolSchema]) -> Result<LlmToolCall> {
        // Always choose first tool and pass instructions as text
        let tool = tools
            .first()
            .ok_or_else(|| loom_core::LoomError::AgentError("no tools available".into()))?;
        let text = if instructions.is_empty() {
            "Hello from MockLLM".to_string()
        } else {
            instructions.to_string()
        };
        let args = json!({"text": text});
        Ok(LlmToolCall {
            name: tool.name.clone(),
            arguments_json: serde_json::to_string(&args).unwrap_or("{}".into()),
        })
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt::init();

    // Event bus just for demonstration (publish a final event)
    let event_bus = EventBus::new().await?;

    // Memory + ContextBuilder
    let mem = InMemoryMemory::new();
    let builder = ContextBuilder::new(Arc::clone(&mem), Arc::clone(&mem));

    // Seed a couple of events
    let session = "session_e2e_1";
    let e1 = Event {
        id: "e1".into(),
        r#type: "intent".into(),
        timestamp_ms: 1,
        source: "ui".into(),
        metadata: Default::default(),
        payload: vec![],
        confidence: 1.0,
        tags: vec![],
        priority: 50,
    };
    let e2 = Event {
        id: "e2".into(),
        r#type: "context".into(),
        timestamp_ms: 2,
        source: "system".into(),
        metadata: Default::default(),
        payload: vec![],
        confidence: 1.0,
        tags: vec![],
        priority: 50,
    };
    mem.append_event(session, e1).await?;
    mem.append_event(session, e2).await?;

    // Build prompt bundle
    let pb = builder
        .build(TriggerInput {
            session_id: session.to_string(),
            goal: Some("Say a friendly greeting as TTS".to_string()),
            tool_hints: vec!["tts.echo".into()],
            budget: TokenBudget::default(),
        })
        .await?;

    info!("instructions = {}", pb.instructions);

    // Available tools for LLM
    let tools = vec![ToolSchema {
        name: "tts.echo".into(),
    }];

    // Mock LLM decides to call a tool
    let tool_call = MockLlm::infer_with_tools(&pb.instructions, &tools)?;
    info!(
        "llm tool_call: {} {}",
        tool_call.name, tool_call.arguments_json
    );

    // Broker + provider
    let broker = ActionBroker::new();
    broker.register_provider(Arc::new(EchoTts));

    // Execute the tool call via ActionBroker
    let call = ActionCall {
        id: "e2e_call_001".into(),
        capability: tool_call.name,
        version: "0.1.0".into(),
        payload: tool_call.arguments_json.into_bytes(),
        headers: Default::default(),
        timeout_ms: 5_000,
        correlation_id: session.into(),
        qos: QoSLevel::QosRealtime as i32,
    };
    let res = broker.invoke(call).await?;

    if res.status == ActionStatus::ActionOk as i32 {
        info!("tool result ok: {}", String::from_utf8_lossy(&res.output));
        // Publish a final event to the bus
        let out_event = Event {
            id: "e_final".into(),
            r#type: "action_done".into(),
            timestamp_ms: 3,
            source: "agent.demo".into(),
            metadata: Default::default(),
            payload: res.output.clone(),
            confidence: 1.0,
            tags: vec!["tts".into()],
            priority: 50,
        };
        let _ = event_bus.publish("agent.demo", out_event).await?;
    } else {
        warn!("tool result error: {:?}", res.error);
    }

    Ok(())
}
