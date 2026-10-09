import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Check } from 'lucide-react'
import { RefChip, Wordmark } from '@/components/sb/primitives'
import { useThemeStore } from '@/stores/themeStore'

const REPO_URL = 'https://github.com/suryaanshrai/scibot'
const COMMAND = 'docker compose up'
const EASE = 'cubic-bezier(.16,1,.3,1)'
const PAD_X = 'clamp(20px,5vw,72px)'

type Part = { text: string } | { ref: number }

const parse = (t: string): Part[] =>
  t
    .replace(/ \{/g, ' {')
    .split(/\{(\d+)\}/)
    .map((s, i) => (i % 2 ? { ref: Number(s) } : { text: s }))
    .filter((p) => ('ref' in p ? p.ref : p.text))

const BLOCKS: { lead?: string; t: string; note?: string }[] = [
  { t: '“Attention Is All You Need” introduces the Transformer, a sequence transduction model built entirely on attention mechanisms, replacing the recurrent layers used in encoder–decoder architectures {2}.' },
  { lead: 'Self-attention. ', t: 'Representations are computed without sequence-aligned RNNs or convolutions, relating different positions of a single sequence {2}{14}.' },
  {
    lead: 'Encoder–decoder structure. ',
    t: 'The overall layout is kept, built from stacked self-attention and point-wise feed-forward layers {3}.',
    note: 'Excerpt [3] supports the overall layout only. An ungrounded citation was removed.',
  },
  { lead: 'Decoder. ', t: 'A third sub-layer performs multi-head attention over the encoder output {8}.' },
]

const SOURCES = [
  { ref: 2, section: 'Abstract', snippet: 'Proposes the Transformer, an architecture based solely on attention mechanisms.', score: '0.94' },
  { ref: 3, section: '3 Model Architecture', snippet: 'Encoder–decoder structure using stacked self-attention and point-wise layers.', score: '0.88' },
  { ref: 8, section: '3.1 Encoder and Decoder Stacks', snippet: 'The decoder inserts a third sub-layer for attention over the encoder output.', score: '0.86' },
  { ref: 14, section: '2 Background', snippet: 'Self-attention relates positions of a single sequence to compute its representation.', score: '0.77' },
]

const AGENTS = [
  { name: 'Orchestrator', text: 'Breaks your question into sub-queries and decides which tools to use: your collection, arXiv, PubMed, whitelisted web search, or data analysis.' },
  { name: 'Researcher', text: 'Retrieves excerpts from the vector store, queries live databases at runtime, and drafts an answer with numbered citations.' },
  { name: 'Checker', text: 'Tests every claim against its excerpt. Unsupported claims are flagged and ungrounded citations are removed before you read the answer.' },
]

const PRINCIPLES = [
  { title: 'OCR before LLMs', text: 'PDFs are read with OCR, videos are frame-sampled, and speech is transcribed locally. A model is consulted only when computation falls short.' },
  { title: 'Background workers', text: 'Ingestion and agent runs happen in separate workers, so the API stays responsive under heavy imports.' },
  { title: 'Rich metadata, no GraphRAG', text: 'Non-analytical data lives in a vector store with detailed metadata, giving comparable retrieval at a fraction of the cost.' },
  { title: 'Whitelisted web search', text: 'Search is limited to reliable domains, with DuckDuckGo, Tavily or SerpAPI as the engine.' },
]

const rise = (delay: number) => ({ animation: `sl-rise 1.1s ${EASE} ${delay}s both` })

function useCopy() {
  const [copied, setCopied] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(timer.current), [])
  const copy = () => {
    void navigator.clipboard?.writeText(COMMAND).catch(() => undefined)
    setCopied(true)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setCopied(false), 1800)
  }
  return { copied, copy }
}

