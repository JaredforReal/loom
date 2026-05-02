import { useEffect, useState } from "react"
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { AlertTriangle, RefreshCw } from "lucide-react"
import { toast } from "sonner"

import { getConfig, restartDaemon, saveConfig } from "@/lib/config"
import { Button } from "@/components/ui/button"
import { ConfigEditor } from "./ConfigEditor"

export function ConfigPanel() {
  const qc = useQueryClient()
  const [draft, setDraft] = useState<string>("")
  const [error, setError] = useState<string | null>(null)
  const [restartRequired, setRestartRequired] = useState<string[]>([])

  const { data: config } = useQuery({
    queryKey: ["config"],
    queryFn: getConfig,
  })

  useEffect(() => {
    if (config) {
      setDraft(config.content)
      setError(null)
    }
  }, [config])

  const saveMutation = useMutation({
    mutationFn: (content: string) => saveConfig(content),
    onSuccess: (data) => {
      setError(null)
      setRestartRequired(data.restart_required)
      if (data.restart_required.length > 0) {
        toast.warning(
          `Saved · daemon restart required for: ${data.restart_required.join(", ")}`,
        )
      } else if (data.changed.length > 0) {
        toast.success(`Saved · hot-reloaded: ${data.changed.join(", ")}`)
      } else {
        toast.success("Saved · no changes detected")
      }
      qc.invalidateQueries({ queryKey: ["config"] })
      qc.invalidateQueries({ queryKey: ["sources"] })
      qc.invalidateQueries({ queryKey: ["groups"] })
    },
    onError: (err: Error) => {
      setError(err.message)
      toast.error(err.message)
    },
  })

  const restartMutation = useMutation({
    mutationFn: () => restartDaemon(),
    onSuccess: () => {
      toast.success("Daemon restarting — page will reload shortly")
      setRestartRequired([])
      // Reload after a few seconds to reconnect
      setTimeout(() => window.location.reload(), 3000)
    },
    onError: (err: Error) => toast.error(err.message),
  })

  const isDirty = config !== undefined && draft !== config.content

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center justify-between border-b border-border px-4 py-2">
        <div className="flex items-center gap-2 text-sm">
          <span className="font-medium">config.yaml</span>
          {config && (
            <span className="font-mono text-xs text-muted-foreground">
              {config.path}
            </span>
          )}
          {isDirty && (
            <span className="text-xs text-amber-500">· unsaved</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {restartRequired.length > 0 && (
            <Button
              size="sm"
              variant="destructive"
              onClick={() => restartMutation.mutate()}
              disabled={restartMutation.isPending}
            >
              <RefreshCw className="mr-1 h-3.5 w-3.5" />
              {restartMutation.isPending ? "Restarting…" : "Restart daemon"}
            </Button>
          )}
          <Button
            size="sm"
            onClick={() => saveMutation.mutate(draft)}
            disabled={!isDirty || saveMutation.isPending}
          >
            {saveMutation.isPending ? "Saving…" : "Save"}
          </Button>
        </div>
      </div>

      {restartRequired.length > 0 && (
        <div className="flex shrink-0 items-center gap-2 border-b border-amber-500/30 bg-amber-500/10 px-4 py-2 text-xs text-amber-700 dark:text-amber-400">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          <span>
            Saved, but the following changes need a daemon restart to take effect:{" "}
            <strong>{restartRequired.join(", ")}</strong>
          </span>
        </div>
      )}

      {error && (
        <div className="border-b border-destructive/30 bg-destructive/10 px-4 py-2 text-xs text-destructive">
          {error}
        </div>
      )}

      <div className="flex-1 overflow-hidden">
        <ConfigEditor value={draft} onChange={setDraft} />
      </div>
    </div>
  )
}
