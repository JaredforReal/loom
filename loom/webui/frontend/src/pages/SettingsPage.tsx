import { PoliciesPanel } from "./policies/PoliciesPanel"
import { PromptsPanel } from "./prompts/PromptsPanel"

interface SettingsPageProps {
  view: "policies" | "prompts"
}

export function SettingsPage({ view }: SettingsPageProps) {
  return (
    <div className="flex h-full flex-col">
      <header className="flex h-12 shrink-0 items-center border-b border-border px-6">
        <h1 className="text-sm font-semibold tracking-tight">
          Settings · {view === "policies" ? "Policies" : "Prompts"}
        </h1>
      </header>
      <div className="flex-1 overflow-hidden">
        {view === "policies" ? <PoliciesPanel /> : <PromptsPanel />}
      </div>
    </div>
  )
}
