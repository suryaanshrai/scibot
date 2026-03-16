import { useMemo } from 'react'
import { ChevronLeft, ChevronRight, Database, ExternalLink, LibraryBig, Link2, Loader2, FolderOpen } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { SourceIcon } from '@/components/sources/SourceIcon'
import { cn } from '@/lib/utils'
import type { CollectionDetail, CollectionSourceGroupKey, CollectionSourceValue } from '@/types/collections'
import type { SourceType } from '@/types/sources'

interface CollectionSourcesRailProps {
  collection: CollectionDetail | null
  loading?: boolean
  error?: string | null
  open: boolean
  onToggle: () => void
}

interface SourceGroupMeta {
  label: string
  sourceType: SourceType
}

interface SourceItemView {
  id: string
  label: string
  description?: string
  href?: string
}

const GROUP_ORDER: CollectionSourceGroupKey[] = [
  'papers',
  'youtube',
  'github',
  'github_repos',
  'webpages',
  'videos',
  'audios',
  'images',
  'dynamic_data_sources',
]

const GROUP_META: Record<CollectionSourceGroupKey, SourceGroupMeta> = {
  papers: { label: 'Papers', sourceType: 'arxiv' },
  youtube: { label: 'Videos', sourceType: 'youtube' },
  github: { label: 'GitHub', sourceType: 'github' },
  github_repos: { label: 'GitHub', sourceType: 'github' },
  webpages: { label: 'Web', sourceType: 'website' },
  videos: { label: 'Video Files', sourceType: 'video' },
  audios: { label: 'Audio Files', sourceType: 'audio' },
  images: { label: 'Images', sourceType: 'image' },
  dynamic_data_sources: { label: 'Data Sources', sourceType: 'data' },
}

function toStringValue(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined
}

