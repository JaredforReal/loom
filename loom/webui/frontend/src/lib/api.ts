import type { DaemonStatus, Envelope, Source } from "./types"

async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json() as Promise<T>
}

export const getStatus = () => jsonFetch<DaemonStatus>("/api/status")

export const listEnvelopes = (source?: string) => {
  const qs = source ? `?source=${encodeURIComponent(source)}` : ""
  return jsonFetch<Envelope[]>(`/api/envelopes${qs}`)
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
