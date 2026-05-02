import { Trash2 } from "lucide-react"

import type {
  PolicyAction,
  PolicyMatch,
  PolicyRule,
  PolicySchema,
} from "@/lib/types"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

interface RuleCardProps {
  rule: PolicyRule
  schema: PolicySchema | null
  readOnly: boolean
  onChange: (next: PolicyRule) => void
  onRemove: () => void
}

export function RuleCard({
  rule,
  schema,
  readOnly,
  onChange,
  onRemove,
}: RuleCardProps) {
  const updateMatch = (patch: Partial<PolicyMatch>) =>
    onChange({ ...rule, match: { ...rule.match, ...patch } })
  const updateAction = (patch: Partial<PolicyAction>) =>
    onChange({ ...rule, action: { ...rule.action, ...patch } })

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="mb-3 flex items-center gap-2">
        <Field label="Name" className="flex-1">
          <input
            type="text"
            value={rule.name}
            onChange={(e) => onChange({ ...rule, name: e.target.value })}
            disabled={readOnly}
            placeholder="Rule name"
            className={inputCls}
          />
        </Field>
        {!readOnly && (
          <Button
            size="icon"
            variant="ghost"
            onClick={onRemove}
            className="mt-5 h-8 w-8 shrink-0 text-muted-foreground hover:text-destructive"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        )}
      </div>

      <SectionHeader>Match</SectionHeader>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Source">
          <Select
            value={rule.match.source ?? ""}
            onChange={(v) => updateMatch({ source: v || undefined })}
            disabled={readOnly}
            options={[{ value: "", label: "any" }, ...(schema?.sources ?? []).map((s) => ({ value: s, label: s }))]}
          />
        </Field>
        <Field label="Group">
          <Select
            value={rule.match.group ?? ""}
            onChange={(v) => updateMatch({ group: v || undefined })}
            disabled={readOnly}
            options={[{ value: "", label: "any" }, ...(schema?.groups ?? []).map((g) => ({ value: g, label: g }))]}
          />
        </Field>
        <Field label="Labels (all required)" className="col-span-2">
          <ChipInput
            values={rule.match.labels ?? []}
            onChange={(labels) => updateMatch({ labels })}
            disabled={readOnly}
            placeholder="bug, P0"
          />
        </Field>
        <Field label="Source ID pattern (regex)">
          <input
            type="text"
            value={rule.match.source_id_pattern ?? ""}
            onChange={(e) => updateMatch({ source_id_pattern: e.target.value || undefined })}
            disabled={readOnly}
            className={inputCls}
          />
        </Field>
        <Field label="Title pattern (regex)">
          <input
            type="text"
            value={rule.match.title_pattern ?? ""}
            onChange={(e) => updateMatch({ title_pattern: e.target.value || undefined })}
            disabled={readOnly}
            className={inputCls}
          />
        </Field>
      </div>

      <SectionHeader className="mt-4">Action</SectionHeader>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Priority (0–3)">
          <input
            type="number"
            min={0}
            max={3}
            value={rule.action.priority ?? 1}
            onChange={(e) => updateAction({ priority: Number(e.target.value) })}
            disabled={readOnly}
            className={inputCls}
          />
        </Field>
        <Field label="Model">
          <Select
            value={rule.action.model ?? ""}
            onChange={(v) => updateAction({ model: v || undefined })}
            disabled={readOnly}
            options={(schema?.models ?? []).map((m) => ({
              value: m,
              label: m || "(default)",
            }))}
          />
        </Field>
        <Field label="Prompt">
          {schema && schema.prompts.length > 0 ? (
            <Select
              value={rule.action.prompt ?? ""}
              onChange={(v) => updateAction({ prompt: v || undefined })}
              disabled={readOnly}
              options={[
                { value: "", label: "(none)" },
                ...schema.prompts.map((p) => ({ value: p, label: p })),
              ]}
            />
          ) : (
            <input
              type="text"
              value={rule.action.prompt ?? ""}
              onChange={(e) => updateAction({ prompt: e.target.value || undefined })}
              disabled={readOnly}
              className={inputCls}
            />
          )}
        </Field>
        <Field label="Agent">
          <input
            type="text"
            value={rule.action.agent ?? ""}
            onChange={(e) => updateAction({ agent: e.target.value || undefined })}
            disabled={readOnly}
            className={inputCls}
          />
        </Field>
        <Field label="Tools" className="col-span-2">
          <ChipInput
            values={rule.action.tools ?? []}
            onChange={(tools) => updateAction({ tools })}
            disabled={readOnly}
            suggestions={schema?.tools ?? []}
            placeholder="Read, Grep, Bash"
          />
        </Field>
        <Field label="Skills" className="col-span-2">
          <ChipInput
            values={rule.action.skills ?? []}
            onChange={(skills) => updateAction({ skills })}
            disabled={readOnly}
            placeholder="skill-name"
          />
        </Field>
        <Field label="Max turns">
          <input
            type="number"
            min={1}
            value={rule.action.max_turns ?? ""}
            onChange={(e) =>
              updateAction({
                max_turns: e.target.value ? Number(e.target.value) : null,
              })
            }
            disabled={readOnly}
            className={inputCls}
          />
        </Field>
        <Field label="Working directory (cwd)">
          <input
            type="text"
            value={rule.action.cwd ?? ""}
            onChange={(e) => updateAction({ cwd: e.target.value || undefined })}
            disabled={readOnly}
            placeholder="~/projects/foo"
            className={inputCls}
          />
        </Field>
        <Field label="Batch window (only if batched)">
          <input
            type="text"
            value={rule.action.batch_window ?? ""}
            onChange={(e) => updateAction({ batch_window: e.target.value || undefined })}
            disabled={readOnly}
            placeholder="6h, 1d"
            className={inputCls}
          />
        </Field>
        <Field label="Toggles" className="col-span-2">
          <div className="flex flex-wrap gap-4">
            <Toggle
              label="auto_approve"
              checked={rule.action.auto_approve ?? false}
              onChange={(auto_approve) => updateAction({ auto_approve })}
              disabled={readOnly}
            />
            <Toggle
              label="batch"
              checked={rule.action.batch ?? false}
              onChange={(batch) => updateAction({ batch })}
              disabled={readOnly}
            />
          </div>
        </Field>
        <Field label="System prompt" className="col-span-2">
          <textarea
            value={rule.action.system_prompt ?? ""}
            onChange={(e) => updateAction({ system_prompt: e.target.value || undefined })}
            disabled={readOnly}
            rows={3}
            className={cn(inputCls, "min-h-[60px] resize-y")}
          />
        </Field>
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

function SectionHeader({
  children,
  className,
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <h4
      className={cn(
        "mb-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground",
        className,
      )}
    >
      {children}
    </h4>
  )
}

function Select({
  value,
  onChange,
  disabled,
  options,
}: {
  value: string
  onChange: (next: string) => void
  disabled?: boolean
  options: { value: string; label: string }[]
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      className={inputCls}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  )
}

function Toggle({
  label,
  checked,
  onChange,
  disabled,
}: {
  label: string
  checked: boolean
  onChange: (next: boolean) => void
  disabled?: boolean
}) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        disabled={disabled}
        className="h-4 w-4 rounded border-border accent-primary"
      />
      <span className="font-mono text-xs text-muted-foreground">{label}</span>
    </label>
  )
}

function ChipInput({
  values,
  onChange,
  disabled,
  placeholder,
  suggestions,
}: {
  values: string[]
  onChange: (next: string[]) => void
  disabled?: boolean
  placeholder?: string
  suggestions?: string[]
}) {
  const text = values.join(", ")
  const datalistId = suggestions ? `chip-suggest-${Math.random().toString(36).slice(2)}` : undefined
  return (
    <>
      <input
        type="text"
        value={text}
        list={datalistId}
        onChange={(e) =>
          onChange(
            e.target.value
              .split(",")
              .map((s) => s.trim())
              .filter(Boolean),
          )
        }
        disabled={disabled}
        placeholder={placeholder}
        className={inputCls}
      />
      {datalistId && suggestions && (
        <datalist id={datalistId}>
          {suggestions.map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>
      )}
    </>
  )
}
