import { cn } from "@/lib/utils"
import type { Envelope, EnvelopeStatus } from "@/lib/types"
import { ScrollArea } from "@/components/ui/scroll-area"
import { EnvelopeCard } from "./EnvelopeCard"

interface ColumnProps {
  title: string
  status: EnvelopeStatus
  envelopes: Envelope[]
  selectedId: string | null
  onSelect: (id: string) => void
}

const STATUS_TOKEN: Record<EnvelopeStatus, { bg: string; dot: string; label: string }> = {
  pending: {
    bg: "bg-[hsl(var(--status-queue)/0.06)]",
    dot: "bg-status-queue",
    label: "text-[hsl(var(--status-queue))]",
  },
  processing: {
    bg: "bg-[hsl(var(--status-processing)/0.06)]",
    dot: "bg-status-processing",
    label: "text-[hsl(var(--status-processing))]",
  },
  waiting_approval: {
    bg: "bg-[hsl(var(--status-waiting)/0.08)]",
    dot: "bg-status-waiting",
    label: "text-[hsl(var(--status-waiting))]",
  },
  done: {
    bg: "bg-[hsl(var(--status-done)/0.06)]",
    dot: "bg-status-done",
    label: "text-[hsl(var(--status-done))]",
  },
  dismissed: {
    bg: "bg-muted/40",
    dot: "bg-muted-foreground",
    label: "text-muted-foreground",
  },
  failed: {
    bg: "bg-destructive/5",
    dot: "bg-destructive",
    label: "text-destructive",
  },
}

export function Column({ title, status, envelopes, selectedId, onSelect }: ColumnProps) {
  const token = STATUS_TOKEN[status]

  return (
    <div className={cn("flex h-full min-w-[260px] flex-1 flex-col rounded-lg p-2", token.bg)}>
      <header className="mb-2 flex items-center gap-2 px-1">
        <span className={cn("h-2 w-2 rounded-full", token.dot)} />
        <span className={cn("text-xs font-semibold uppercase tracking-wide", token.label)}>
          {title}
        </span>
        <span className="ml-auto text-xs text-muted-foreground">{envelopes.length}</span>
      </header>
      <ScrollArea className="flex-1 pr-1">
        {envelopes.length === 0 ? (
          <div className="py-6 text-center text-xs text-muted-foreground">Empty</div>
        ) : (
          <ul className="space-y-2">
            {envelopes.map((e) => (
              <li key={e.id}>
                <EnvelopeCard
                  envelope={e}
                  active={e.id === selectedId}
                  onClick={() => onSelect(e.id)}
                />
              </li>
            ))}
          </ul>
        )}
      </ScrollArea>
    </div>
  )
}
