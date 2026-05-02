import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatRelativeTime(iso: string): string {
  const date = new Date(iso)
  const diffMs = Date.now() - date.getTime()
  const diffMin = Math.floor(diffMs / 60000)
  if (diffMin < 1) return "just now"
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  const diffDay = Math.floor(diffHr / 24)
  if (diffDay < 7) return `${diffDay}d ago`
  return date.toLocaleDateString()
}

/** Returns black or white to ensure readable text on the given hex background. */
export function contrastTextColor(hex: string): "#000" | "#fff" {
  const clean = hex.replace(/^#/, "")
  if (clean.length !== 6) return "#000"
  const n = parseInt(clean, 16)
  if (Number.isNaN(n)) return "#000"
  const r = (n >> 16) & 255
  const g = (n >> 8) & 255
  const b = n & 255
  const L = (0.299 * r + 0.587 * g + 0.114 * b) / 255
  return L > 0.6 ? "#000" : "#fff"
}
