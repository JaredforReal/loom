export type EnvelopeStatus =
  | "pending"
  | "processing"
  | "waiting_approval"
  | "done"
  | "dismissed"
  | "failed"

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
  unread: number
  [k: string]: unknown
}
