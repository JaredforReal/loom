import { useEffect, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Settings } from "lucide-react"

import { listSources } from "@/lib/api"
import { getDefaultSource, setDefaultSource } from "@/lib/settings"
import { Button } from "@/components/ui/button"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"

interface SettingsPopoverProps {
  current: string | null
  onChange: (next: string | null) => void
}

export function SettingsPopover({ current, onChange }: SettingsPopoverProps) {
  const { data: sources = [] } = useQuery({
    queryKey: ["sources"],
    queryFn: listSources,
  })
  const [savedDefault, setSavedDefault] = useState<string | null>(() =>
    getDefaultSource()
  )

  useEffect(() => {
    setSavedDefault(getDefaultSource())
  }, [])

  const handleChange = (next: string | null) => {
    setDefaultSource(next)
    setSavedDefault(next)
    onChange(next)
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Settings">
          <Settings className="h-4 w-4" />
        </Button>
      </PopoverTrigger>
      <PopoverContent side="top" align="end" className="w-72 space-y-3">
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Default view
          </h4>
          <p className="mt-1 text-xs text-muted-foreground">
            Which source to show first when you open Loom.
          </p>
        </div>
        <select
          className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm outline-none focus:ring-1 focus:ring-ring"
          value={savedDefault ?? ""}
          onChange={(e) => handleChange(e.target.value || null)}
        >
          <option value="">All sources</option>
          {sources.map((s) => (
            <option key={s.name || s.kind} value={s.name || s.kind}>
              {s.name || s.kind}
            </option>
          ))}
        </select>
        <p className="text-xs text-muted-foreground">
          Saved locally. Temporary filter chips don&apos;t change this default.
        </p>
        {current !== savedDefault && (
          <p className="text-xs text-muted-foreground">
            Currently viewing{" "}
            <span className="font-medium text-foreground">
              {current ?? "All"}
            </span>
            {" "}— will reset to default on reload.
          </p>
        )}
      </PopoverContent>
    </Popover>
  )
}
