import { useQuery } from "@tanstack/react-query"
import { Circle } from "lucide-react"

import { getStatus } from "@/lib/api"
import { cn } from "@/lib/utils"

export function StatusBar() {
  const { data } = useQuery({
    queryKey: ["status"],
    queryFn: getStatus,
    refetchInterval: 5_000,
  })
  const online = !!data?.online
  const active = data?.active_sessions ?? 0
  const backlog = data?.queue_backlog ?? 0

  return (
    <footer className="flex h-10 items-center gap-4 border-t border-border bg-muted/30 px-4 text-xs text-muted-foreground">
      <div className="flex items-center gap-1.5">
        <Circle
          className={cn(
            "h-2 w-2 fill-current",
            online ? "text-emerald-500" : "text-muted-foreground/50"
          )}
        />
        <span>{online ? "daemon online" : "daemon offline"}</span>
      </div>
      <div>·</div>
      <div>{active} active sessions</div>
      <div>·</div>
      <div>{backlog} in queue</div>
      <div className="ml-auto font-mono text-[10px] opacity-60">loom 0.1.0</div>
    </footer>
  )
}
