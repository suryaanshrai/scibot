import type { HITLPayload, Message, SourceRecord, TraceStep } from '@/types/chat'

// ── Checker note ─────────────────────────────────────────────────────────────
// The orchestrator appends the Checker's findings to the answer as a trailing
// blockquote (see app/agent/orchestrator.py `_run_checker`). We lift it out of
// the body and render it as a structured footer instead.

export interface CheckerReport {
  flags: string[]
  removed: string[]
  suggested: string[]
}

const CHECKER_LINE = /^>\s*\*\*(Checker flags|Ungrounded citations removed|Suggested citations)\*\*:\s*(.*)$/

export function splitCheckerNote(content: string): { body: string; checker: CheckerReport | null } {
  const lines = content.replace(/\s+$/, '').split('\n')
  const report: CheckerReport = { flags: [], removed: [], suggested: [] }
  let found = false

  while (lines.length) {
    const last = lines[lines.length - 1].trim()
    if (!last) {
      lines.pop()
      continue
    }
    const match = last.match(CHECKER_LINE)
    if (!match) break
    found = true
    lines.pop()
    const kind = match[1]
    if (kind === 'Checker flags') report.flags.unshift(...splitList(match[2], '; '))
    else if (kind === 'Ungrounded citations removed') report.removed.unshift(...splitList(match[2], ', '))
    else report.suggested.unshift(...splitList(match[2], '; '))
  }

  return { body: found ? lines.join('\n').replace(/\s+$/, '') : content, checker: found ? report : null }
}

function splitList(text: string, sep: string) {
  return text
    .split(sep)
    .map((item) => item.trim())
    .filter(Boolean)
}

// ── Citations ────────────────────────────────────────────────────────────────

const CITE_RE = /\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]/g

export function citedRefs(content: string): Set<number> {
  const refs = new Set<number>()
  for (const match of content.matchAll(CITE_RE)) {
    for (const n of match[1].split(',')) refs.add(Number(n.trim()))
  }
  return refs
}

interface MdNode {
  type: string
  value?: string
  children?: MdNode[]
  data?: { hName?: string; hProperties?: Record<string, unknown> }
}

/** remark plugin: turn `[3]` / `[2, 14]` in text into `<cite data-ref>` nodes. */
export function remarkCitations() {
  const transform = (node: MdNode) => {
    if (!node.children || node.type === 'link' || node.type === 'linkReference') return
    const next: MdNode[] = []
    for (const child of node.children) {
      if (child.type !== 'text' || !child.value || !CITE_RE.test(child.value)) {
        CITE_RE.lastIndex = 0
        transform(child)
        next.push(child)
        continue
      }
      CITE_RE.lastIndex = 0
      const value = child.value
      let last = 0
      for (const match of value.matchAll(CITE_RE)) {
        const index = match.index ?? 0
        if (index > last) next.push({ type: 'text', value: value.slice(last, index) })
        for (const n of match[1].split(',')) {
          next.push({
            type: 'citation',
            data: { hName: 'cite', hProperties: { dataRef: Number(n.trim()) } },
            children: [{ type: 'text', value: n.trim() }],
          })
        }
        last = index + match[0].length
      }
      if (last < value.length) next.push({ type: 'text', value: value.slice(last) })
    }
    node.children = next
  }
  return (tree: MdNode) => transform(tree)
}

// ── Sources ──────────────────────────────────────────────────────────────────

/** The excerpts the answer actually cites (falls back to all visible ones). */
export function citedSources(message: Message | undefined): SourceRecord[] {
  if (!message?.sources?.length) return []
  const visible = message.sources.filter((s) => !s.filtered)
  const refs = citedRefs(message.content)
  const cited = refs.size ? visible.filter((s) => refs.has(s.ref_id)) : []
  return (cited.length ? cited : visible).slice().sort((a, b) => a.ref_id - b.ref_id)
}

export function sourceDocLabel(source: SourceRecord) {
  if (source.url) {
    try {
      const url = new URL(source.url)
      return url.hostname.replace(/^www\./, '') + (url.pathname.length > 1 ? url.pathname : '')
    } catch {
      return source.url
    }
  }
  return source.tool_name ? source.tool_name.replace(/_/g, ' ') : source.source_type
}

// ── HITL ─────────────────────────────────────────────────────────────────────

