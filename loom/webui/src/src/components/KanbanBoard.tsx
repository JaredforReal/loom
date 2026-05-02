import { useMemo } from "react"

import type { Envelope, EnvelopeStatus } from "@/lib/types"
import { Column } from "./Column"

interface KanbanBoardProps {
  envelopes: Envelope[]
  showArchived: boolean
  selectedId: string | null
  onSelect: (id: string) => void
}

export function KanbanBoard({
  envelopes,
  showArchived,
  selectedId,
  onSelect,
}: KanbanBoardProps) {
  const grouped = useMemo(() => {
    const g: Record<EnvelopeStatus, Envelope[]> = {
      pending: [],
      processing: [],
      waiting_approval: [],
      done: [],
      dismissed: [],
      failed: [],
    }
    for (const e of envelopes) g[e.status].push(e)
    return g
  }, [envelopes])

  const doneColumn = showArchived
    ? [...grouped.done, ...grouped.dismissed, ...grouped.failed]
    : grouped.done

  return (
    <div className="flex h-full gap-3 overflow-x-auto px-4 py-3">
      <Column
        title="Queue"
        status="pending"
        envelopes={grouped.pending}
        selectedId={selectedId}
        onSelect={onSelect}
      />
      <Column
        title="Processing"
        status="processing"
        envelopes={grouped.processing}
        selectedId={selectedId}
        onSelect={onSelect}
      />
      <Column
        title="Waiting Approval"
        status="waiting_approval"
        envelopes={grouped.waiting_approval}
        selectedId={selectedId}
        onSelect={onSelect}
      />
      <Column
        title="Done"
        status="done"
        envelopes={doneColumn}
        selectedId={selectedId}
        onSelect={onSelect}
      />
    </div>
  )
}
