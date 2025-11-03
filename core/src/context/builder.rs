use super::{MemoryReader, MemoryWriter, PromptBundle, TokenBudget};
use crate::Result;
use std::sync::Arc;
use tracing::debug;

/// Input that triggers context construction
#[derive(Debug, Clone)]
pub struct TriggerInput {
    pub session_id: String,
    pub goal: Option<String>,
    pub tool_hints: Vec<String>,
    pub budget: TokenBudget,
}

/// ContextBuilder assembles a PromptBundle from memory and recent events
pub struct ContextBuilder<R: MemoryReader, W: MemoryWriter> {
    reader: Arc<R>,
    writer: Arc<W>,
}

impl<R: MemoryReader, W: MemoryWriter> ContextBuilder<R, W> {
    pub fn new(reader: Arc<R>, writer: Arc<W>) -> Self {
        Self { reader, writer }
    }

    /// Build a minimal prompt bundle; this is a skeleton to be expanded
    pub async fn build(&self, trigger: TriggerInput) -> Result<PromptBundle> {
        debug!(target: "context_builder", session = %trigger.session_id, "Building prompt bundle");

        // TODO: pull recent events window and episodic summaries from writer/reader
        // TODO: run retrieval based on goal/query
        let _retrieved = self
            .reader
            .retrieve(trigger.goal.as_deref().unwrap_or(""), 4, None)
            .await
            .unwrap_or_default();

        // Minimal prompt bundle (no-op)
        Ok(PromptBundle {
            system: "You are Loom Agent. Be concise and precise.".to_string(),
            instructions: trigger.goal.unwrap_or_default(),
            tools_json_schema: None,
            context_docs: vec![],
            history: vec![],
        })
    }
}
