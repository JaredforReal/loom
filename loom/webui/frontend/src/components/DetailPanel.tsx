import { useEffect } from "react"
import { useQuery } from "@tanstack/react-query"
import { X } from "lucide-react"

import { getEnvelope } from "@/lib/api"
import type { Envelope } from "@/lib/types"
import { ScrollArea } from "@/components/ui/scroll-area"
import { EnvelopeDetail } from "./EnvelopeDetail"
import { ActionsPanel } from "./ActionsPanel"

interface DetailPanelProps {
  envelopeId: string | null
  onClose: () => void
}

export function DetailPanel({ envelopeId, onClose }: DetailPanelProps) {
  const { data } = useQuery({
    queryKey: ["envelope", envelopeId],
    queryFn: () => (envelopeId ? getEnvelope(envelopeId) : Promise.resolve(null)),
    enabled: !!envelopeId,
  })

  const envelope: Envelope | null =
    data && !("error" in (data as object)) ? (data as Envelope) : null

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [onClose])

  return (
    <div className="flex h-full flex-col bg-background">
      <div className="flex h-10 shrink-0 items-center justify-between border-b border-border px-4">
        <span className="truncate text-xs font-medium text-muted-foreground">
          {envelope?.title || "Envelope detail"}
        </span>
        <button
          type="button"
          onClick={onClose}
          className="rounded-sm opacity-60 transition-opacity hover:opacity-100"
          aria-label="Close"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <ScrollArea className="flex-1">
        <EnvelopeDetail envelopeId={envelopeId} />
      </ScrollArea>
      <ActionsPanel envelope={envelope} />
    </div>
  )
}
