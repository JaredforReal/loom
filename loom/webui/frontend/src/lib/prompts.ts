import type {
  PromptDeleteResponse,
  PromptSaveResponse,
  PromptSummary,
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

export const listPrompts = () =>
  jsonFetch<PromptSummary[]>("/api/settings/prompts")

export const getPrompt = (name: string) =>
  jsonFetch<PromptSummary>(`/api/settings/prompts/${encodeURIComponent(name)}`)

export const savePrompt = (name: string, content: string) =>
  jsonFetch<PromptSaveResponse>(
    `/api/settings/prompts/${encodeURIComponent(name)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    },
  )

export const deletePrompt = (name: string) =>
  jsonFetch<PromptDeleteResponse>(
    `/api/settings/prompts/${encodeURIComponent(name)}`,
    { method: "DELETE" },
  )

export const reloadPrompts = () =>
  jsonFetch<{ templates: number }>("/api/settings/prompts/reload", {
    method: "POST",
  })