function isHttpUrl(value?: string): boolean {
  return Boolean(value && /^https?:\/\//i.test(value))
}

function joinParts(parts: Array<string | undefined>): string | undefined {
  const compact = parts.filter(Boolean)
  return compact.length ? compact.join(' • ') : undefined
}

function humanizePathOrUrl(value: string): string {
  const trimmed = value.trim()
  if (!trimmed) return 'Untitled source'

  const arxivMatch = trimmed.match(/(?:arxiv\.org\/(?:abs|pdf)\/|^arxiv:)?([a-z\-]+\/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?/i)
  if (arxivMatch) return `arXiv:${arxivMatch[1]}`

  const pubmedMatch = trimmed.match(/pubmed(?:\.ncbi\.nlm\.nih\.gov)?\/(\d+)/i) || trimmed.match(/^\d{5,10}$/)
  if (pubmedMatch) return `PubMed:${pubmedMatch[1] ?? trimmed}`

  try {
    if (/^https?:\/\//i.test(trimmed)) {
      const url = new URL(trimmed)
      const last = url.pathname.split('/').filter(Boolean).pop()
      return last ? decodeURIComponent(last) : url.hostname
    }
  } catch {
    // Fall through to path parsing.
  }

  const normalized = trimmed.replace(/\\/g, '/')
  const lastSegment = normalized.split('/').filter(Boolean).pop()
  return lastSegment ? decodeURIComponent(lastSegment) : trimmed
}

function inferPaperType(source: CollectionSourceValue): SourceType {
  const explicitType = toStringValue(source.source_type)
  if (explicitType === 'pubmed') return 'pubmed'
  if (explicitType === 'pdf') return 'pdf'
  if (explicitType === 'markdown') return 'markdown'
  if (explicitType === 'latex') return 'latex'
  const url = toStringValue(source.url_or_path)
  if (!url) return 'arxiv'
  if (url.includes('pubmed') || url.includes('ncbi.nlm.nih.gov')) return 'pubmed'
  if (/\.pdf($|\?)/i.test(url)) return 'pdf'
  if (/\.md($|\?)/i.test(url)) return 'markdown'
  if (/\.tex($|\?)/i.test(url)) return 'latex'
  return 'arxiv'
}

function buildItemView(group: CollectionSourceGroupKey, source: CollectionSourceValue, index: number): SourceItemView {
  if (group === 'papers') {
    const title = toStringValue(source.title)
    const url = toStringValue(source.source_url) ?? toStringValue(source.url_or_path)
    const type = inferPaperType(source)
    return {
      id: `${group}-${index}-${url ?? 'paper'}`,
      label: title ?? (url ? humanizePathOrUrl(url) : `Paper ${index + 1}`),
      description: joinParts([
        type === 'arxiv' ? 'Paper' : type === 'pubmed' ? 'PubMed' : type === 'pdf' ? 'PDF' : type === 'markdown' ? 'Markdown' : 'LaTeX',
        Array.isArray(source.authors) ? String(source.authors.slice(0, 3).join(', ')) : undefined,
        typeof source.year === 'number' ? String(source.year) : undefined,
        source.fetch_references ? `refs depth ${source.reference_depth ?? 1}` : undefined,
      ]),
      href: isHttpUrl(url) ? url : undefined,
    }
  }

  if (group === 'youtube') {
    const url = toStringValue(source.url)
    return {
      id: `${group}-${index}-${url ?? 'youtube'}`,
      label: url ?? `YouTube source ${index + 1}`,
      description: toStringValue(source.language),
      href: isHttpUrl(url) ? url : undefined,
    }
  }

  if (group === 'github' || group === 'github_repos') {
    const url = toStringValue(source.url)
    return {
      id: `${group}-${index}-${url ?? 'github'}`,
      label: url ?? `Repository ${index + 1}`,
      description: toStringValue(source.branch),
      href: isHttpUrl(url) ? url : undefined,
    }
  }

  if (group === 'webpages') {
    const url = toStringValue(source.url)
    return {
      id: `${group}-${index}-${url ?? 'web'}`,
      label: url ?? `Web source ${index + 1}`,
      description: joinParts([
        source.crawl ? 'Site crawl' : 'Single page',
        typeof source.max_depth === 'number' ? `depth ${String(source.max_depth)}` : undefined,
      ]),
      href: isHttpUrl(url) ? url : undefined,
    }
  }

  if (group === 'dynamic_data_sources') {
    const sourceType = toStringValue(source.source_type)
    const filePath = toStringValue(source.file_path)
    const database = toStringValue(source.database)
    const table = toStringValue(source.table)
    const collection = toStringValue(source.mongo_collection)
    const credentialKey = toStringValue(source.credential_key)
    return {
      id: `${group}-${index}-${sourceType ?? 'data'}-${credentialKey ?? filePath ?? index}`,
      label: filePath ?? `${sourceType === 'mongodb' ? 'MongoDB' : sourceType === 'postgres' ? 'PostgreSQL' : sourceType ?? 'Data source'}`,
      description: joinParts([
        sourceType?.toUpperCase(),
        database,
        table,
        collection,
        credentialKey,
      ]),
    }
  }

  const filePath = toStringValue(source.file_path)
  return {
    id: `${group}-${index}-${filePath ?? 'file'}`,
    label: filePath ?? `${GROUP_META[group].label} ${index + 1}`,
  }
}

export function CollectionSourcesRail({ collection, loading = false, error, open, onToggle }: CollectionSourcesRailProps) {
  const sourceGroups = useMemo(() => {
    if (!collection) return []
    return GROUP_ORDER
      .map((group) => {
        const entries = collection.sources[group] ?? []
        if (!entries.length) return null
        return {
          key: group,
          meta: GROUP_META[group],
          items: entries.map((entry, index) => buildItemView(group, entry, index)),
        }
      })
      .filter((group): group is NonNullable<typeof group> => Boolean(group))
  }, [collection])

  const totalCount = useMemo(
    () => sourceGroups.reduce((sum, group) => sum + group.items.length, 0),
    [sourceGroups]
  )

  return (
    <aside
      className={cn(
        'border-t bg-muted/20 transition-all duration-200 lg:border-l lg:border-t-0',
        open ? 'w-full lg:w-[22rem]' : 'w-full lg:w-14'
      )}
    >
      <div className={cn('flex h-full min-h-[4rem] flex-col', !open && 'lg:items-center')}>
        <div className="flex items-center gap-2 border-b px-3 py-3">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 shrink-0"
            onClick={onToggle}
            aria-label={open ? 'Collapse attached sources' : 'Expand attached sources'}
            title={open ? 'Collapse attached sources' : 'Expand attached sources'}
          >
            {open ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
          </Button>

          {open ? (
            <>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">Attached Sources</p>
                <p className="truncate text-xs text-muted-foreground">
                  {collection?.collectionName ?? 'No collection attached'}
                </p>
              </div>
              <Badge variant="secondary" className="shrink-0 text-[11px]">
                {totalCount}
              </Badge>
            </>
          ) : (
            <div className="hidden lg:flex lg:flex-1 lg:justify-center">
              <LibraryBig size={16} className="text-muted-foreground" />
            </div>
          )}
        </div>

        {open ? (
          <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
            {loading ? (
              <div className="flex items-center gap-2 rounded-lg border border-dashed bg-background/80 px-3 py-4 text-sm text-muted-foreground">
                <Loader2 size={15} className="animate-spin" />
                <span>Loading collection sources...</span>
              </div>
            ) : error ? (
              <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-3 text-sm text-destructive">
                {error}
              </div>
            ) : !collection ? (
              <div className="rounded-lg border border-dashed bg-background/80 px-3 py-4 text-sm text-muted-foreground">
                This chat does not have a collection attached yet.
              </div>
            ) : sourceGroups.length === 0 ? (
              <div className="rounded-lg border border-dashed bg-background/80 px-3 py-4 text-sm text-muted-foreground">
                The attached collection exists, but it has no stored sources.
              </div>
            ) : (
              <div className="space-y-4">
                {sourceGroups.map((group) => (
                  <section key={group.key} className="space-y-2">
                    <div className="flex items-center gap-2">
                      <SourceIcon type={group.meta.sourceType} size={15} />
                      <h3 className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                        {group.meta.label}
                      </h3>
                      <Badge variant="outline" className="ml-auto text-[10px]">
                        {group.items.length}
                      </Badge>
                    </div>
                    <div className="space-y-2">
                      {group.items.map((item) => (
                        <div key={item.id} className="rounded-lg border bg-background/90 px-3 py-2">
                          <div className="flex items-start gap-2">
                            <div className="mt-0.5 shrink-0 text-muted-foreground">
                              {item.href ? <Link2 size={14} /> : group.key === 'dynamic_data_sources' ? <Database size={14} /> : <FolderOpen size={14} />}
                            </div>
                            <div className="min-w-0 flex-1">
                              {item.href ? (
                                <a
                                  href={item.href}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="flex items-start gap-1 text-sm font-medium leading-5 hover:text-primary"
                                >
                                  <span className="truncate">{item.label}</span>
                                  <ExternalLink size={12} className="mt-1 shrink-0" />
                                </a>
                              ) : (
                                <p className="truncate text-sm font-medium leading-5">{item.label}</p>
                              )}
                              {item.description && (
                                <p className="mt-1 text-xs leading-4 text-muted-foreground">{item.description}</p>
                              )}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </section>
                ))}
              </div>
            )}
          </div>
        ) : (
          <div className="hidden flex-1 items-center justify-center lg:flex">
            <button
              type="button"
              onClick={onToggle}
              className="rounded-full border bg-background/80 p-2 text-muted-foreground hover:text-foreground"
              aria-label="Expand attached sources"
              title="Expand attached sources"
            >
              <LibraryBig size={16} />
            </button>
          </div>
        )}
      </div>
    </aside>
  )
}