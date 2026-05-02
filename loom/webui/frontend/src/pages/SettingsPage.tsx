import { PoliciesPanel } from "./policies/PoliciesPanel"
import { PromptsPanel } from "./prompts/PromptsPanel"
import { ConfigPanel } from "./config/ConfigPanel"

interface SettingsPageProps {
  view: "policies" | "prompts" | "config"
}

const TITLES: Record<SettingsPageProps["view"], string> = {
  policies: "Policies",
  prompts: "Prompts",
  config: "Config",
}

export function SettingsPage({ view }: SettingsPageProps) {
  return (
    <div className="flex h-full flex-col">
      <header className="flex h-12 shrink-0 items-center border-b border-border px-6">
        <h1 className="text-sm font-semibold tracking-tight">
          Settings · {TITLES[view]}
        </h1>
      </header>
      <div className="flex-1 overflow-hidden">
        {view === "policies" && <PoliciesPanel />}
        {view === "prompts" && <PromptsPanel />}
        {view === "config" && <ConfigPanel />}
      </div>
    </div>
  )
}
