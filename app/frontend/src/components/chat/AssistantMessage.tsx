import { memo, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import type { Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Check, ChevronDown, CircleAlert, ShieldCheck, TriangleAlert } from 'lucide-react'
import { RefChip, Spinner } from '@/components/sb/primitives'
import { hitlDetails, remarkCitations, splitCheckerNote } from '@/lib/answer'
import { cn } from '@/lib/utils'
import type { Message } from '@/types/chat'

const STAGES = ['Orchestrator', 'Researcher', 'Checker'] as const

interface AssistantMessageProps {
  message: Message
  hoverRef: number | null
  onHoverRef: (ref: number | null) => void
  onCite: (ref: number) => void
  onApprove: () => void
  onDeny: () => void
  tight: boolean
}

function useElapsed(startedAt: number | undefined, live: boolean) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!live) return
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [live])
  return startedAt ? Math.max(0, Math.floor((now - startedAt) / 1000)) : 0
}

const MarkdownBody = memo(function MarkdownBody({
  content,
  hoverRef,
  onHoverRef,
  onCite,
}: {
  content: string
  hoverRef: number | null
  onHoverRef: (ref: number | null) => void
  onCite: (ref: number) => void
}) {
  const components = useMemo<Components>(
    () => ({
      cite: ({ node, children }) => {
        const raw = (node?.properties?.dataRef as number | string | undefined) ?? String(children)
        const n = Number(raw)
        return (
          <RefChip
            n={n}
            active={hoverRef === n}
            onEnter={() => onHoverRef(n)}
            onLeave={() => onHoverRef(null)}
            onClick={() => onCite(n)}
          />
        )
      },
      a: ({ href, children }) => (
        <a href={href} target="_blank" rel="noreferrer">
          {children}
        </a>
      ),
      table: ({ children }) => (
        <div className="sb-table-wrap">
          <table>{children}</table>
        </div>
      ),
    }),
    [hoverRef, onCite, onHoverRef]
  )

  return (
    <ReactMarkdown remarkPlugins={[remarkGfm, remarkCitations]} components={components}>
      {content}
    </ReactMarkdown>
  )
})

function StatusBar({
  message,
  expanded,
  onToggle,
  tight,
}: {
  message: Message
  expanded: boolean
  onToggle: () => void
  tight: boolean
}) {
  const live = message.runStatus === 'running' || message.runStatus === 'writing' || message.runStatus === 'waiting'
  const elapsed = useElapsed(message.startedAt, live)
  const hasTrace = Boolean(message.trace?.length)

  const status = message.runStatus ?? (message.status === 'failed' ? 'failed' : message.interrupted ? 'paused' : 'done')
  const lastStep = message.trace?.[message.trace.length - 1]
  const statusText =
    status === 'waiting'
      ? 'Waiting for your approval'
      : status === 'writing'
        ? 'Writing answer…'
        : status === 'done'
          ? 'Research complete'
          : status === 'failed'
            ? 'Run failed'
            : status === 'paused'
              ? 'Paused for approval'
              : `${lastStep?.label ?? 'Working'}…`
  const stage = message.stage ?? (status === 'done' ? 3 : 0)
  const seconds = live ? elapsed : message.durationS

  return (
    <button
      type="button"
      onClick={hasTrace ? onToggle : undefined}
      aria-expanded={hasTrace ? expanded : undefined}
      className={cn(
        'mb-[22px] flex h-[38px] w-full max-w-[640px] items-center gap-3 overflow-hidden rounded-[10px] border border-line bg-transparent px-3 text-left text-[12.5px] font-medium text-ink2',
        hasTrace ? 'cursor-pointer hover:bg-bg1' : 'cursor-default'
      )}
    >
      {(status === 'running' || status === 'writing') && <Spinner />}
      {status === 'waiting' && <span className="sb-pulse mx-[3px] h-2 w-2 flex-none rounded-full bg-warn" />}
      {status === 'done' && <Check size={14} className="flex-none text-ok" />}
      {(status === 'failed' || status === 'paused') && <CircleAlert size={14} className="flex-none text-warn" />}
      <span className="truncate text-ink">{statusText}</span>
      <span className="flex-1" />
      {!tight && (
        <span className="flex flex-none items-center gap-3">
          {STAGES.map((label, i) => (
            <span
              key={label}
              className="flex items-center gap-1.5"
              style={{
                color: i < stage ? 'var(--ink2)' : i === stage ? 'var(--acc)' : 'var(--ink3)',
                fontWeight: i === stage ? 600 : 500,
              }}
            >
              <span
                className="h-1.5 w-1.5 rounded-full"
                style={{ background: i < stage ? 'var(--ok)' : i === stage ? 'var(--acc)' : 'var(--line2)' }}
              />
              {label}
            </span>
          ))}
        </span>
      )}
      {seconds !== undefined && <span className="min-w-7 text-right font-mono text-[11.5px] font-medium text-ink3">{seconds}s</span>}
      {hasTrace && (
        <ChevronDown
          size={14}
          className="flex-none text-ink3 transition-transform duration-300 ease-[cubic-bezier(.16,1,.3,1)]"
          style={{ transform: expanded ? 'rotate(180deg)' : 'none' }}
        />
      )}
    </button>
  )
}

