import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"

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

const ANIM_MS = 300
const PAD = 16 // container px-4
const GAP = 12

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
    }
    for (const e of envelopes) g[e.status].push(e)
    return g
  }, [envelopes])

  const doneColumn = showArchived
    ? [...grouped.done, ...grouped.dismissed, ...grouped.failed]
    : grouped.done

  const isOpen = selectedId !== null

  const activeStatus = useMemo(() => {
    if (!selectedId) return null
    const s = envelopes.find((e) => e.id === selectedId)?.status ?? null
    if (s === "dismissed" || s === "failed") return "done" as const
    return s
  }, [selectedId, envelopes])

  const containerRef = useRef<HTMLDivElement | null>(null)
  const colRefs = useRef<Partial<Record<string, HTMLDivElement | null>>>({})
  // Captured before the DOM update so panel starts at the column's true right edge.
  const pendingPanelLeftRef = useRef<number | null>(null)

  const [frozenStatus, setFrozenStatus] = useState<string | null>(null)
  const [frozenWidth, setFrozenWidth] = useState<number | null>(null)
  const [panelLeft, setPanelLeft] = useState<number | null>(null)
  // Suppresses column transitions for one frame on close.
  const [isSnapping, setIsSnapping] = useState(false)
  // Suppresses the panel's left transition while it snaps to its start position.
  const [isPanelSnapping, setIsPanelSnapping] = useState(false)

  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const animRaf = useRef<number | null>(null)

  useLayoutEffect(() => {
    if (closeTimer.current) clearTimeout(closeTimer.current)
    if (animRaf.current) cancelAnimationFrame(animRaf.current)

    if (selectedId) {
      const env = envelopes.find((e) => e.id === selectedId)
      if (env && containerRef.current) {
        const mapped =
          env.status === "dismissed" || env.status === "failed" ? "done" : env.status
        const colEl = colRefs.current[mapped]
        if (colEl) {
          const cRect = containerRef.current.getBoundingClientRect()
          const colWidth = Math.round((cRect.width - 2 * PAD) / 4)
          const finalPanelLeft = PAD + colWidth + GAP

          setIsSnapping(false)
          setFrozenStatus(mapped)
          setFrozenWidth(colWidth)

          const initialPanelLeft = pendingPanelLeftRef.current ?? finalPanelLeft

          if (initialPanelLeft !== finalPanelLeft) {
            // Panel snaps instantly to the column's original right edge (no
            // left transition), then animates left in sync with the columns.
            setIsPanelSnapping(true)
            setPanelLeft(initialPanelLeft)
            animRaf.current = requestAnimationFrame(() => {
              setIsPanelSnapping(false)
              setPanelLeft(finalPanelLeft)
            })
          } else {
            setIsPanelSnapping(false)
            setPanelLeft(finalPanelLeft)
          }
        }
      }
    } else {
      // Snap columns back instantly (covered by the still-opaque panel).
      setIsSnapping(true)
      setFrozenStatus(null)
      setFrozenWidth(null)
      animRaf.current = requestAnimationFrame(() => setIsSnapping(false))
      closeTimer.current = setTimeout(() => setPanelLeft(null), ANIM_MS)
    }
  }, [selectedId]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => () => {
    if (closeTimer.current) clearTimeout(closeTimer.current)
    if (animRaf.current) cancelAnimationFrame(animRaf.current)
  }, [])

  const effectiveStatus = frozenStatus ?? activeStatus

  // handleSelect captures the column's current right edge BEFORE the DOM
  // update so the panel can start adjacent to the column's original position.
  const handleSelect = (id: string | null) => {
    if (id && containerRef.current) {
      const env = envelopes.find((e) => e.id === id)
      if (env) {
        const mapped =
          env.status === "dismissed" || env.status === "failed" ? "done" : env.status
        const colEl = colRefs.current[mapped]
        if (colEl) {
          const cRect = containerRef.current.getBoundingClientRect()
          const eRect = colEl.getBoundingClientRect()
          pendingPanelLeftRef.current = Math.round(eRect.right - cRect.left) + GAP
        }
      }
    } else {
      pendingPanelLeftRef.current = null
    }
    onSelect(id)
  }

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
    <div ref={containerRef} className="relative flex h-full overflow-hidden px-4 py-3">
      {COLUMN_DEFS.map((colDef) => {
        const isActive = effectiveStatus === colDef.status && frozenWidth != null
        const isHidden = isOpen && effectiveStatus != null && effectiveStatus !== colDef.status
        return (
          <div
            key={colDef.status}
            ref={(el) => { colRefs.current[colDef.status] = el }}
            className={cn(
              "flex-none h-full flex-col overflow-hidden rounded-lg p-2",
              isHidden && "opacity-0 pointer-events-none select-none",
            )}
            style={{
              width: isActive ? frozenWidth! : isHidden ? 0 : "25%",
              ...(isHidden ? { padding: 0 } : {}),
              transition: isActive || isSnapping
                ? "none"
                : "width 300ms ease-in-out, padding 300ms ease-in-out, opacity 300ms ease-in-out",
            }}
          >
            <Column
              title={colDef.title}
              status={colDef.status}
              envelopes={columnData[colDef.status]}
              selectedId={selectedId}
              onSelect={handleSelect}
            />
          </div>
        )
      })}

      <div
        className={cn(
          "absolute inset-y-3 right-0 overflow-hidden rounded-lg border-l border-border",
          isOpen ? "opacity-100" : "opacity-0 pointer-events-none",
        )}
        style={{
          left: panelLeft ?? "100%",
          transition: isPanelSnapping
            ? "opacity 300ms ease-in-out"
            : "opacity 300ms ease-in-out, left 300ms ease-in-out",
        }}
      >
        {(isOpen || frozenStatus != null) && (
          <DetailPanel envelopeId={selectedId} onClose={() => handleSelect(null)} />
        )}
      </div>
    </div>
  )
}