function Specimen() {
  const [hover, setHover] = useState<number | null>(null)
  const [auto, setAuto] = useState(0)

  useEffect(() => {
    if (hover !== null) return
    const id = window.setInterval(() => setAuto((a) => (a + 1) % SOURCES.length), 2200)
    return () => window.clearInterval(id)
  }, [hover])

  const active = hover ?? SOURCES[auto].ref
  const leave = () => setHover(null)

  return (
    <div className="overflow-hidden rounded-[18px] border border-line2 bg-surface" style={{ boxShadow: 'var(--shadow-lg)' }}>
      <div className="flex h-[46px] items-center gap-3.5 border-b border-line px-5 text-[12.5px] text-ink3">
        <span className="font-semibold text-ink">Attention!</span>
        <span className="flex-1" />
        <span className="flex h-6 items-center gap-[7px] rounded-full border border-line2 px-2.5 font-mono text-[11px] font-medium whitespace-nowrap">
          <span className="h-1.5 w-1.5 rounded-full bg-ok" />
          gemini-2.5-flash
        </span>
      </div>
      <div className="flex flex-wrap">
        <div className="min-w-0" style={{ flex: '1 1 480px', padding: 'clamp(28px,4vw,56px)' }}>
          <h2 className="mb-5 mt-0 font-serif font-medium leading-tight tracking-[-0.018em]" style={{ fontSize: 'clamp(22px,2vw,27px)' }}>
            Can you give me a summary of the paper?
          </h2>
          <div className="mb-[26px] flex max-w-[620px] flex-wrap items-center gap-x-3.5 gap-y-2 rounded-[10px] border border-line px-3 py-[9px] text-[12.5px] text-ink2">
            <Check size={14} className="text-ok" />
            <span className="font-medium text-ink">Research complete</span>
            <span className="flex-1" />
            <span className="flex flex-wrap gap-3">
              {['Orchestrator', 'Researcher', 'Checker'].map((a) => (
                <span key={a} className="flex items-center gap-1.5">
                  <span className="h-1.5 w-1.5 rounded-full bg-ok" />
                  {a}
                </span>
              ))}
            </span>
            <span className="font-mono text-[11.5px] font-medium text-ink3">14s</span>
          </div>
          {BLOCKS.map((b, i) => (
            <div key={i} className="mb-4 max-w-[620px]">
              <p
                className="m-0 font-serif leading-[1.62] text-pretty"
                style={{
                  fontSize: 'clamp(17px,1.3vw,19px)',
                  textDecoration: b.note ? 'underline dotted' : 'none',
                  textDecorationColor: 'var(--warn)',
                  textDecorationThickness: '1.5px',
                  textUnderlineOffset: '5px',
                }}
              >
                {b.lead && <strong className="font-semibold">{b.lead}</strong>}
                {parse(b.t).map((p, j) =>
                  'ref' in p ? (
                    <RefChip key={j} n={p.ref} active={p.ref === active} onEnter={() => setHover(p.ref)} onLeave={leave} />
                  ) : (
                    <span key={j}>{p.text}</span>
                  )
                )}
              </p>
              {b.note && (
                <div className="mt-2.5 flex gap-2.5 text-[13px] leading-normal text-ink2">
                  <span className="mt-1.5 h-[7px] w-[7px] flex-none rounded-full bg-warn" />
                  <span>
                    <strong className="font-semibold text-ink">Checker flag.</strong> {b.note}
                  </span>
                </div>
              )}
            </div>
          ))}
        </div>
        <aside className="max-w-full border-l border-line bg-bg1 px-3.5 py-[22px]" style={{ flex: '1 1 280px' }}>
          <div className="flex items-baseline justify-between px-2 pb-3">
            <span className="font-serif text-[20px] font-medium">Sources</span>
            <span className="font-mono text-[11px] font-medium text-ink3">scibot-6en0qqqgm</span>
          </div>
          {SOURCES.map((s) => {
            const on = s.ref === active
            return (
              <div
                key={s.ref}
                onMouseEnter={() => setHover(s.ref)}
                onMouseLeave={leave}
                className="grid grid-cols-[28px_minmax(0,1fr)] gap-2.5 rounded-[10px] px-2 py-3 transition-colors duration-300"
                style={{ background: on ? 'var(--surface)' : 'transparent' }}
              >
                <span
                  className="flex h-[22px] items-center justify-center rounded-md font-mono text-[11px] font-semibold transition-colors duration-300"
                  style={{ background: on ? 'var(--acc)' : 'var(--surface)', color: on ? 'var(--accink)' : 'var(--ink2)' }}
                >
                  {s.ref}
                </span>
                <div className="min-w-0">
                  <div className="flex justify-between gap-2.5 text-[13px] font-semibold">
                    {s.section}
                    <span className="font-mono text-[11px] font-medium text-ink3">{s.score}</span>
                  </div>
                  <p className="mt-[5px] mb-0 font-serif text-[14px] leading-normal text-ink2">{s.snippet}</p>
                </div>
              </div>
            )
          })}
        </aside>
      </div>
    </div>
  )
}

