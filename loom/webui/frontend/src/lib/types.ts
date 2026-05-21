export type EnvelopeStatus =
  | "pending"
  | "processing"
  | "in_review"
  | "done"
  | "dismissed"
  | "failed"
  | "tracked"

export interface AgentLogEntry {
  step?: string
  input?: string
  output?: string
  timestamp?: string
  [k: string]: unknown
}

export interface Envelope {
  id: string
  source: string
  source_id: string
  title: string
  body: string
  received_at: string | null
  status: EnvelopeStatus
  priority: number
  labels: string[]
  group: string
  metadata: Record<string, unknown>
  agent_summary: string
  agent_log: AgentLogEntry[]
  proposed_action: Record<string, unknown> | null
}

export interface DaemonStatus {
  online: boolean
  active_sessions: number
  queue_backlog: number
}

export interface Source {
  kind: string
  name: string
  unread: number
  group?: string
  [k: string]: unknown
}

export interface GroupSummary {
  name: string
  sources: Array<Record<string, unknown> & { kind: string; name?: string }>
  unread: number
  prompt?: string
  model?: string
}

export interface PolicySummary {
  name: string
  source: "user" | "bundled"
  content: string
}

export interface PolicyAction {
  priority?: number
  agent?: string
  prompt?: string
  auto_approve?: boolean
  batch?: boolean
  batch_window?: string
  tools?: string[]
  max_turns?: number | null
  system_prompt?: string
  model?: string
  skills?: string[]
  cwd?: string
}

export interface PolicyMatch {
  source?: string
  group?: string
  labels?: string[]
  source_id_pattern?: string
  title_pattern?: string
}

export interface PolicyRule {
  name: string
  match: PolicyMatch
  action: PolicyAction
}

export interface PolicyFile {
  rules: PolicyRule[]
}

export interface PolicySchema {
  sources: string[]
  models: string[]
  tools: string[]
  prompts: string[]
  groups: string[]
  match_fields: string[]
  action_fields: string[]
}

export interface PolicySaveResponse {
  saved: string
  rules: number
}

export interface PolicyDeleteResponse {
  deleted: string
  rules: number
}

export interface PromptSummary {
  name: string
  source: "user" | "bundled"
  content: string
}

export interface PromptSaveResponse {
  saved: string
  templates: number
}

export interface PromptDeleteResponse {
  deleted: string
  templates: number
}

export interface ConfigFile {
  path: string
  content: string
}

export interface ConfigSaveResponse {
  saved: boolean
  changed: string[]
  restart_required: string[]
}

export interface EventUpdate {
  id: string
  type: string
  author: string
  body: string
  html_url: string
  created_at: string
  seen: boolean
}

export interface TrackedEvent {
  id: string
  source_id: string
  source: string
  title: string
  group: string
  envelope_id: string
  status: "active" | "resolved"
  agent_session_id: string
  agent_summary: string
  labels: string[]
  metadata: Record<string, unknown>
  updates: EventUpdate[]
  created_at: string | null
  updated_at: string | null
  new_updates: number
}
