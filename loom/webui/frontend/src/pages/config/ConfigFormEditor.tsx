import { useEffect, useMemo, useRef, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import yaml from "js-yaml"
import { ChevronRight, Plus, Trash2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { savePolicy } from "@/lib/api"
import { listPolicies } from "@/lib/policies"
import { cn } from "@/lib/utils"

interface ConfigFormEditorProps {
  value: string
  onChange: (next: string) => void
}

interface ConfigShape {
  daemon: {
    host?: string
    port?: number
    proxy?: string
  }
  agent: {
    max_concurrent?: number
    model?: string
  }
  paths: {
    policies_dir?: string
    prompts_dir?: string
    data_dir?: string
    credentials_dir?: string
  }
  sources: Array<Record<string, unknown> & { kind: string }>
  groups: Record<string, string>
}

const KNOWN_MODELS = ["sonnet", "opus", "haiku", ""]
const KNOWN_KINDS = ["github", "gmail", "rss", "arxiv"]
const KNOWN_MODES = ["active", "fetch-only", "paused"]
const SOURCE_COMMON_FIELDS = new Set(["kind", "group", "mode"])

interface SourceFieldDef {
  key: string
  label: string
  type: "text" | "number" | "select" | "tags"
  options?: string[]
  default?: string | number
  placeholder?: string
  section?: "config" | "filter"
}

const SOURCE_FIELDS: Record<string, SourceFieldDef[]> = {
  github: [
    { key: "owner", label: "Owner", type: "text", placeholder: "octocat" },
    { key: "repo", label: "Repo", type: "text", placeholder: "hello-world" },
    { key: "poll_interval", label: "Poll interval (s)", type: "number", default: 120 },
    { key: "state", label: "State", type: "select", options: ["all", "open", "closed"], default: "all", section: "filter" },
    { key: "events", label: "Events", type: "tags", placeholder: "issues, pull_requests", section: "filter" },
    { key: "include_labels", label: "Labels (any match)", type: "tags", placeholder: "bug, enhancement", section: "filter" },
    { key: "keywords", label: "Keywords (title/body)", type: "tags", placeholder: "CUDA, quantization", section: "filter" },
    { key: "authors", label: "Authors", type: "tags", placeholder: "username", section: "filter" },
  ],
  rss: [
    { key: "url", label: "Feed URL", type: "text", placeholder: "https://example.com/feed.xml" },
    { key: "poll_interval", label: "Poll interval (s)", type: "number", default: 300 },
    { key: "title_filter", label: "Title filter (any match)", type: "tags", placeholder: "keyword1, keyword2", section: "filter" },
  ],
  arxiv: [
    { key: "categories", label: "Categories", type: "tags", placeholder: "cs.AI, cs.CL" },
    { key: "query", label: "Query (override)", type: "text", placeholder: "cat:cs.AI AND ti:agent" },
    { key: "poll_interval", label: "Poll interval (s)", type: "number", default: 43200 },
    { key: "max_results", label: "Max results", type: "number", default: 50 },
    { key: "keywords", label: "Keywords", type: "tags", placeholder: "LLM, reasoning", section: "filter" },
  ],
  gmail: [
    { key: "query", label: "Gmail query", type: "text", default: "is:unread -in:chats newer_than:1d" },
    { key: "poll_seconds", label: "Poll interval (s)", type: "number", default: 30 },
  ],
}

function sourceDefaults(kind: string): Record<string, unknown> & { kind: string } {
  const fields = SOURCE_FIELDS[kind] ?? []
  const obj: Record<string, unknown> & { kind: string } = { kind }
  for (const f of fields) {
    if (f.default !== undefined) obj[f.key] = f.default
  }
  return obj
}

function parseConfig(content: string): ConfigShape | { error: string } {
  if (!content.trim()) {
    return emptyConfig()
  }
  try {
    const parsed = yaml.load(content)
    if (parsed === null || parsed === undefined) return emptyConfig()
    if (typeof parsed !== "object" || Array.isArray(parsed)) {
      return { error: "Top-level YAML must be an object" }
    }
    const obj = parsed as Record<string, unknown>
    return {
      daemon: (obj.daemon as ConfigShape["daemon"]) ?? {},
      agent: (obj.agent as ConfigShape["agent"]) ?? {},
      paths: (obj.paths as ConfigShape["paths"]) ?? {},
      sources: (obj.sources as ConfigShape["sources"]) ?? [],
      groups: Object.fromEntries(
        Object.entries((obj.groups as Record<string, unknown>) ?? {}).filter(
          ([, v]) => typeof v === "string",
        ),
      ) as Record<string, string>,
    }
  } catch (e) {
    return { error: (e as Error).message }
  }
}

function emptyConfig(): ConfigShape {
  return { daemon: {}, agent: {}, paths: {}, sources: [], groups: {} }
}

function serializeConfig(c: ConfigShape): string {
  const data: Record<string, unknown> = {
    daemon: stripEmpty(c.daemon as unknown as Record<string, unknown>),
    agent: stripEmpty(c.agent as unknown as Record<string, unknown>),
    sources: c.sources,
  }
  if (Object.keys(c.groups).length > 0) {
    data.groups = c.groups
  }
  data.paths = stripEmpty(c.paths as unknown as Record<string, unknown>)
  return yaml.dump(data, { lineWidth: 100, noRefs: true })
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

export function ConfigFormEditor({ value, onChange }: ConfigFormEditorProps) {
  const parsed = useMemo(() => parseConfig(value), [value])
  const [config, setConfig] = useState<ConfigShape>(() =>
    "error" in parsed ? emptyConfig() : parsed,
  )
  const lastEmittedRef = useRef<string>(value)

  const { data: policies = [] } = useQuery({
    queryKey: ["policies"],
    queryFn: listPolicies,
  })
  const policyNames = useMemo(
    () => policies.map((p) => p.name.replace(/\.ya?ml$/, "")),
    [policies],
  )

  useEffect(() => {
    if (value === lastEmittedRef.current) return
    if (!("error" in parsed)) {
      setConfig(parsed)
    }
    lastEmittedRef.current = value
  }, [value, parsed])

  const [newGroupName, setNewGroupName] = useState("")

  const update = (next: ConfigShape) => {
    setConfig(next)
    const serialized = serializeConfig(next)
    lastEmittedRef.current = serialized
    onChange(serialized)
  }

  const addGroup = (name: string) => {
    if (!name || config.groups[name] !== undefined) return
    const policyName = `${name}_policy`
    const policyFile = `${policyName}.yaml`
    const template = `prompt: \nmodel: sonnet\nauto_approve: false\n`
    savePolicy(policyFile, template).catch(() => {})
    update({ ...config, groups: { ...config.groups, [name]: policyName } })
    setNewGroupName("")
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

  const groupNames = Object.keys(config.groups)

  return (
    <div className="h-full overflow-y-auto px-6 py-4">
      <div className="mx-auto flex max-w-3xl flex-col gap-6">
        <Card title="Daemon">
          <div className="grid grid-cols-3 gap-3">
            <Field label="Host">
              <input
                type="text"
                value={config.daemon.host ?? ""}
                onChange={(e) =>
                  update({ ...config, daemon: { ...config.daemon, host: e.target.value } })
                }
                className={inputCls}
              />
            </Field>
            <Field label="Port">
              <input
                type="number"
                value={config.daemon.port ?? ""}
                onChange={(e) =>
                  update({
                    ...config,
                    daemon: {
                      ...config.daemon,
                      port: e.target.value ? Number(e.target.value) : undefined,
                    },
                  })
                }
                className={inputCls}
              />
            </Field>
            <Field label="Proxy">
              <input
                type="text"
                value={config.daemon.proxy ?? ""}
                onChange={(e) =>
                  update({
                    ...config,
                    daemon: { ...config.daemon, proxy: e.target.value || undefined },
                  })
                }
                placeholder="http://127.0.0.1:7897"
                className={inputCls}
              />
            </Field>
          </div>
        </Card>

        <Card title="Agent">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Max concurrent">
              <input
                type="number"
                min={1}
                value={config.agent.max_concurrent ?? ""}
                onChange={(e) =>
                  update({
                    ...config,
                    agent: {
                      ...config.agent,
                      max_concurrent: e.target.value
                        ? Number(e.target.value)
                        : undefined,
                    },
                  })
                }
                className={inputCls}
              />
            </Field>
            <Field label="Model">
              <select
                value={config.agent.model ?? ""}
                onChange={(e) =>
                  update({
                    ...config,
                    agent: { ...config.agent, model: e.target.value || undefined },
                  })
                }
                className={inputCls}
              >
                {KNOWN_MODELS.map((m) => (
                  <option key={m} value={m}>
                    {m || "(default)"}
                  </option>
                ))}
              </select>
            </Field>
          </div>
        </Card>

        <Card title="Paths">
          <div className="grid grid-cols-2 gap-3">
            {(["policies_dir", "prompts_dir", "data_dir", "credentials_dir"] as const).map(
              (k) => (
                <Field key={k} label={k}>
                  <input
                    type="text"
                    value={(config.paths[k] as string | undefined) ?? ""}
                    onChange={(e) =>
                      update({
                        ...config,
                        paths: { ...config.paths, [k]: e.target.value || undefined },
                      })
                    }
                    className={inputCls}
                  />
                </Field>
              ),
            )}
          </div>
        </Card>

        <Card title="Groups">
          <div className="flex flex-col gap-3">
            {groupNames.length === 0 && (
              <p className="text-xs text-muted-foreground">
                No groups defined. Sources without a group appear at the top of the sidebar.
              </p>
            )}
            {groupNames.map((name) => (
              <GroupCard
                key={name}
                name={name}
                policy={config.groups[name]}
                policyNames={policyNames}
                onChange={(next) =>
                  update({
                    ...config,
                    groups: { ...config.groups, [name]: next },
                  })
                }
                onRename={(newName) => {
                  if (!newName || newName === name || config.groups[newName] !== undefined) return
                  const { [name]: g, ...rest } = config.groups
                  update({ ...config, groups: { ...rest, [newName]: g } })
                }}
                onRemove={() => {
                  const { [name]: _removed, ...rest } = config.groups
                  update({ ...config, groups: rest })
                }}
              />
            ))}
            <div className="flex gap-2">
              <input
                type="text"
                value={newGroupName}
                onChange={(e) => setNewGroupName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key !== "Enter") return
                  addGroup(newGroupName.trim())
                }}
                placeholder="New group name…"
                className={cn(inputCls, "flex-1")}
              />
              <Button
                size="sm"
                variant="outline"
                onClick={() => addGroup(newGroupName.trim())}
              >
                <Plus className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        </Card>

        <Card
          title="Sources"
          action={
            <div className="flex items-center gap-1">
              <select
                id="source-kind-select"
                defaultValue="github"
                className={cn(inputCls, "h-8 w-auto text-xs")}
              >
                {KNOWN_KINDS.map((k) => (
                  <option key={k} value={k}>{k}</option>
                ))}
              </select>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  const sel = document.getElementById("source-kind-select") as HTMLSelectElement
                  const kind = sel?.value ?? "github"
                  const defaults = sourceDefaults(kind)
                  const next = [...config.sources, defaults]
                  update({ ...config, sources: next })
                }}
              >
                <Plus className="mr-1 h-3.5 w-3.5" />
                Add
              </Button>
            </div>
          }
        >
          {config.sources.length === 0 ? (
            <p className="text-xs text-muted-foreground">No sources configured.</p>
          ) : (
            <div className="flex flex-col gap-2">
              {config.sources.map((s, i) => (
                <SourceCard
                  key={i}
                  source={s}
                  groupNames={groupNames}
                  groups={config.groups}
                  onChange={(next) => {
                    const sources = [...config.sources]
                    sources[i] = next
                    update({ ...config, sources })
                  }}
                  onRemove={() => {
                    const sources = config.sources.filter((_, j) => j !== i)
                    update({ ...config, sources })
                  }}
                  defaultExpanded={true}
                />
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}

function SourceCard({
  source,
  groupNames,
  groups,
  onChange,
  onRemove,
  defaultExpanded = false,
}: {
  source: Record<string, unknown> & { kind: string }
  groupNames: string[]
  groups: Record<string, string>
  onChange: (next: Record<string, unknown> & { kind: string }) => void
  onRemove: () => void
  defaultExpanded?: boolean
}) {
  const [expanded, setExpanded] = useState(defaultExpanded)
  const schemaFields = SOURCE_FIELDS[source.kind] ?? []
  const configFields = schemaFields.filter((f) => f.section !== "filter")
  const filterFields = schemaFields.filter((f) => f.section === "filter")
  const schemaKeys = new Set(schemaFields.map((f) => f.key))
  const extraEntries = Object.entries(source).filter(
    ([k]) => !SOURCE_COMMON_FIELDS.has(k) && !schemaKeys.has(k),
  )

  const handleKindChange = (newKind: string) => {
    const newDefaults = sourceDefaults(newKind)
    const preserved: Record<string, unknown> & { kind: string } = { kind: newKind }
    if (source.group !== undefined) preserved.group = source.group
    if (source.mode !== undefined) preserved.mode = source.mode
    onChange({ ...newDefaults, ...preserved })
  }

  const setField = (key: string, value: unknown) => {
    const next = { ...source }
    if (value === "" || value === undefined || value === null) {
      delete next[key]
    } else {
      next[key] = value
    }
    onChange(next)
  }

  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="flex items-center gap-2 px-3 py-2">
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          className="text-muted-foreground hover:text-foreground"
        >
          <ChevronRight
            className={cn("h-3.5 w-3.5 transition-transform", expanded && "rotate-90")}
          />
        </button>
        <span className="font-mono text-xs font-medium">{source.kind}</span>
        {source.group ? (
          <span className="text-xs text-muted-foreground">
            group: {String(source.group)}
            {groups[String(source.group)] && (
              <span className="ml-1 opacity-60">→ {groups[String(source.group)]}</span>
            )}
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">(ungrouped)</span>
        )}
        <span className="ml-auto text-xs text-muted-foreground">
          {(source.mode as string | undefined) ?? "active"}
        </span>
        <Button
          size="icon"
          variant="ghost"
          onClick={onRemove}
          className="h-7 w-7 shrink-0 text-muted-foreground hover:text-destructive"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </div>

      {expanded && (
        <div className="border-t border-border px-3 pb-3 pt-2">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Kind">
              <select
                value={source.kind}
                onChange={(e) => handleKindChange(e.target.value)}
                className={inputCls}
              >
                {KNOWN_KINDS.map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
                {!KNOWN_KINDS.includes(source.kind) && (
                  <option value={source.kind}>{source.kind}</option>
                )}
              </select>
            </Field>
            <Field label="Group">
              <select
                value={(source.group as string | undefined) ?? ""}
                onChange={(e) =>
                  onChange({ ...source, group: e.target.value || undefined })
                }
                className={inputCls}
              >
                <option value="">(none)</option>
                {groupNames.map((g) => (
                  <option key={g} value={g}>
                    {g}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Mode">
              <select
                value={(source.mode as string | undefined) ?? "active"}
                onChange={(e) => onChange({ ...source, mode: e.target.value })}
                className={inputCls}
              >
                {KNOWN_MODES.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </Field>

            {/* Config fields */}
            {configFields.map((f) => (
              <SourceField key={f.key} def={f} value={source[f.key]} onChange={(v) => setField(f.key, v)} />
            ))}

            {/* Any extra keys not covered by the schema */}
            {extraEntries.map(([k, v]) => (
              <Field key={k} label={k}>
                <input
                  type="text"
                  value={String(v ?? "")}
                  onChange={(e) =>
                    onChange({ ...source, [k]: e.target.value || undefined })
                  }
                  className={inputCls}
                />
              </Field>
            ))}
          </div>

          {/* Filter section — only shown when the source kind has filter fields */}
          {filterFields.length > 0 && (
            <>
              <div className="mt-3 mb-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Filters
              </div>
              <div className="grid grid-cols-2 gap-3">
                {filterFields.map((f) => (
                  <SourceField key={f.key} def={f} value={source[f.key]} onChange={(v) => setField(f.key, v)} />
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function SourceField({
  def,
  value,
  onChange,
}: {
  def: SourceFieldDef
  value: unknown
  onChange: (v: unknown) => void
}) {
  if (def.type === "select") {
    return (
      <Field label={def.label}>
        <select
          value={String(value ?? def.default ?? "")}
          onChange={(e) => onChange(e.target.value || undefined)}
          className={inputCls}
        >
          {(def.options ?? []).map((o) => (
            <option key={o} value={o}>{o}</option>
          ))}
        </select>
      </Field>
    )
  }

  if (def.type === "number") {
    return (
      <Field label={def.label}>
        <input
          type="number"
          value={value !== undefined ? String(value) : (def.default ?? "")}
          onChange={(e) => onChange(e.target.value ? Number(e.target.value) : undefined)}
          className={inputCls}
        />
      </Field>
    )
  }

  if (def.type === "tags") {
    // YAML list → comma-separated string for editing
    const str = Array.isArray(value)
      ? value.join(", ")
      : typeof value === "string" && value !== ""
        ? value
        : String(def.default ?? "")
    return (
      <Field label={def.label}>
        <input
          type="text"
          value={str}
          placeholder={def.placeholder}
          onChange={(e) => {
            const raw = e.target.value
            if (raw === "") {
              onChange(undefined)
            } else {
              onChange(raw.split(",").map((s) => s.trim()).filter(Boolean))
            }
          }}
          className={inputCls}
        />
      </Field>
    )
  }

  // Default: text
  return (
    <Field label={def.label}>
      <input
        type="text"
        value={String(value ?? def.default ?? "")}
        placeholder={def.placeholder}
        onChange={(e) => onChange(e.target.value || undefined)}
        className={inputCls}
      />
    </Field>
  )
}

function GroupCard({
  name,
  policy,
  policyNames,
  onChange,
  onRename,
  onRemove,
}: {
  name: string
  policy: string
  policyNames: string[]
  onChange: (next: string) => void
  onRename: (next: string) => void
  onRemove: () => void
}) {
  const handlePolicyChange = (value: string) => {
    if (value === "__new__") {
      const newName = window.prompt("New policy name (without .yaml):")
      if (!newName) return
      const template = `prompt: \nmodel: sonnet\nauto_approve: false\n`
      savePolicy(`${newName}.yaml`, template).catch(() => {})
      onChange(newName)
    } else {
      onChange(value)
    }
  }

  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="flex items-center gap-2">
        <Field label="Name" className="flex-1">
          <input
            type="text"
            defaultValue={name}
            onBlur={(e) => onRename(e.target.value)}
            className={inputCls}
          />
        </Field>
        <Field label="Policy" className="flex-1">
          <select
            value={policy}
            onChange={(e) => handlePolicyChange(e.target.value)}
            className={inputCls}
          >
            <option value="">(none)</option>
            {policyNames.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
            <option value="__new__">+ Create new policy...</option>
          </select>
        </Field>
        <Button
          size="icon"
          variant="ghost"
          onClick={onRemove}
          className="mt-5 h-8 w-8 shrink-0 text-muted-foreground hover:text-destructive"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  )
}

const inputCls =
  "w-full rounded-md border border-input bg-background px-2.5 py-1.5 text-sm shadow-sm transition-colors focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-60"

function Field({
  label,
  className,
  children,
}: {
  label: string
  className?: string
  children: React.ReactNode
}) {
  return (
    <label className={cn("flex flex-col gap-1", className)}>
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      {children}
    </label>
  )
}

function Card({
  title,
  action,
  children,
}: {
  title: string
  action?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold">{title}</h3>
        {action}
      </div>
      {children}
    </section>
  )
}