function Trace({ message }: { message: Message }) {
  return (
    <div className="-mt-2.5 mb-6 max-w-[640px] rounded-[10px] border border-line bg-bg1 py-1">
      {message.trace?.map((step, i) => (
        <div key={i} className="grid grid-cols-[96px_minmax(0,1fr)_auto_14px] items-center gap-3 px-3 py-[7px] text-[12.5px] max-sm:grid-cols-[minmax(0,1fr)_auto_14px]">
          <span className="text-[11.5px] font-semibold text-ink3 max-sm:hidden">{step.agent}</span>
          <span className="truncate text-ink">{step.label}</span>
          <span className="text-ink3 tabular-nums">{step.detail}</span>
          {step.running ? <Spinner size={13} /> : <Check size={13} className="text-ok" />}
        </div>
      ))}
    </div>
  )
}

function HitlCard({ message, onApprove, onDeny }: { message: Message; onApprove: () => void; onDeny: () => void }) {
  const hitl = message.hitl
  if (!hitl) return null
  const details = hitlDetails(hitl)
  return (
    <div
      data-screen-label="HITL approval"
      className="sb-rise mb-7 flex max-w-[640px] flex-col gap-3.5 rounded-[14px] border border-line2 bg-surface px-[22px] py-5 shadow-sb"
    >
      <div className="flex items-center gap-2 text-[13px] font-semibold">
        <TriangleAlert size={15} className="text-warn" />
        Agent wants to take an action
      </div>
      <p className="m-0 font-serif text-[20px] leading-[1.4] tracking-[-0.01em] text-pretty">{hitl.question ?? hitl.description ?? 'Approve this action?'}</p>
      {hitl.tool && (
        <div className="flex items-center gap-2 text-[12px] text-ink3">
          Tool
          <code className="rounded-md bg-bg1 px-[7px] py-0.5 font-mono text-[12px] font-medium text-ink">{hitl.tool}</code>
        </div>
      )}
      {details && (
        <pre className="m-0 max-h-60 overflow-auto rounded-[10px] bg-bg1 px-3.5 py-3 font-mono text-[12px] leading-[1.65] whitespace-pre-wrap text-ink2">
          {details}
        </pre>
      )}
      <div className="mt-0.5 flex justify-end gap-2">
        <button
          type="button"
          onClick={onDeny}
          className="h-9 cursor-pointer rounded-[10px] border border-line2 bg-transparent px-4 text-[13px] font-semibold text-ink hover:bg-bg1"
        >
          Deny
        </button>
        <button
          type="button"
          onClick={onApprove}
          className="h-9 cursor-pointer rounded-[10px] border-0 bg-acc px-[18px] text-[13px] font-semibold text-accink hover:brightness-110"
        >
          Approve
        </button>
      </div>
    </div>
  )
}

function CheckerFooter({ children }: { children: ReactNode }) {
  return (
    <div className="mt-[22px] flex max-w-[640px] flex-col gap-1.5 border-t border-line pt-4 text-[12.5px] text-ink2">{children}</div>
  )
}

export function AssistantMessage({ message, hoverRef, onHoverRef, onCite, onApprove, onDeny, tight }: AssistantMessageProps) {
  const [expanded, setExpanded] = useState(false)
  const { body, checker } = useMemo(() => splitCheckerNote(message.content), [message.content])
  const done = (message.runStatus ?? 'done') === 'done' && message.status !== 'failed'
  const checkerRan = message.trace?.some((s) => s.agent === 'Checker' && !s.running)

  return (
    <div className="mb-12">
      <StatusBar message={message} expanded={expanded} onToggle={() => setExpanded((v) => !v)} tight={tight} />
      {expanded && <Trace message={message} />}
      <HitlCard message={message} onApprove={onApprove} onDeny={onDeny} />
      {message.hitlResult && <p className="-mt-2 mb-[22px] text-[12.5px] text-ink3">{message.hitlResult}</p>}

      {body && (
        <div className="sb-answer sb-rise">
          <MarkdownBody content={body} hoverRef={hoverRef} onHoverRef={onHoverRef} onCite={onCite} />
          {message.runStatus === 'writing' && <span className="sb-caret" aria-hidden />}
        </div>
      )}

      {done && body && checker && (
        <CheckerFooter>
          <div className="flex flex-wrap items-center gap-x-[18px] gap-y-1.5">
            <span className="flex items-center gap-[7px] font-semibold text-ink">
              <ShieldCheck size={14} className="text-ok" />
              Checker revised this answer
            </span>
            {checker.flags.length > 0 && (
              <span className="flex items-center gap-[7px]">
                <span className="h-[7px] w-[7px] rounded-full bg-warn" />
                {checker.flags.length} flagged
              </span>
            )}
          </div>
          {checker.flags.map((flag, i) => (
            <div key={i} className="flex gap-2.5 leading-normal">
              <span className="mt-[6px] h-[7px] w-[7px] flex-none rounded-full bg-warn" />
              <span>
                <strong className="font-semibold text-ink">Checker flag.</strong> {flag}
              </span>
            </div>
          ))}
          {checker.removed.length > 0 && (
            <span className="text-ink3">Removed as ungrounded: {checker.removed.join(', ')}</span>
          )}
          {checker.suggested.length > 0 && (
            <span className="text-ink3">Needs a citation: {checker.suggested.join('; ')}</span>
          )}
        </CheckerFooter>
      )}

      {done && body && !checker && checkerRan && (
        <CheckerFooter>
          <span className="flex items-center gap-[7px] font-semibold text-ink">
            <ShieldCheck size={14} className="text-ok" />
            Checker verified the claims against their excerpts
          </span>
        </CheckerFooter>
      )}
    </div>
  )
}
