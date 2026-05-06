import { useState } from "react"

import type { PolicySchema } from "@/lib/types"
import { cn } from "@/lib/utils"
import { PolicyYamlEditor } from "./PolicyYamlEditor"
import { PolicyFormEditor } from "./PolicyFormEditor"

type Mode = "yaml" | "form"

interface PolicyEditorProps {
  value: string
  onChange: (next: string) => void
  readOnly: boolean
  schema: PolicySchema | null
}

export function PolicyEditor({
  value,
  onChange,
  readOnly,
  schema,
}: PolicyEditorProps) {
  const [mode, setMode] = useState<Mode>("form")

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center gap-1 border-b border-border bg-muted/20 px-3 py-1.5">
        <ModeTab active={mode === "form"} onClick={() => setMode("form")}>
          Form
        </ModeTab>
        <ModeTab active={mode === "yaml"} onClick={() => setMode("yaml")}>
          YAML
        </ModeTab>
      </div>
      <div className="flex-1 overflow-hidden">
        {mode === "yaml" ? (
          <PolicyYamlEditor value={value} onChange={onChange} readOnly={readOnly} />
        ) : (
          <PolicyFormEditor
            value={value}
            onChange={onChange}
            readOnly={readOnly}
            schema={schema}
          />
        )}
      </div>
    </div>
  )
}

function ModeTab({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded px-3 py-1 text-xs font-medium transition-colors",
        active
          ? "bg-background text-foreground shadow-sm"
          : "text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  )
}
