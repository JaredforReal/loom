import { Badge } from "@/components/ui/badge"
import { contrastTextColor } from "@/lib/utils"

export function Label({ name, color }: { name: string; color?: string }) {
  if (!color) {
    return (
      <Badge variant="outline" className="text-xs font-medium">
        {name}
      </Badge>
    )
  }
  return (
    <span
      className="inline-flex items-center rounded-md border border-transparent px-1.5 py-0.5 text-xs font-medium"
      style={{
        backgroundColor: `#${color}`,
        color: contrastTextColor(color),
      }}
    >
      {name}
    </span>
  )
}
