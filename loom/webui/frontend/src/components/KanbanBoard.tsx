import { useMemo, useRef, useState } from "react"

import type { Envelope, EnvelopeStatus } from "@/lib/types"
import { cn } from "@/lib/utils"
import { Column } from "./Column"
import { DetailPanel } from "./DetailPanel"

const COLUMN_DEFS = [
  { title: "Queue", status: "pending" as const },
  { title: "Processing", status: "processing" as const },
  { title: "In Review", status: "in_review" as const },
  { title: "Done", status: "done" as const },
] as const

interface KanbanBoardProps {
  envelopes: Envelope[]
  showArchived: boolean
  selectedId: string | null
  onSelect: (id: string | null) => void
  onCloseDetail: () => void
}

export function KanbanBoard({
  envelopes,
  showArchived,
  selectedId,
  onSelect,
  onCloseDetail,
}: KanbanBoardProps) {
  const grouped = useMemo(() => {
    const g: Record<EnvelopeStatus, Envelope[]> = {
      pending: [],
      processing: [],
      in_review: [],
      done: [],
      dismissed: [],
      failed: [],
      tracked: [],
    }
    for (const e of envelopes) g[e.status].push(e)
    return g
  }, [envelopes])

  const doneColumn = showArchived
    ? [...grouped.done, ...grouped.dismissed, ...grouped.failed]
    : grouped.done

  // Freeze the active column status when a card is first selected so that
  // envelope status changes (via polling) don't cause layout jumps.
  const [frozenStatus, setFrozenStatus] = useState<EnvelopeStatus | null>(null)
  const prevSelectedId = useRef<string | null>(null)

  if (selectedId !== prevSelectedId.current) {
    prevSelectedId.current = selectedId
    if (selectedId) {
      const env = envelopes.find((e) => e.id === selectedId)
      if (env) setFrozenStatus(env.status)
    } else {
      setFrozenStatus(null)
    }
  }

  const isOpen = selectedId !== null
  const activeStatus = isOpen ? frozenStatus : null

  const orderedColumns = useMemo(() => {
    if (!activeStatus) return COLUMN_DEFS
    const active = COLUMN_DEFS.find((c) => c.status === activeStatus)!
    const rest = COLUMN_DEFS.filter((c) => c.status !== activeStatus)
    return [active, ...rest]
  }, [activeStatus])

  const columnData = useMemo(
    () => ({
      pending: grouped.pending,
      processing: grouped.processing,
      in_review: grouped.in_review,
      done: doneColumn,
    }),
    [grouped, doneColumn]
  )

  return (
    <div className="flex h-full px-4 py-3">
      {orderedColumns.map((colDef, idx) => {
        const isHidden = isOpen && idx > 0
        return (
          <div
            key={colDef.status}
            className={cn(
              "transition-all duration-300 ease-in-out",
              isHidden
                ? "w-0 min-w-0 flex-none overflow-hidden opacity-0"
                : "flex h-full min-w-[260px] flex-1 flex-col rounded-lg p-2"
            )}
            style={isHidden ? { marginLeft: 0, marginRight: 0 } : undefined}
          >
            <Column
              title={colDef.title}
              status={colDef.status}
              envelopes={columnData[colDef.status]}
              selectedId={selectedId}
              onSelect={onSelect}
            />
          </div>
        )
      })}

      <div
        className={cn(
          "flex-none overflow-hidden rounded-lg border-l border-border transition-all duration-300 ease-in-out",
          isOpen
            ? "ml-3 min-w-[480px] flex-[3] opacity-100"
            : "min-w-0 w-0 flex-none opacity-0"
        )}
      >
        {isOpen && <DetailPanel envelopeId={selectedId} onClose={onCloseDetail} />}
      </div>
    </div>
  )
}
