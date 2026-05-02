import type {
  PolicyDeleteResponse,
  PolicySaveResponse,
  PolicySchema,
  PolicySummary,
} from "./types"

async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) {
    let detail = ""
    try {
      const body = await res.json()
      detail = body?.error ?? ""
    } catch {
      // ignore
    }
    throw new Error(detail || `${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<T>
}

export const listPolicies = () =>
  jsonFetch<PolicySummary[]>("/api/settings/policies")

export const getPolicy = (name: string) =>
  jsonFetch<PolicySummary>(`/api/settings/policies/${encodeURIComponent(name)}`)

export const savePolicy = (name: string, content: string) =>
  jsonFetch<PolicySaveResponse>(
    `/api/settings/policies/${encodeURIComponent(name)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    },
  )

export const deletePolicy = (name: string) =>
  jsonFetch<PolicyDeleteResponse>(
    `/api/settings/policies/${encodeURIComponent(name)}`,
    { method: "DELETE" },
  )

export const reloadPolicies = () =>
  jsonFetch<{ rules: number }>("/api/settings/policies/reload", {
    method: "POST",
  })

export const getPolicySchema = () =>
  jsonFetch<PolicySchema>("/api/settings/policies/schema")
