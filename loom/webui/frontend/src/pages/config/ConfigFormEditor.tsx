import { useEffect, useMemo, useRef, useState } from "react"
import yaml from "js-yaml"
import { ChevronRight, Plus, Trash2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { savePolicy } from "@/lib/api"
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

        <Card
          title="Sources"
          action={
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                const next = [...config.sources, { kind: "github" }]
                update({ ...config, sources: next })
              }}
            >
              <Plus className="mr-1 h-3.5 w-3.5" />
              Add
            </Button>
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
                  onChange={(next) => {
                    const sources = [...config.sources]
                    sources[i] = next
                    update({ ...config, sources })
                  }}
                  onRemove={() => {
                    const sources = config.sources.filter((_, j) => j !== i)
                    update({ ...config, sources })
                  }}
                  defaultExpanded={i === config.sources.length - 1 && s.kind === "github" && Object.keys(s).length === 1}
                />
              ))}
            </div>
          )}
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
      </div>
    </div>
  )
}

function SourceCard({
  source,
  groupNames,
  onChange,
  onRemove,
  defaultExpanded = false,
}: {
  source: Record<string, unknown> & { kind: string }
  groupNames: string[]
  onChange: (next: Record<string, unknown> & { kind: string }) => void
  onRemove: () => void
  defaultExpanded?: boolean
}) {
  const [expanded, setExpanded] = useState(defaultExpanded)
  const extraEntries = Object.entries(source).filter(([k]) => !SOURCE_COMMON_FIELDS.has(k))
  const datalistId = `group-list-${Math.random().toString(36).slice(2)}`

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
          <span className="text-xs text-muted-foreground">group: {String(source.group)}</span>
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
                onChange={(e) => onChange({ ...source, kind: e.target.value })}
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
              <input
                type="text"
                value={(source.group as string | undefined) ?? ""}
                list={datalistId}
                onChange={(e) =>
                  onChange({ ...source, group: e.target.value || undefined })
                }
                placeholder="(none)"
                className={inputCls}
              />
              <datalist id={datalistId}>
                {groupNames.map((g) => (
                  <option key={g} value={g} />
                ))}
              </datalist>
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
        </div>
      )}
    </div>
  )
}

function GroupCard({
  name,
  policy,
  onChange,
  onRename,
  onRemove,
}: {
  name: string
  policy: string
  onChange: (next: string) => void
  onRename: (next: string) => void
  onRemove: () => void
}) {
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
          <input
            type="text"
            value={policy}
            onChange={(e) => onChange(e.target.value)}
            placeholder="arxiv_policy"
            className={inputCls}
          />
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
