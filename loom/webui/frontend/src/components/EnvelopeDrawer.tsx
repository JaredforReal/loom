import { useQuery } from "@tanstack/react-query"

import { getEnvelope } from "@/lib/api"
import type { Envelope } from "@/lib/types"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog"
import { ScrollArea } from "@/components/ui/scroll-area"
import { EnvelopeDetail } from "./EnvelopeDetail"
import { ActionsPanel } from "./ActionsPanel"

interface EnvelopeDrawerProps {
  envelopeId: string | null
  onClose: () => void
}

export function EnvelopeDrawer({ envelopeId, onClose }: EnvelopeDrawerProps) {
  const { data } = useQuery({
    queryKey: ["envelope", envelopeId],
    queryFn: () => (envelopeId ? getEnvelope(envelopeId) : Promise.resolve(null)),
    enabled: !!envelopeId,
  })

  const envelope: Envelope | null =
    data && !("error" in (data as object)) ? (data as Envelope) : null

  return (
    <Dialog open={!!envelopeId} onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        className="right-0 top-0 h-full w-[40vw] min-w-[560px] max-w-[720px] translate-x-0 rounded-none border-l border-border p-0
                   data-[state=open]:slide-in-from-right
                   data-[state=closed]:slide-out-to-right"
      >
        <DialogTitle className="sr-only">
          {envelope?.title || "Envelope detail"}
        </DialogTitle>
        <DialogDescription className="sr-only">
          Envelope detail and actions
        </DialogDescription>
        <div className="flex h-full flex-col">
          <ScrollArea className="flex-1">
            <EnvelopeDetail envelopeId={envelopeId} />
          </ScrollArea>
          <ActionsPanel envelope={envelope} />
        </div>
      </DialogContent>
    </Dialog>
  )
}
