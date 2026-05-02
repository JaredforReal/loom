import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Toaster } from "sonner"

import { listEnvelopes } from "@/lib/api"
import { getDefaultSource } from "@/lib/settings"
import { Sidebar } from "@/components/Sidebar"
import { KanbanBoard } from "@/components/KanbanBoard"
import { StatusBar } from "@/components/StatusBar"
import { SettingsPage } from "@/pages/SettingsPage"

export type View = "inbox" | "policies" | "prompts" | "config"

export default function App() {
  const [view, setView] = useState<View>("inbox")
  const [sourceFilter, setSourceFilter] = useState<string | null>(() =>
    getDefaultSource()
  )
  const [groupFilter, setGroupFilter] = useState<string | null>(null)
  const [sourceIdPrefix, setSourceIdPrefix] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [showArchived, setShowArchived] = useState(false)

  const { data: envelopes = [] } = useQuery({
    queryKey: ["envelopes", sourceFilter, groupFilter, sourceIdPrefix],
    queryFn: () =>
      listEnvelopes(sourceFilter ?? undefined, groupFilter ?? undefined, sourceIdPrefix ?? undefined),
    refetchInterval: 7_000,
    enabled: view === "inbox",
  })

  return (
    <div className="flex h-screen bg-background text-foreground">
      <Sidebar
        view={view}
        onViewChange={setView}
        sourceFilter={sourceFilter}
        groupFilter={groupFilter}
        sourceIdPrefix={sourceIdPrefix}
        onSourceFilter={(src) => {
          setSourceFilter(src)
          setGroupFilter(null)
          setSourceIdPrefix(null)
          setView("inbox")
        }}
        onGroupFilter={(grp) => {
          setGroupFilter(grp)
          setSourceFilter(null)
          setSourceIdPrefix(null)
          setView("inbox")
        }}
        onSourceIdPrefix={(prefix) => {
          setSourceIdPrefix(prefix)
          setSourceFilter(null)
          setGroupFilter(null)
          setView("inbox")
        }}
        showArchived={showArchived}
        onToggleArchived={() => setShowArchived((v) => !v)}
      />
      <div className="flex flex-1 flex-col overflow-hidden">
        <main className="flex-1 overflow-hidden">
          {view === "inbox" ? (
            <KanbanBoard
              envelopes={envelopes}
              showArchived={showArchived}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onCloseDetail={() => setSelectedId(null)}
            />
          ) : (
            <SettingsPage view={view} />
          )}
        </main>
        <StatusBar />
      </div>
      <Toaster position="bottom-right" richColors />
    </div>
  )
}
