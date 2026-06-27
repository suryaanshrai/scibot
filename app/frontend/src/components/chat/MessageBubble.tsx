import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ChevronDown, ChevronUp, ExternalLink, Loader2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { Message } from '@/types/chat'

interface MessageBubbleProps {
  message: Message
}

function CitationBadge({ num }: { num: number }) {
  return (
    <sup>
      <span className="inline-flex items-center justify-center h-4 min-w-4 px-1 rounded text-[10px] font-semibold bg-primary/15 text-primary cursor-pointer hover:bg-primary/25 mx-0.5 transition-colors">
        {num}
      </span>
    </sup>
  )
}

function ToolCallCard({ name, status }: { name: string; status: 'running' | 'done' }) {
  const labels: Record<string, string> = {
    arxiv_search: 'Searching arXiv…',
    pubmed_search: 'Searching PubMed…',
    web_search: 'Searching the web…',
    search_storage: 'Searching knowledge base…',
    get_data: 'Loading data…',
    analyze_data: 'Analysing data…',
    invoke_researcher: 'Running researcher sub-agent…',
  }
  return (
    <div className={cn(
      'flex items-center gap-2 px-3 py-1.5 rounded-md text-xs border mb-1',
      status === 'running' ? 'shimmer border-border' : 'bg-muted text-muted-foreground'
    )}>
      {status === 'running' ? (
        <Loader2 size={12} className="animate-spin text-primary shrink-0" />
      ) : (
        <span className="h-2 w-2 rounded-full bg-green-500 shrink-0" />
      )}
      {labels[name] ?? `Tool: ${name}`}
    </div>
  )
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const [sourcesOpen, setSourcesOpen] = useState(false)
  const isUser = message.role === 'user'
  const hasVisibleSources = (message.sources?.filter((s) => !s.filtered).length ?? 0) > 0

  return (
    <div className={cn('flex gap-3 mb-4', isUser ? 'flex-row-reverse' : 'flex-row')}>
      {/* Avatar */}
      <div className={cn(
        'h-8 w-8 rounded-full shrink-0 flex items-center justify-center text-xs font-semibold mt-0.5',
        isUser
          ? 'bg-primary/20 text-primary'
          : 'bg-secondary text-muted-foreground'
      )}>
        {isUser ? 'You' : 'AI'}
      </div>

      <div className={cn('flex flex-col max-w-[75%]', isUser && 'items-end')}>
        {/* Tool calls (assistant only) */}
        {!isUser && message.toolCalls && message.toolCalls.length > 0 && (
          <div className="mb-2 w-full">
            {message.toolCalls.map((tc, i) => (
              <ToolCallCard key={i} name={tc.name} status={tc.status} />
            ))}
          </div>
        )}

        {/* Message bubble */}
        <div className={cn(
          'rounded-2xl px-4 py-3 text-sm leading-relaxed',
          isUser
            ? 'bg-primary text-primary-foreground rounded-tr-sm'
            : 'bg-card border rounded-tl-sm'
        )}>
          {isUser ? (
            <p className="whitespace-pre-wrap">{message.content}</p>
          ) : (
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                // Render [N] as citation badges
                text: ({ children }) => {
                  if (typeof children !== 'string') return <>{children}</>
                  const parts = children.split(/(\[\d+\])/g)
                  return (
                    <>
                      {parts.map((part, i) => {
                        const m = part.match(/^\[(\d+)\]$/)
                        if (m) return <CitationBadge key={i} num={parseInt(m[1])} />
                        return <span key={i}>{part}</span>
                      })}
                    </>
                  )
                },
                p: ({ children }) => (
                  <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>
                ),
                h1: ({ children }) => (
                  <h1 className="font-bold text-base mt-4 mb-2 border-b pb-1">{children}</h1>
                ),
                h2: ({ children }) => (
                  <h2 className="font-semibold text-sm mt-4 mb-2 border-b pb-1">{children}</h2>
                ),
                h3: ({ children }) => (
                  <h3 className="font-semibold text-sm mt-3 mb-1">{children}</h3>
                ),
                h4: ({ children }) => (
                  <h4 className="font-medium text-sm mt-2 mb-1 text-muted-foreground">{children}</h4>
                ),
                ul: ({ children }) => (
                  <ul className="list-disc list-outside space-y-1 mb-2 ml-4">{children}</ul>
                ),
                ol: ({ children }) => (
                  <ol className="list-decimal list-outside space-y-1 mb-2 ml-4">{children}</ol>
                ),
                li: ({ children }) => (
                  <li className="leading-relaxed pl-1">{children}</li>
                ),
                blockquote: ({ children }) => (
                  <blockquote className="border-l-2 border-primary/40 pl-3 italic text-muted-foreground my-2">
                    {children}
                  </blockquote>
                ),
                hr: () => <hr className="border-border my-3" />,
                strong: ({ children }) => (
                  <strong className="font-semibold">{children}</strong>
                ),
                em: ({ children }) => (
                  <em className="italic">{children}</em>
                ),
                table: ({ children }) => (
                  <div className="overflow-x-auto my-2">
                    <table className="w-full text-xs border-collapse">{children}</table>
                  </div>
                ),
                thead: ({ children }) => (
                  <thead className="bg-muted">{children}</thead>
                ),
                th: ({ children }) => (
                  <th className="border border-border px-2 py-1.5 font-semibold text-left">{children}</th>
                ),
                td: ({ children }) => (
                  <td className="border border-border px-2 py-1.5">{children}</td>
                ),
                a: ({ href, children }) => (
                  <a href={href} target="_blank" rel="noopener noreferrer" className="text-primary underline underline-offset-2 inline-flex items-center gap-0.5">
                    {children}
                    <ExternalLink size={10} />
                  </a>
                ),
                pre: ({ children }) => (
                  <pre className="bg-muted rounded p-3 overflow-x-auto text-xs my-2">{children}</pre>
                ),
                code: ({ children, className }) => {
                  const isBlock = className?.includes('language-')
                  if (isBlock) {
                    return <code>{children}</code>
                  }
                  return <code className="bg-muted rounded px-1 py-0.5 text-xs font-mono">{children}</code>
                },
              }}
            >
              {message.content}
            </ReactMarkdown>
          )}

          {/* Streaming cursor */}
          {message.streaming && (
            <span className="cursor-blink" aria-hidden />
          )}
        </div>

        {/* Sources toggle */}
        {hasVisibleSources && (
          <div className="mt-2 w-full">
            <Button
              variant="ghost"
              size="sm"
              className="h-7 gap-1 text-xs text-muted-foreground hover:text-foreground px-2"
              onClick={() => setSourcesOpen(!sourcesOpen)}
            >
              {sourcesOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              {message.sources!.filter((s) => !s.filtered).length} sources
              {(message.sources!.filter((s) => s.filtered).length > 0) && (
                <Badge variant="secondary" className="text-[10px] py-0 px-1 ml-1">
                  +{message.sources!.filter((s) => s.filtered).length} filtered
                </Badge>
              )}
            </Button>

            {sourcesOpen && (
              <div className="mt-1 space-y-1.5">
                {message.sources!.filter((s) => !s.filtered).map((src, i) => (
                  <div key={i} className="rounded-lg border bg-card p-3 text-xs space-y-1.5">
                    <div className="flex items-start gap-2">
                      <CitationBadge num={src.ref_id} />
                      <div className="flex-1 min-w-0">
                        <p className="font-medium leading-tight truncate">{src.title || src.url}</p>
                        {src.url && (
                          <a
                            href={src.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-muted-foreground hover:text-primary truncate block"
                          >
                            {src.url}
                          </a>
                        )}
                      </div>
                    </div>
                    {src.snippet && (
                      <p className="text-muted-foreground line-clamp-2">{src.snippet}</p>
                    )}
                    <div className="flex items-center gap-2">
                      <Progress value={src.relevance_score * 100} className="h-1 flex-1" />
                      <span className="text-muted-foreground tabular-nums">
                        {Math.round(src.relevance_score * 100)}%
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
