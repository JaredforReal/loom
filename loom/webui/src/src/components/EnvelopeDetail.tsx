import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { ChevronRight } from "lucide-react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

import { getEnvelope } from "@/lib/api"
import type { Envelope } from "@/lib/types"
import { cn, formatRelativeTime } from "@/lib/utils"
import { Separator } from "@/components/ui/separator"
import { Label } from "./Label"

interface EnvelopeDetailProps {
  envelopeId: string | null
}

function pickLabelColors(env: Envelope): Record<string, string> {
  const md = env.metadata as Record<string, unknown> | undefined
  const raw = md?.label_colors
  if (raw && typeof raw === "object") return raw as Record<string, string>
  return {}
}

export function EnvelopeDetail({ envelopeId }: EnvelopeDetailProps) {
  const { data, isLoading } = useQuery({
    queryKey: ["envelope", envelopeId],
    queryFn: () => (envelopeId ? getEnvelope(envelopeId) : Promise.resolve(null)),
    enabled: !!envelopeId,
  })

  if (!envelopeId) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Select an envelope
      </div>
    )
  }
  if (isLoading || !data) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Loading…
      </div>
    )
  }
  if ("error" in data) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-destructive">
        {data.error}
      </div>
    )
  }

  const envelope = data as Envelope
  const colors = pickLabelColors(envelope)
  const displayLabels = envelope.labels.filter(
    (l) => !["pr", "issue", "open", "closed", "merged"].includes(l)
  )
  const md = envelope.metadata as Record<string, unknown>
  const assignees = Array.isArray(md.assignees) ? (md.assignees as string[]) : []
  const user = typeof md.user === "string" ? md.user : null
  const repo = typeof md.repo === "string" ? md.repo : null
  const kind = typeof md.kind === "string" ? md.kind : envelope.source

  return (
    <div className="space-y-5 px-6 pb-6 pt-5">
      <header className="space-y-2">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="uppercase">{envelope.source}</span>
          <span>·</span>
          <span>{envelope.source_id}</span>
        </div>
        <h1 className="pr-8 text-base font-semibold leading-snug">
          {envelope.title || "(no title)"}
        </h1>
        {displayLabels.length > 0 && (
          <div className="flex flex-wrap gap-1.5 pt-1">
            {displayLabels.map((l) => (
              <Label key={l} name={l} color={colors[l]} />
            ))}
          </div>
        )}
      </header>

      <section className="rounded-md border border-border bg-muted/20 px-3 py-2">
        <PropertyRow label="Status" value={envelope.status} />
        {user && <PropertyRow label="Author" value={user} />}
        {repo && <PropertyRow label="Repo" value={repo} />}
        <PropertyRow label="Kind" value={kind} />
        {envelope.received_at && (
          <PropertyRow
            label="Received"
            value={formatRelativeTime(envelope.received_at)}
          />
        )}
        {assignees.length > 0 && (
          <PropertyRow label="Assignees" value={assignees.join(", ")} />
        )}
      </section>

      {envelope.agent_summary && (
        <Section title="Agent summary">
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground/90">
            {envelope.agent_summary}
          </p>
        </Section>
      )}

      {envelope.proposed_action && (
        <Section title="Proposed action">
          <pre className="overflow-x-auto rounded-md border border-border bg-muted/40 p-3 text-xs">
            {JSON.stringify(envelope.proposed_action, null, 2)}
          </pre>
        </Section>
      )}

      {envelope.body && (
        <Section title="Body">
          <Markdown source={envelope.body} />
        </Section>
      )}

      {envelope.agent_log.length > 0 && (
        <Section title={`Agent log (${envelope.agent_log.length})`}>
          <AgentLogList entries={envelope.agent_log} />
        </Section>
      )}
    </div>
  )
}

function PropertyRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex min-h-8 items-center gap-3 rounded-md px-1 py-1 text-sm transition-colors hover:bg-accent/50">
      <span className="w-20 shrink-0 text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <span className="truncate text-foreground">{value}</span>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        {title}
      </h2>
      <Separator />
      {children}
    </section>
  )
}

function Markdown({ source }: { source: string }) {
  return (
    <div className="text-sm leading-relaxed text-foreground/90">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ node: _node, ...p }) => (
            <h1 className="mt-4 text-base font-semibold" {...p} />
          ),
          h2: ({ node: _node, ...p }) => (
            <h2 className="mt-4 text-sm font-semibold" {...p} />
          ),
          h3: ({ node: _node, ...p }) => (
            <h3 className="mt-3 text-sm font-semibold" {...p} />
          ),
          p: ({ node: _node, ...p }) => <p className="my-2" {...p} />,
          ul: ({ node: _node, ...p }) => (
            <ul className="my-2 list-disc space-y-1 pl-5" {...p} />
          ),
          ol: ({ node: _node, ...p }) => (
            <ol className="my-2 list-decimal space-y-1 pl-5" {...p} />
          ),
          li: ({ node: _node, ...p }) => <li className="my-0.5" {...p} />,
          code: ({ node: _node, className, children, ...rest }) => {
            const isBlock = /language-/.test(className || "")
            return isBlock ? (
              <code
                className="block overflow-x-auto whitespace-pre rounded-md bg-muted p-3 text-xs"
                {...rest}
              >
                {children}
              </code>
            ) : (
              <code
                className="rounded bg-muted px-1 py-0.5 text-xs"
                {...rest}
              >
                {children}
              </code>
            )
          },
          pre: ({ node: _node, ...p }) => (
            <pre className="my-2 overflow-x-auto rounded-md bg-muted text-xs" {...p} />
          ),
          a: ({ node: _node, ...p }) => (
            <a
              className="text-primary underline underline-offset-2"
              target="_blank"
              rel="noopener noreferrer"
              {...p}
            />
          ),
          blockquote: ({ node: _node, ...p }) => (
            <blockquote
              className="my-2 border-l-2 border-border pl-3 text-muted-foreground"
              {...p}
            />
          ),
          table: ({ node: _node, ...p }) => (
            <div className="my-2 overflow-x-auto">
              <table className="w-full border-collapse text-xs" {...p} />
            </div>
          ),
          th: ({ node: _node, ...p }) => (
            <th className="border border-border px-2 py-1 text-left" {...p} />
          ),
          td: ({ node: _node, ...p }) => (
            <td className="border border-border px-2 py-1" {...p} />
          ),
          hr: ({ node: _node, ...p }) => (
            <hr className="my-3 border-border" {...p} />
          ),
        }}
      >
        {source}
      </ReactMarkdown>
    </div>
  )
}

function AgentLogList({ entries }: { entries: Envelope["agent_log"] }) {
  const [openIdx, setOpenIdx] = useState<number | null>(null)
  return (
    <ul className="space-y-1">
      {entries.map((entry, i) => {
        const open = openIdx === i
        return (
          <li key={i} className="rounded-md border border-border">
            <button
              type="button"
              onClick={() => setOpenIdx(open ? null : i)}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-accent/40"
            >
              <ChevronRight
                className={cn("h-3 w-3 transition-transform", open && "rotate-90")}
              />
              <span className="font-medium">{entry.step ?? `step ${i + 1}`}</span>
              {entry.timestamp && (
                <span className="ml-auto text-muted-foreground">{entry.timestamp}</span>
              )}
            </button>
            {open && (
              <pre className="overflow-x-auto border-t border-border bg-muted/30 p-3 text-xs leading-relaxed">
                {JSON.stringify(entry, null, 2)}
              </pre>
            )}
          </li>
        )
      })}
    </ul>
  )
}
