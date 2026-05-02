const KEY = "loom.settings.defaultSource"

export function getDefaultSource(): string | null {
  if (typeof window === "undefined") return null
  return window.localStorage.getItem(KEY) || null
}

export function setDefaultSource(source: string | null): void {
  if (typeof window === "undefined") return
  if (source === null) window.localStorage.removeItem(KEY)
  else window.localStorage.setItem(KEY, source)
}
