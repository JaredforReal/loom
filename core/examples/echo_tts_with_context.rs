use async_trait::async_trait;
use loom_core::action_broker::{ActionBroker, CapabilityProvider};
use loom_core::context::builder::{ContextBuilder, TriggerInput};
use loom_core::context::memory::InMemoryMemory;
use loom_core::context::MemoryWriter;
use loom_core::context::TokenBudget;
use loom_core::proto::{
    ActionCall, ActionError, ActionResult, ActionStatus, CapabilityDescriptor, Event, ProviderKind,
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
            id: "call_ctx_001".to_string(),
            status: ActionStatus::ActionOk as i32,
            output: serde_json::to_vec(&serde_json::json!({"spoken": text})).unwrap_or_default(),
            error: None,
        })
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt::init();

    // Memory + ContextBuilder
    let mem = InMemoryMemory::new();
    let builder = ContextBuilder::new(Arc::clone(&mem), Arc::clone(&mem));

    // Append a couple of events for a session
    let session = "session_ctx_1";
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

    // Build a minimal context
    let pb = builder
        .build(TriggerInput {
            session_id: session.to_string(),
            goal: Some("Speak a short greeting based on session context".to_string()),
            tool_hints: vec!["tts.echo".into()],
            budget: TokenBudget::default(),
        })
        .await?;

    println!("Context instructions: {}", pb.instructions);

    // ActionBroker + EchoTts
    let broker = ActionBroker::new();
    broker.register_provider(Arc::new(EchoTts));

    let call = ActionCall {
        id: "call_ctx_001".to_string(),
        capability: "tts.echo".to_string(),
        version: "0.1.0".to_string(),
        payload: serde_json::to_vec(&serde_json::json!({"text":"Hello from ContextBuilder!"}))
            .unwrap(),
        headers: Default::default(),
        timeout_ms: 3_000,
        correlation_id: session.to_string(),
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
