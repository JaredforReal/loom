import { useState } from "react"

import { cn } from "@/lib/utils"
import { ConfigYamlEditor } from "./ConfigYamlEditor"
import { ConfigFormEditor } from "./ConfigFormEditor"

type Mode = "yaml" | "form"

interface ConfigEditorProps {
  value: string
  onChange: (next: string) => void
}

export function ConfigEditor({ value, onChange }: ConfigEditorProps) {
  const [mode, setMode] = useState<Mode>("form")

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center gap-1 border-b border-border bg-muted/20 px-3 py-1.5">
        <ModeTab active={mode === "yaml"} onClick={() => setMode("yaml")}>
          YAML
        </ModeTab>
        <ModeTab active={mode === "form"} onClick={() => setMode("form")}>
          Form
        </ModeTab>
      </div>
      <div className="flex-1 overflow-hidden">
        {mode === "yaml" ? (
          <ConfigYamlEditor value={value} onChange={onChange} />
        ) : (
          <ConfigFormEditor value={value} onChange={onChange} />
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
