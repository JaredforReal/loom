import type { ConfigFile, ConfigSaveResponse } from "./types"

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

export const getConfig = () => jsonFetch<ConfigFile>("/api/settings/config")

export const saveConfig = (content: string) =>
  jsonFetch<ConfigSaveResponse>("/api/settings/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  })

export const reloadConfig = () =>
  jsonFetch<{ changed: string[]; restart_required: string[] }>(
    "/api/settings/config/reload",
    { method: "POST" },
  )

export const restartDaemon = () =>
  jsonFetch<{ restarting: boolean }>("/api/daemon/restart", { method: "POST" })
