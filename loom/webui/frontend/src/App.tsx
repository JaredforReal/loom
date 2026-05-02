import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Toaster } from "sonner"

import { listEnvelopes } from "@/lib/api"
import { getDefaultSource } from "@/lib/settings"
import { Sidebar } from "@/components/Sidebar"
import { KanbanBoard } from "@/components/KanbanBoard"
import { EnvelopeDrawer } from "@/components/EnvelopeDrawer"
import { StatusBar } from "@/components/StatusBar"
import { SettingsPage } from "@/pages/SettingsPage"

type View = "inbox" | "settings"

export default function App() {
  const [view, setView] = useState<View>("inbox")
  const [sourceFilter, setSourceFilter] = useState<string | null>(() =>
    getDefaultSource()
  )
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [showArchived, setShowArchived] = useState(false)

  const { data: envelopes = [] } = useQuery({
    queryKey: ["envelopes", sourceFilter],
    queryFn: () => listEnvelopes(sourceFilter ?? undefined),
    refetchInterval: 7_000,
    enabled: view === "inbox",
  })

  return (
    <div className="flex h-screen bg-background text-foreground">
      <Sidebar
        view={view}
        onViewChange={setView}
        sourceFilter={sourceFilter}
        onSourceFilter={(src) => {
          setSourceFilter(src)
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
            />
          ) : (
            <SettingsPage />
          )}
        </main>
        <StatusBar />
      </div>
      {view === "inbox" && (
        <EnvelopeDrawer
          envelopeId={selectedId}
          onClose={() => setSelectedId(null)}
        />
      )}
      <Toaster position="bottom-right" richColors />
    </div>
  )
}