export function normalizeHitl(payload: unknown): HITLPayload {
  const value = Array.isArray(payload) ? payload[0] : payload
  if (value && typeof value === 'object') return value as HITLPayload
  return { question: typeof value === 'string' ? value : 'Approve this action?' }
}

export function hitlDetails(payload: HITLPayload) {
  if (payload.details) return payload.details
  if (payload.args === undefined) return ''
  return typeof payload.args === 'string' ? payload.args : JSON.stringify(payload.args, null, 2)
}

// ── Agent trace ──────────────────────────────────────────────────────────────

export const TOOL_LABELS: Record<string, string> = {
  search_storage: 'Searched knowledge base',
  arxiv_search: 'Searched arXiv',
  pubmed_search: 'Searched PubMed',
  web_search: 'Searched the web',
  get_data: 'Loaded data',
  analyze_data: 'Analysed data',
  invoke_researcher: 'Ran researcher',
  fetch_references: 'Fetched references',
}

export function toolLabel(tool: string) {
  return TOOL_LABELS[tool] ?? `Ran ${tool.replace(/_/g, ' ')}`
}

type Patch = (m: Message) => Message

const finishRunning = (trace: TraceStep[] = [], detail?: string): TraceStep[] =>
  trace.map((step, i) =>
    step.running ? { ...step, running: false, detail: i === trace.length - 1 && detail ? detail : step.detail } : step
  )

export const trace = {
  start: (): Partial<Message> => ({
    runStatus: 'running',
    stage: 0,
    startedAt: Date.now(),
    trace: [{ agent: 'Orchestrator', label: 'Planning research', detail: '', running: true }],
  }),

  tool: (tool: string): Patch => (m) => ({
    ...m,
    runStatus: m.runStatus === 'writing' ? 'running' : m.runStatus,
    stage: Math.max(m.stage ?? 0, 1),
    trace: [...finishRunning(m.trace), { agent: 'Researcher', label: toolLabel(tool), detail: '', running: true }],
  }),

  sources: (count: number): Patch => (m) => ({
    ...m,
    trace: finishRunning(m.trace, `${count} excerpt${count === 1 ? '' : 's'}`),
  }),

  token: (): Patch => (m) =>
    m.runStatus === 'writing'
      ? m
      : { ...m, runStatus: 'writing', stage: Math.max(m.stage ?? 0, 1), trace: finishRunning(m.trace) },

  checker: (): Patch => (m) => ({
    ...m,
    runStatus: 'running',
    stage: 2,
    trace: [...finishRunning(m.trace), { agent: 'Checker', label: 'Verifying claims against excerpts', detail: '', running: true }],
  }),

  interrupt: (payload: HITLPayload): Patch => (m) => ({
    ...m,
    runStatus: 'waiting',
    hitl: payload,
    trace: finishRunning(m.trace),
  }),

  resume: (approved: boolean): Patch => (m) => {
    const tool = m.hitl?.tool ?? 'the action'
    return {
      ...m,
      hitl: null,
      runStatus: 'running',
      hitlResult: approved ? `You approved ${tool}` : `You denied ${tool} · answering without it`,
      trace: approved
        ? [...finishRunning(m.trace), { agent: 'Researcher', label: toolLabel(tool), detail: '', running: true }]
        : m.trace,
    }
  },

  done: (): Patch => (m) => {
    const { checker } = splitCheckerNote(m.content)
    const detail = checker
      ? [checker.flags.length && `${checker.flags.length} flagged`, checker.removed.length && `${checker.removed.length} removed`]
          .filter(Boolean)
          .join(' · ') || 'Revised'
      : 'No issues'
    const steps = finishRunning(m.trace)
    const hasChecker = steps.some((s) => s.agent === 'Checker')
    return {
      ...m,
      runStatus: 'done',
      stage: 3,
      durationS: m.startedAt ? Math.max(1, Math.round((Date.now() - m.startedAt) / 1000)) : undefined,
      trace: hasChecker
        ? steps.map((s) => (s.agent === 'Checker' ? { ...s, label: 'Verified claims against excerpts', detail } : s))
        : [...steps, { agent: 'Checker', label: 'Verified claims against excerpts', detail, running: false }],
    }
  },

  fail: (): Patch => (m) => ({ ...m, runStatus: 'failed', trace: finishRunning(m.trace) }),
}
