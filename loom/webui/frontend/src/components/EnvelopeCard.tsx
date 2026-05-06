import { cn, formatRelativeTime } from "@/lib/utils"
import type { Envelope } from "@/lib/types"
import { Label } from "./Label"

interface EnvelopeCardProps {
  envelope: Envelope
  active: boolean
  onClick: () => void
}

function pickLabelColors(env: Envelope): Record<string, string> {
  const md = env.metadata as Record<string, unknown> | undefined
  const raw = md?.label_colors
  if (raw && typeof raw === "object") return raw as Record<string, string>
  return {}
}

/** Compact card shown inside a Kanban column. */
export function EnvelopeCard({ envelope, active, onClick }: EnvelopeCardProps) {
  const colors = pickLabelColors(envelope)
  // Don't render the synthetic state/kind labels the adaptor appended ("pr", "issue", "open", "closed").
  const displayLabels = envelope.labels.filter(
    (l) => !["pr", "issue", "open", "closed", "merged"].includes(l)
  )
  const highPriority = envelope.priority >= 2
  const muted =
    envelope.status === "dismissed" ||
    envelope.status === "failed" ||
    envelope.status === "done"

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "group w-full rounded-lg border-[0.5px] border-border bg-card px-2.5 py-3 text-left shadow-card transition-colors duration-150",
        "hover:border-accent hover:bg-accent",
        active && "border-foreground/40 bg-accent",
        muted && "opacity-70"
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 truncate">
          <span className="truncate text-xs text-muted-foreground">
            {envelope.source_id}
          </span>
          {envelope.group && (
            <span className="shrink-0 rounded bg-muted px-1 py-px text-[10px] text-muted-foreground">
              {envelope.group}
            </span>
          )}
        </div>
        <span className="shrink-0 text-xs text-muted-foreground">
          {envelope.received_at ? formatRelativeTime(envelope.received_at) : "—"}
        </span>
      </div>
      <div className="mt-1 line-clamp-2 text-sm font-medium leading-snug text-foreground">
        {envelope.title || "(no title)"}
      </div>
      {displayLabels.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {displayLabels.slice(0, 4).map((l) => (
            <Label key={l} name={l} color={colors[l]} />
          ))}
          {displayLabels.length > 4 && (
            <span className="text-xs text-muted-foreground">
              +{displayLabels.length - 4}
            </span>
          )}
        </div>
      )}
      {(highPriority || envelope.status === "failed") && (
        <div className="mt-2 flex items-center gap-2 text-xs">
          {envelope.status === "failed" && (
            <span className="inline-flex items-center gap-1 text-destructive">
              <span className="h-1.5 w-1.5 rounded-full bg-destructive" />
              failed
            </span>
          )}
          {highPriority && (
            <span className="text-destructive">P{envelope.priority}</span>
          )}
        </div>
      )}
    </button>
  )
}
