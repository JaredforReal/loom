import { useEffect, useMemo, useRef, useState } from "react"
import yaml from "js-yaml"
import { Plus, Trash2 } from "lucide-react"

import type {
  PolicyAction,
  PolicyFile,
  PolicyMatch,
  PolicyRule,
  PolicySchema,
} from "@/lib/types"
import { Button } from "@/components/ui/button"
import { RuleCard } from "./RuleCard"

interface PolicyFormEditorProps {
  value: string
  onChange: (next: string) => void
  readOnly: boolean
  schema: PolicySchema | null
}

function emptyRule(): PolicyRule {
  return {
    name: "",
    match: { source: "" } as PolicyMatch,
    action: { priority: 1 } as PolicyAction,
  }
}

function parsePolicyFile(content: string): PolicyFile | { error: string } {
  if (!content.trim()) return { rules: [] }
  try {
    const parsed = yaml.load(content)
    if (parsed === null || parsed === undefined) return { rules: [] }
    if (typeof parsed !== "object" || Array.isArray(parsed)) {
      return { error: "Top-level YAML must be an object with 'rules:'" }
    }
    const rules = (parsed as { rules?: unknown }).rules
    if (rules === undefined) return { rules: [] }
    if (!Array.isArray(rules)) return { error: "'rules' must be a list" }
    return { rules: rules as PolicyRule[] }
  } catch (e) {
    return { error: (e as Error).message }
  }
}

function serializePolicyFile(file: PolicyFile): string {
  // Strip empty optional fields to keep the YAML tidy
  const cleaned = {
    rules: file.rules.map((r) => ({
      name: r.name,
      match: stripEmpty(r.match as Record<string, unknown>) as PolicyMatch,
      action: stripEmpty(r.action as Record<string, unknown>) as PolicyAction,
    })),
  }
  return yaml.dump(cleaned, { lineWidth: 100, noRefs: true })
}

function stripEmpty(obj: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(obj)) {
    if (v === null || v === undefined) continue
    if (typeof v === "string" && v === "") continue
    if (Array.isArray(v) && v.length === 0) continue
    out[k] = v
  }
  return out
}

export function PolicyFormEditor({
  value,
  onChange,
  readOnly,
  schema,
}: PolicyFormEditorProps) {
  const parsed = useMemo(() => parsePolicyFile(value), [value])
  const [localRules, setLocalRules] = useState<PolicyRule[]>(() =>
    "rules" in parsed ? parsed.rules : [],
  )
  // Track when external `value` changes are NOT a result of our own onChange
  const lastEmittedRef = useRef<string>(value)

  useEffect(() => {
    if (value === lastEmittedRef.current) return
    if ("rules" in parsed) {
      setLocalRules(parsed.rules)
    }
    lastEmittedRef.current = value
  }, [value, parsed])

  const updateRules = (next: PolicyRule[]) => {
    setLocalRules(next)
    const serialized = serializePolicyFile({ rules: next })
    lastEmittedRef.current = serialized
    onChange(serialized)
  }

  if ("error" in parsed) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center text-sm">
        <span className="text-destructive">YAML cannot be parsed</span>
        <span className="text-xs text-muted-foreground">{parsed.error}</span>
        <span className="text-xs text-muted-foreground">
          Fix it in the YAML tab, then come back.
        </span>
      </div>
    )
  }

  return (
    <div className="h-full overflow-y-auto px-6 py-4">
      <div className="mx-auto flex max-w-3xl flex-col gap-3">
        {localRules.length === 0 && (
          <div className="rounded-md border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground">
            No rules yet
          </div>
        )}
        {localRules.map((rule, idx) => (
          <RuleCard
            key={idx}
            rule={rule}
            schema={schema}
            readOnly={readOnly}
            onChange={(next) => {
              const copy = [...localRules]
              copy[idx] = next
              updateRules(copy)
            }}
            onRemove={() => {
              const copy = localRules.filter((_, i) => i !== idx)
              updateRules(copy)
            }}
          />
        ))}
        {!readOnly && (
          <Button
            variant="outline"
            size="sm"
            className="self-start"
            onClick={() => updateRules([...localRules, emptyRule()])}
          >
            <Plus className="mr-1 h-3.5 w-3.5" />
            Add rule
          </Button>
        )}
        {readOnly && localRules.length > 0 && (
          <p className="text-xs text-muted-foreground">
            <Trash2 className="mr-1 inline h-3 w-3" />
            Bundled policies are read-only. Create a user policy to override.
          </p>
        )}
      </div>
    </div>
  )
}
