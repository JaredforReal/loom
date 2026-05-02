import { useEffect, useMemo, useState } from "react"
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { Plus, Trash2, FileText, Lock } from "lucide-react"
import { toast } from "sonner"

import { deletePrompt, listPrompts, savePrompt } from "@/lib/prompts"
import type { PromptSummary } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { PromptEditor } from "./PromptEditor"

const NEW_PROMPT_TEMPLATE = `# New prompt

Describe what the agent should do here. You can reference envelope fields
with placeholders like {{title}}, {{body}}, {{source}}, etc.
`

export function PromptsPanel() {
  const qc = useQueryClient()
  const [selectedName, setSelectedName] = useState<string | null>(null)
  const [draft, setDraft] = useState<string>("")
  const [error, setError] = useState<string | null>(null)

  const { data: prompts = [] } = useQuery({
    queryKey: ["prompts"],
    queryFn: listPrompts,
    refetchInterval: 30_000,
  })

  const selected = useMemo(
    () => prompts.find((p) => p.name === selectedName) ?? null,
    [prompts, selectedName],
  )

  // Auto-select the first user prompt on first load
  useEffect(() => {
    if (selectedName === null && prompts.length > 0) {
      const firstUser = prompts.find((p) => p.source === "user")
      setSelectedName((firstUser ?? prompts[0]).name)
    }
  }, [prompts, selectedName])

  // Reset draft when selecting a different prompt
  useEffect(() => {
    if (selected) {
      setDraft(selected.content)
      setError(null)
    }
  }, [selected])

  const saveMutation = useMutation({
    mutationFn: ({ name, content }: { name: string; content: string }) =>
      savePrompt(name, content),
    onSuccess: (data) => {
      toast.success(`Saved · ${data.templates} templates loaded`)
      setError(null)
      qc.invalidateQueries({ queryKey: ["prompts"] })
    },
    onError: (err: Error) => {
      setError(err.message)
      toast.error(err.message)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (name: string) => deletePrompt(name),
    onSuccess: (data) => {
      toast.success(`Deleted · ${data.templates} templates loaded`)
      setSelectedName(null)
      qc.invalidateQueries({ queryKey: ["prompts"] })
    },
    onError: (err: Error) => toast.error(err.message),
  })

  const handleNew = () => {
    const name = window.prompt(
      "New prompt filename (must end in .md):",
      "my_prompt.md",
    )
    if (!name) return
    if (!name.endsWith(".md")) {
      toast.error("Filename must end in .md")
      return
    }
    if (prompts.some((p) => p.name === name)) {
      toast.error("A prompt with that name already exists")
      return
    }
    saveMutation.mutate({ name, content: NEW_PROMPT_TEMPLATE })
    setSelectedName(name)
  }

  const handleSave = () => {
    if (!selected || selected.source !== "user") return
    saveMutation.mutate({ name: selected.name, content: draft })
  }

  const handleDelete = () => {
    if (!selected || selected.source !== "user") return
    if (!window.confirm(`Delete prompt "${selected.name}"?`)) return
    deleteMutation.mutate(selected.name)
  }

  const isDirty = selected !== null && draft !== selected.content
  const isReadonly = selected?.source === "bundled"

  return (
    <div className="flex h-full">
      <aside className="flex w-[280px] shrink-0 flex-col border-r border-border">
        <div className="flex items-center justify-between border-b border-border px-3 py-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Prompts
          </span>
          <Button size="sm" variant="ghost" onClick={handleNew}>
            <Plus className="h-3.5 w-3.5" />
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto py-1">
          <PromptList
            prompts={prompts}
            source="user"
            label="User"
            selectedName={selectedName}
            onSelect={setSelectedName}
          />
          <PromptList
            prompts={prompts}
            source="bundled"
            label="Bundled (read-only)"
            selectedName={selectedName}
            onSelect={setSelectedName}
          />
        </div>
      </aside>
      <div className="flex flex-1 flex-col overflow-hidden">
        {selected ? (
          <>
            <div className="flex shrink-0 items-center justify-between border-b border-border px-4 py-2">
              <div className="flex items-center gap-2 text-sm">
                {isReadonly ? (
                  <Lock className="h-3.5 w-3.5 text-muted-foreground" />
                ) : (
                  <FileText className="h-3.5 w-3.5 text-muted-foreground" />
                )}
                <span className="font-medium">{selected.name}</span>
                {isReadonly && (
                  <span className="text-xs text-muted-foreground">
                    bundled · read-only
                  </span>
                )}
                {isDirty && !isReadonly && (
                  <span className="text-xs text-amber-500">· unsaved</span>
                )}
              </div>
              <div className="flex items-center gap-2">
                {!isReadonly && (
                  <>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={handleDelete}
                      disabled={deleteMutation.isPending}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      size="sm"
                      onClick={handleSave}
                      disabled={!isDirty || saveMutation.isPending}
                    >
                      {saveMutation.isPending ? "Saving…" : "Save"}
                    </Button>
                  </>
                )}
              </div>
            </div>
            {error && (
              <div className="border-b border-destructive/30 bg-destructive/10 px-4 py-2 text-xs text-destructive">
                {error}
              </div>
            )}
            <div className="flex-1 overflow-hidden">
              <PromptEditor
                value={draft}
                onChange={setDraft}
                readOnly={isReadonly}
              />
            </div>
          </>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            Select or create a prompt to edit
          </div>
        )}
      </div>
    </div>
  )
}

function PromptList({
  prompts,
  source,
  label,
  selectedName,
  onSelect,
}: {
  prompts: PromptSummary[]
  source: "user" | "bundled"
  label: string
  selectedName: string | null
  onSelect: (name: string) => void
}) {
  const items = prompts.filter((p) => p.source === source)
  if (items.length === 0) return null
  return (
    <div className="px-1 pb-2">
      <h3 className="px-2 pt-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </h3>
      {items.map((p) => (
        <button
          key={`${p.source}:${p.name}`}
          type="button"
          onClick={() => onSelect(p.name)}
          className={cn(
            "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors",
            selectedName === p.name
              ? "bg-accent text-accent-foreground"
              : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
          )}
        >
          {source === "bundled" ? (
            <Lock className="h-3 w-3 opacity-60" />
          ) : (
            <FileText className="h-3 w-3 opacity-60" />
          )}
          <span className="flex-1 truncate">{p.name}</span>
        </button>
      ))}
    </div>
  )
}
