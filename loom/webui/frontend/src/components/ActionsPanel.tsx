import { useMutation, useQueryClient } from "@tanstack/react-query"
import { ExternalLink, Eye, Bot, Copy, Check, X } from "lucide-react"
import { toast } from "sonner"

import { approveEnvelope, dismissEnvelope } from "@/lib/api"
import type { Envelope } from "@/lib/types"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
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
      <div className="flex flex-col gap-3 border-t border-border bg-muted/10 px-5 py-4">
        <div className="flex flex-col gap-2">
          <PrimaryAction
            icon={<ExternalLink className="h-4 w-4" />}
            label="Open in source"
            disabledReason={sourceUrl ? null : "No URL in metadata"}
            onClick={() =>
              sourceUrl && window.open(sourceUrl, "_blank", "noopener,noreferrer")
            }
          />
          <PrimaryAction
            icon={<Eye className="h-4 w-4" />}
            label="Track"
            disabledReason="Coming in Phase 2"
            onClick={() => {}}
          />
          <PrimaryAction
            icon={<Bot className="h-4 w-4" />}
            label="Open in Agent"
            secondaryIcon={<Copy className="h-3 w-3" />}
            disabledReason={null}
            onClick={openInAgent}
          />
        </div>

        <Separator />

        <div className="flex items-center justify-between gap-2">
          <div className="text-xs text-muted-foreground">
            {canApprove
              ? "Ready for review"
              : isTerminal
                ? `status: ${envelope.status}`
                : "Awaiting processing"}
          </div>
          <div className="flex items-center gap-1">
            <IconReviewBtn
              label="Approve"
              icon={<Check className="h-4 w-4" />}
              color="text-emerald-600"
              disabled={!canApprove || approveMut.isPending}
              onClick={() => approveMut.mutate(envelope.id)}
            />
            <IconReviewBtn
              label="Dismiss"
              icon={<X className="h-4 w-4" />}
              color="text-rose-600"
              disabled={isTerminal || dismissMut.isPending}
              onClick={() => dismissMut.mutate(envelope.id)}
            />
          </div>
        </div>
      </div>
    </TooltipProvider>
  )
}

function PrimaryAction({
  icon,
  label,
  secondaryIcon,
  disabledReason,
  onClick,
}: {
  icon: React.ReactNode
  label: string
  secondaryIcon?: React.ReactNode
  disabledReason: string | null
  onClick: () => void
}) {
  const btn = (
    <Button
      variant="outline"
      size="sm"
      disabled={!!disabledReason}
      onClick={onClick}
      className="justify-start gap-2"
    >
      {icon}
      <span className="flex-1 text-left">{label}</span>
      {secondaryIcon}
    </Button>
  )
  if (!disabledReason) return btn
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="inline-block">{btn}</span>
      </TooltipTrigger>
      <TooltipContent side="left">{disabledReason}</TooltipContent>
    </Tooltip>
  )
}

function IconReviewBtn({
  label,
  icon,
  color,
  disabled,
  onClick,
}: {
  label: string
  icon: React.ReactNode
  color: string
  disabled: boolean
  onClick: () => void
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          disabled={disabled}
          onClick={onClick}
          className={cn("h-8 w-8", !disabled && color)}
          aria-label={label}
        >
          {icon}
        </Button>
      </TooltipTrigger>
      <TooltipContent side="top">{label}</TooltipContent>
    </Tooltip>
  )
}