export function LandingPage() {
  const { copied, copy } = useCopy()
  const setAccentOverride = useThemeStore((s) => s.setAccentOverride)

  // The landing page uses the teal accent from the design; the app keeps the user's accent.
  useEffect(() => {
    setAccentOverride('teal')
    return () => setAccentOverride(null)
  }, [setAccentOverride])

  const copyLabel = copied ? 'Copied' : 'Copy'
  const section = { paddingLeft: PAD_X, paddingRight: PAD_X }

  return (
    <div className="min-h-screen overflow-x-clip bg-bg font-ui text-[16px] text-ink">
      <nav
        className="sticky top-0 z-10 flex h-16 items-center gap-7 border-b border-line backdrop-blur-[10px]"
        style={{ ...section, background: 'color-mix(in oklch, var(--bg) 88%, transparent)' }}
      >
        <Wordmark className="flex-1 text-[25px]" />
        <a href="#how" className="hidden text-[14px] font-medium text-ink2 no-underline hover:text-acc sm:inline">How it works</a>
        <a href="#sources" className="hidden text-[14px] font-medium text-ink2 no-underline hover:text-acc sm:inline">Sources</a>
        <a href="#start" className="hidden text-[14px] font-medium text-ink2 no-underline hover:text-acc sm:inline">Quick start</a>
        <Link to="/chat" className="flex h-9 items-center rounded-[10px] bg-ink px-4 text-[13.5px] font-semibold text-bg no-underline">
          Open app
        </Link>
      </nav>

      <header
        data-screen-label="Hero"
        className="mx-auto max-w-[1440px]"
        style={{ padding: `clamp(72px,14vh,160px) ${PAD_X} clamp(56px,9vh,96px)` }}
      >
        <h1 className="m-0 max-w-[11ch] font-serif font-normal leading-[.92] tracking-[-0.04em]" style={{ fontSize: 'clamp(56px,10.5vw,168px)' }}>
          <span className="block" style={rise(0)}>Research,</span>
          <span className="block" style={rise(0.09)}>
            <em className="font-light">cited</em> and
          </span>
          <span className="block" style={rise(0.18)}>
            <em className="font-light">checked.</em>
          </span>
        </h1>
        <div className="flex flex-wrap items-end justify-between gap-8" style={{ marginTop: 'clamp(40px,7vh,72px)' }}>
          <p className="m-0 max-w-[44ch] leading-[1.55] text-pretty text-ink2" style={{ fontSize: 'clamp(17px,1.4vw,20px)', ...rise(0.3) }}>
            A multi-agent, multi-modal RAG assistant for intensive study and research. Bring papers, videos, repositories and live
            databases, and get answers grounded in them.
          </p>
          <div className="flex flex-wrap gap-2.5" style={rise(0.38)}>
            <button
              type="button"
              onClick={copy}
              className="flex h-12 flex-none cursor-pointer items-center gap-3.5 rounded-xl border border-line2 bg-surface py-0 pr-2 pl-[18px] font-mono text-[14px] font-medium whitespace-nowrap text-ink"
            >
              {COMMAND}
              <span className="flex h-8 items-center rounded-lg bg-acc px-3 font-ui text-[12.5px] font-semibold text-accink">{copyLabel}</span>
            </button>
            <a href="#start" className="flex h-12 flex-none items-center rounded-xl px-5 text-[14.5px] font-semibold whitespace-nowrap text-ink underline underline-offset-4 decoration-line2 hover:text-acc">
              Read the quick start
            </a>
          </div>
        </div>
      </header>

      <section data-screen-label="Specimen" className="mx-auto max-w-[1440px]" style={{ ...section, paddingBottom: 'clamp(96px,16vh,180px)' }}>
        <Specimen />
      </section>

      <section
        id="how"
        data-screen-label="How it works"
        className="mx-auto flex max-w-[1440px] scroll-mt-20 flex-wrap"
        style={{ ...section, paddingBottom: 'clamp(96px,16vh,180px)', gap: 'clamp(40px,6vw,96px)' }}
      >
        <h2 className="m-0 max-w-[9ch] font-serif font-normal leading-none tracking-[-0.03em]" style={{ flex: '1 1 380px', fontSize: 'clamp(40px,5vw,76px)' }}>
          Three agents, <em className="font-light">one answer.</em>
        </h2>
        <div className="flex flex-col" style={{ flex: '1.4 1 460px' }}>
          {AGENTS.map((a) => (
            <div key={a.name} className="grid gap-6 border-t border-line2 py-[26px] grid-cols-[minmax(120px,180px)_minmax(0,1fr)] max-sm:grid-cols-1 max-sm:gap-2">
              <span className="font-serif text-[24px] font-medium tracking-[-0.01em]">{a.name}</span>
              <p className="m-0 max-w-[52ch] text-[16px] leading-[1.6] text-pretty text-ink2">{a.text}</p>
            </div>
          ))}
          <p className="m-0 max-w-[60ch] border-t border-line2 pt-[26px] text-[14px] leading-[1.6] text-ink3">
            Chosen over ReAct for research work. When an action needs your say, such as fetching references, the agent pauses and asks.
          </p>
        </div>
      </section>

      <section
        id="sources"
        data-screen-label="Sources"
        className="scroll-mt-16 border-y border-line bg-bg1"
        style={{ padding: `clamp(80px,14vh,160px) ${PAD_X}` }}
      >
        <div className="mx-auto max-w-[1440px]">
          <p className="m-0 max-w-[22ch] font-serif font-normal leading-[1.12] tracking-[-0.025em] text-balance" style={{ fontSize: 'clamp(30px,4.2vw,64px)' }}>
            arXiv, PubMed, PDF, LaTeX, Markdown, images, audio, video, YouTube, GitHub, web pages and whole websites.{' '}
            <em className="font-light text-ink2">Plus Postgres, MongoDB, CSV and JSON, queried live.</em>
          </p>
          <div className="flex flex-wrap gap-x-16 gap-y-6" style={{ marginTop: 'clamp(48px,8vh,88px)' }}>
            {[
              'Each chat gets its own collection, so data from one line of study never pollutes another. Settings can be overridden per chat.',
              'References are fetched recursively through Semantic Scholar to the depth you choose, then ranked by citation count.',
              'Expose a collection, or all of your data, over MCP and use it as context in other tools.',
            ].map((t) => (
              <p key={t} className="m-0 max-w-[46ch] text-[16px] leading-[1.6] text-ink2" style={{ flex: '1 1 280px' }}>
                {t}
              </p>
            ))}
          </div>
        </div>
      </section>

      <section data-screen-label="Principles" className="mx-auto max-w-[1440px]" style={{ padding: `clamp(96px,16vh,180px) ${PAD_X}` }}>
        <h2 className="m-0 max-w-[14ch] font-serif font-normal leading-none tracking-[-0.03em]" style={{ fontSize: 'clamp(40px,5vw,76px)', marginBottom: 'clamp(40px,7vh,72px)' }}>
          Computation first, <em className="font-light">language models last.</em>
        </h2>
        <div className="grid gap-x-12" style={{ gridTemplateColumns: 'repeat(auto-fit,minmax(min(100%,300px),1fr))' }}>
          {PRINCIPLES.map((pr) => (
            <div key={pr.title} className="border-t border-line2 pt-6 pb-8">
              <h3 className="mt-0 mb-2.5 text-[16px] font-semibold">{pr.title}</h3>
              <p className="m-0 text-[15px] leading-[1.6] text-pretty text-ink2">{pr.text}</p>
            </div>
          ))}
        </div>
      </section>

      <section id="start" data-screen-label="Quick start" className="mx-auto max-w-[1440px] scroll-mt-20" style={{ ...section, paddingBottom: 'clamp(96px,16vh,180px)' }}>
        <div className="flex flex-wrap items-end justify-between gap-12 rounded-[18px] bg-ink text-bg" style={{ padding: 'clamp(32px,6vw,88px)' }}>
          <div style={{ flex: '1 1 360px' }}>
            <h2 className="m-0 font-serif font-normal leading-none tracking-[-0.03em]" style={{ fontSize: 'clamp(40px,5vw,76px)' }}>
              Run it <em className="font-light">locally.</em>
            </h2>
            <p className="mt-5 mb-0 max-w-[44ch] text-[16px] leading-[1.6] opacity-70">
              One command from the project root brings up the API, workers and frontend. Open the app at localhost:8080.
            </p>
          </div>
          <div className="flex max-w-[560px] flex-col gap-2.5" style={{ flex: '1 1 420px' }}>
            <button
              type="button"
              onClick={copy}
              className="flex h-14 w-full cursor-pointer items-center justify-between gap-4 rounded-xl py-0 pr-2.5 pl-5 text-left font-mono text-[15px] font-medium text-bg"
              style={{
                border: '1px solid color-mix(in oklch, var(--bg) 20%, transparent)',
                background: 'color-mix(in oklch, var(--bg) 6%, transparent)',
              }}
            >
              <span>
                <span className="opacity-50">$ </span>
                {COMMAND}
              </span>
              <span className="flex h-9 items-center rounded-lg bg-acc px-3.5 font-ui text-[13px] font-semibold text-accink">{copyLabel}</span>
            </button>
            <p className="m-0 text-[13px] leading-[1.6] opacity-60">
              Slow first build? Start dependencies alone with{' '}
              <code className="font-mono text-[12.5px] font-medium">docker compose -f docker-compose.dependencies.yml up -d</code>, then run
              the API, workers and frontend separately.
            </p>
          </div>
        </div>
      </section>

      <footer
        className="mx-auto flex max-w-[1440px] flex-wrap items-baseline gap-x-8 gap-y-4 border-t border-line pt-8 pb-12 text-[13.5px] text-ink3"
        style={section}
      >
        <Wordmark className="flex-1 text-[20px] text-ink" />
        <a href={REPO_URL} target="_blank" rel="noreferrer" className="text-ink2 underline-offset-4 hover:text-acc">GitHub</a>
        <a href={`${REPO_URL}/blob/master/LICENSE`} target="_blank" rel="noreferrer" className="text-ink2 underline-offset-4 hover:text-acc">License</a>
        <Link to="/chat" className="text-ink2 underline-offset-4 hover:text-acc">Open app</Link>
      </footer>
    </div>
  )
}
