import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, Eye, MessageSquare, RotateCcw } from "lucide-react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { toast } from "sonner"

import { getEvent, listEvents, markUpdatesSeen, resolveEvent, analyzeEvent } from "@/lib/api"
import type { TrackedEvent, EventUpdate } from "@/lib/types"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"

export function TrackedPanel() {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [showResolved, setShowResolved] = useState(false)

  const { data: events = [] } = useQuery({
    queryKey: ["events", showResolved ? "all" : "active"],
    queryFn: () => listEvents(showResolved ? undefined : "active"),
    refetchInterval: 15_000,
  })

  return (
    <div className="flex h-full">
      {/* Event list */}
      <div className="w-80 shrink-0 border-r border-border bg-muted/10 overflow-y-auto">
        <div className="sticky top-0 z-10 border-b border-border bg-background/95 px-3 py-2">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold">Tracked</h2>
            <button
              type="button"
              onClick={() => setShowResolved((v) => !v)}
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              {showResolved ? "Active only" : "Show resolved"}
            </button>
          </div>
        </div>
        {events.length === 0 ? (
          <div className="px-4 py-8 text-center text-sm text-muted-foreground">
            No tracked items yet.
            <br />
            <span className="text-xs">Click the eye icon on a GitHub envelope to track it.</span>
          </div>
        ) : (
          <div className="flex flex-col">
            {events.map((event) => (
              <EventCard
                key={event.id}
                event={event}
                active={selectedId === event.id}
                onClick={() => setSelectedId(event.id)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Event detail */}
      <div className="flex-1 overflow-y-auto">
        {selectedId ? (
          <EventDetail event={events.find((e) => e.id === selectedId) ?? null} />
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            Select a tracked item
          </div>
        )}
      </div>
    </div>
  )
}

function EventCard({
  event,
  active,
  onClick,
}: {
  event: TrackedEvent
  active: boolean
  onClick: () => void
}) {
  const newCount = event.new_updates

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full px-3 py-2.5 text-left transition-colors border-b border-border",
        active ? "bg-accent" : "hover:bg-accent/50",
        event.status === "resolved" && "opacity-60",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-xs text-muted-foreground">
          {event.source_id}
        </span>
        <div className="flex items-center gap-1">
          {newCount > 0 && (
            <span className="rounded-full bg-blue-500 px-1.5 py-px text-[10px] font-medium text-white">
              {newCount}
            </span>
          )}
          {event.status === "resolved" && (
            <Check className="h-3 w-3 text-muted-foreground" />
          )}
        </div>
      </div>
      <div className="mt-0.5 line-clamp-1 text-sm font-medium">{event.title}</div>
      {event.agent_summary && (
        <div className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">
          {event.agent_summary.slice(0, 100)}
        </div>
      )}
    </button>
  )
}

function EventDetail({
  event,
}: {
  event: TrackedEvent | null
}) {
  const qc = useQueryClient()

  const { data: freshEvent } = useQuery({
    queryKey: ["event", event?.id],
    queryFn: () => getEvent(event!.id),
    enabled: !!event,
    refetchInterval: 15_000,
  })

  const ev = freshEvent ?? event

  const resolveMut = useMutation({
    mutationFn: (id: string) => resolveEvent(id),
    onSuccess: () => {
      toast.success("Resolved")
      qc.invalidateQueries({ queryKey: ["events"] })
    },
    onError: (e) => toast.error(String(e)),
  })

  const seenMut = useMutation({
    mutationFn: (id: string) => markUpdatesSeen(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["events"] })
      qc.invalidateQueries({ queryKey: ["event", ev?.id] })
    },
  })

  const analyzeMut = useMutation({
    mutationFn: (id: string) => analyzeEvent(id),
    onSuccess: () => {
      toast.success("Analysis complete")
      qc.invalidateQueries({ queryKey: ["events"] })
      qc.invalidateQueries({ queryKey: ["event", ev?.id] })
    },
    onError: (e) => toast.error(String(e)),
  })

  if (!ev) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Event not found
      </div>
    )
  }

  return (
    <div className="space-y-5 px-6 pb-6 pt-5">
      <header className="space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Eye className="h-3 w-3" />
            <span className="uppercase">{ev.source}</span>
            <span>·</span>
            <span>{ev.source_id}</span>
            {ev.status === "resolved" && (
              <span className="rounded bg-muted px-1 py-px text-[10px]">resolved</span>
            )}
          </div>
          <div className="flex items-center gap-1">
            {ev.status === "active" && (
              <>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => analyzeMut.mutate(ev.id)}
                  disabled={analyzeMut.isPending}
                >
                  <RotateCcw className="mr-1 h-3 w-3" />
                  Re-analyze
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => resolveMut.mutate(ev.id)}
                  disabled={resolveMut.isPending}
                >
                  <Check className="mr-1 h-3 w-3" />
                  Resolve
                </Button>
              </>
            )}
          </div>
        </div>
        <h1 className="text-base font-semibold leading-snug">{ev.title}</h1>
      </header>

      {/* Agent summary */}
      {ev.agent_summary && (
        <section className="space-y-2">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Agent Summary
          </h2>
          <div className="rounded-lg border border-border bg-muted/30 p-3 text-sm">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{ev.agent_summary}</ReactMarkdown>
          </div>
        </section>
      )}

      {/* Updates timeline */}
      {ev.updates.length > 0 && (
        <section className="space-y-2">
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Updates ({ev.updates.length})
            </h2>
            {ev.new_updates > 0 && (
              <button
                type="button"
                onClick={() => seenMut.mutate(ev.id)}
                className="text-xs text-muted-foreground hover:text-foreground"
              >
                Mark all seen
              </button>
            )}
          </div>
          <div className="space-y-2">
            {ev.updates.map((update) => (
              <UpdateCard key={update.id} update={update} />
            ))}
          </div>
        </section>
      )}

      {ev.updates.length === 0 && (
        <div className="flex flex-col items-center gap-2 py-8 text-sm text-muted-foreground">
          <MessageSquare className="h-6 w-6 opacity-40" />
          <span>No updates yet — new comments will appear here</span>
        </div>
      )}
    </div>
  )
}

function UpdateCard({ update }: { update: EventUpdate }) {
  return (
    <div
      className={cn(
        "rounded-lg border border-border p-3",
        !update.seen && "border-l-2 border-l-blue-500",
      )}
    >
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>{update.author}</span>
        <div className="flex items-center gap-2">
          <span>{update.created_at ? new Date(update.created_at).toLocaleDateString() : ""}</span>
          {update.html_url && (
            <a
              href={update.html_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-500 hover:underline"
            >
              link
            </a>
          )}
        </div>
      </div>
      <div className="mt-1 text-sm">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{update.body}</ReactMarkdown>
      </div>
    </div>
  )
}
