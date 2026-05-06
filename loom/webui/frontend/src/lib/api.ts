import type { DaemonStatus, Envelope, GroupSummary, Source, TrackedEvent } from "./types"

async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json() as Promise<T>
}

export const getStatus = () => jsonFetch<DaemonStatus>("/api/status")

export const listEnvelopes = (source?: string, group?: string, sourceIdPrefix?: string) => {
  const params = new URLSearchParams()
  if (source) params.set("source", source)
  if (group) params.set("group", group)
  if (sourceIdPrefix) params.set("source_id_prefix", sourceIdPrefix)
  params.set("limit", "10000")
  return jsonFetch<Envelope[]>(`/api/envelopes?${params}`)
}

export const getEnvelope = (id: string) =>
  jsonFetch<Envelope | { error: string }>(`/api/envelopes/${id}`)

export const approveEnvelope = (id: string) =>
  jsonFetch<{ status: string; id: string }>(`/api/envelopes/${id}/approve`, {
    method: "POST",
  })

export const dismissEnvelope = (id: string) =>
  jsonFetch<{ status: string; id: string }>(`/api/envelopes/${id}/dismiss`, {
    method: "POST",
  })

export const openInTerminal = (id: string, confirm?: boolean) => {
  const init: RequestInit = { method: "POST" }
  if (confirm) init.body = JSON.stringify({ confirm: true })
  return jsonFetch<{ status?: string; resumed?: boolean; needs_confirm?: boolean }>(
    `/api/envelopes/${id}/open-in-terminal`,
    init,
  )
}

export const getEnvelopeSession = (id: string) =>
  jsonFetch<{ cli_session_id: string; cwd: string | null } | null>(
    `/api/envelopes/${id}/session`,
  )

export const listSources = () => jsonFetch<Source[]>("/api/sources")

export const listGroups = () => jsonFetch<GroupSummary[]>("/api/groups")

export const savePolicy = (name: string, content: string) =>
  jsonFetch<{ saved: boolean }>(`/api/settings/policies/${encodeURIComponent(name)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  })

// --- Events (tracked items) ---

export const trackEnvelope = (id: string) =>
  jsonFetch<{ status: string; event_id: string }>(`/api/envelopes/${id}/track`, {
    method: "POST",
  })

export const listEvents = (status?: string) => {
  const params = new URLSearchParams()
  if (status) params.set("status", status)
  return jsonFetch<TrackedEvent[]>(`/api/events?${params}`)
}

export const getEvent = (id: string) =>
  jsonFetch<TrackedEvent>(`/api/events/${id}`)

export const resolveEvent = (id: string) =>
  jsonFetch<{ status: string; id: string }>(`/api/events/${id}/resolve`, {
    method: "POST",
  })

export const markUpdatesSeen = (id: string) =>
  jsonFetch<{ marked_seen: number }>(`/api/events/${id}/updates/seen`, {
    method: "PATCH",
  })

export const analyzeEvent = (id: string) =>
  jsonFetch<{ status: string; summary_length?: number }>(`/api/events/${id}/analyze`, {
    method: "POST",
  })
