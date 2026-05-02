import { useMutation, useQueryClient } from "@tanstack/react-query"
import { ExternalLink, Bot, Check, X } from "lucide-react"
import { toast } from "sonner"

import { approveEnvelope, dismissEnvelope } from "@/lib/api"
import type { Envelope } from "@/lib/types"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"

interface ActionsPanelProps {
  envelope: Envelope | null
}

function extractSourceUrl(envelope: Envelope): string | null {
  const md = (envelope.metadata ?? {}) as Record<string, unknown>
  const candidates = ["html_url", "permalink", "url", "link"] as const
  for (const key of candidates) {
    const v = md[key]
    if (typeof v === "string" && v.startsWith("http")) return v
  }
  return null
}

export function ActionsPanel({ envelope }: ActionsPanelProps) {
  const qc = useQueryClient()

  const approveMut = useMutation({
    mutationFn: (id: string) => approveEnvelope(id),
    onSuccess: (_, id) => {
      toast.success("Approved")
      qc.invalidateQueries({ queryKey: ["envelopes"] })
      qc.invalidateQueries({ queryKey: ["envelope", id] })
    },
    onError: (e) => toast.error(String(e)),
  })

  const dismissMut = useMutation({
    mutationFn: (id: string) => dismissEnvelope(id),
    onSuccess: (_, id) => {
      toast.success("Dismissed")
      qc.invalidateQueries({ queryKey: ["envelopes"] })
      qc.invalidateQueries({ queryKey: ["envelope", id] })
    },
    onError: (e) => toast.error(String(e)),
  })

  if (!envelope) return null

  const sourceUrl = extractSourceUrl(envelope)
  const canApprove = envelope.status === "waiting_approval"
  const isTerminal =
    envelope.status === "done" ||
    envelope.status === "dismissed" ||
    envelope.status === "failed"

  const openInAgent = async () => {
    try {
      await navigator.clipboard.writeText(envelope.id)
      toast.success("Envelope id copied", {
        description: "Paste it into your agent. Jump-out protocol TBD.",
      })
    } catch {
      toast.error("Clipboard blocked")
    }
  }

  return (
    <TooltipProvider delayDuration={150}>
      <div className="flex h-9 shrink-0 items-center justify-between border-t border-border bg-muted/10 px-3">
        <div className="flex items-center gap-0.5">
          <IconButton
            label="Open in source"
            disabled={!sourceUrl}
            onClick={() =>
              sourceUrl && window.open(sourceUrl, "_blank", "noopener,noreferrer")
            }
          >
            <ExternalLink className="h-3.5 w-3.5" />
          </IconButton>
          <IconButton
            label="Open in Agent"
            onClick={openInAgent}
          >
            <Bot className="h-3.5 w-3.5" />
          </IconButton>
        </div>
        <div className="flex items-center gap-0.5">
          <IconButton
            label="Approve"
            disabled={!canApprove || approveMut.isPending}
            onClick={() => approveMut.mutate(envelope.id)}
            className={cn(!canApprove || "text-emerald-600 hover:text-emerald-700")}
          >
            <Check className="h-3.5 w-3.5" />
          </IconButton>
          <IconButton
            label="Dismiss"
            disabled={isTerminal || dismissMut.isPending}
            onClick={() => dismissMut.mutate(envelope.id)}
            className={cn(isTerminal || "text-rose-600 hover:text-rose-700")}
          >
            <X className="h-3.5 w-3.5" />
          </IconButton>
        </div>
      </div>
    </TooltipProvider>
  )
}

function IconButton({
  label,
  disabled,
  onClick,
  className,
  children,
}: {
  label: string
  disabled?: boolean
  onClick: () => void
  className?: string
  children: React.ReactNode
}) {
  const btn = (
    <Button
      variant="ghost"
      size="icon"
      disabled={disabled}
      onClick={onClick}
      className={cn("h-7 w-7", className)}
      aria-label={label}
    >
      {children}
    </Button>
  )
  if (disabled) return <span className="inline-flex">{btn}</span>
  return (
    <Tooltip>
      <TooltipTrigger asChild>{btn}</TooltipTrigger>
      <TooltipContent side="top">{label}</TooltipContent>
    </Tooltip>
  )
}
