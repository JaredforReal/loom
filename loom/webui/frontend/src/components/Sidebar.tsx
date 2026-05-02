import { useQuery } from "@tanstack/react-query"
import { Archive, Inbox } from "lucide-react"

import { listSources } from "@/lib/api"
import { cn } from "@/lib/utils"
import { SettingsPopover } from "./SettingsPopover"

interface SidebarProps {
  sourceFilter: string | null
  onSourceFilter: (source: string | null) => void
  showArchived: boolean
  onToggleArchived: () => void
}

export function Sidebar({
  sourceFilter,
  onSourceFilter,
  showArchived,
  onToggleArchived,
}: SidebarProps) {
  const { data: sources = [] } = useQuery({
    queryKey: ["sources"],
    queryFn: listSources,
    refetchInterval: 15_000,
  })

  return (
    <aside className="flex h-full w-[240px] shrink-0 flex-col border-r border-border bg-muted/20">
      <div className="flex h-12 items-center gap-2 px-4">
        <div className="h-5 w-5 rounded-md bg-foreground" aria-hidden />
        <span className="text-sm font-semibold tracking-tight">Loom</span>
      </div>

      <nav className="flex flex-1 flex-col gap-4 overflow-y-auto px-2 py-2">
        <Section title="Sources">
          <SidebarRow
            icon={<Inbox className="h-4 w-4" />}
            label="All"
            active={sourceFilter === null}
            onClick={() => onSourceFilter(null)}
          />
          {sources.map((s) => (
            <SidebarRow
              key={s.kind}
              label={s.kind}
              badge={s.unread || undefined}
              active={sourceFilter === s.kind}
              onClick={() => onSourceFilter(s.kind)}
            />
          ))}
        </Section>

        <Section title="View">
          <SidebarRow
            icon={<Archive className="h-4 w-4" />}
            label={showArchived ? "Hide archived" : "Show archived"}
            active={showArchived}
            onClick={onToggleArchived}
          />
        </Section>
      </nav>

      <div className="flex items-center justify-between border-t border-border px-3 py-2">
        <span className="text-xs text-muted-foreground">loom 0.1.0</span>
        <SettingsPopover current={sourceFilter} onChange={onSourceFilter} />
      </div>
    </aside>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <h3 className="px-2 pb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h3>
      {children}
    </div>
  )
}

interface SidebarRowProps {
  icon?: React.ReactNode
  label: string
  badge?: number
  active: boolean
  onClick: () => void
}

function SidebarRow({ icon, label, badge, active, onClick }: SidebarRowProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors",
        active
          ? "bg-accent text-accent-foreground"
          : "text-muted-foreground hover:bg-accent/60 hover:text-foreground"
      )}
    >
      {icon ?? <span className="inline-block h-1.5 w-1.5 rounded-full bg-current opacity-60" />}
      <span className="flex-1 truncate">{label}</span>
      {badge !== undefined && badge > 0 && (
        <span className="text-xs tabular-nums text-muted-foreground">{badge}</span>
      )}
    </button>
  )
}
