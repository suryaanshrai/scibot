import type { CollectionDetail, CollectionSourceGroupKey, CollectionSourceValue } from '@/types/collections'
import type { SourceType } from '@/types/sources'

interface SourceGroupMeta {
  label: string
  sourceType: SourceType
}

export interface SourceItemView {
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
  return compact.length ? compact.join(' · ') : undefined
}

function humanizePathOrUrl(value: string): string {
  const trimmed = value.trim()
  if (!trimmed) return 'Untitled source'

  const arxivMatch = trimmed.match(/(?:arxiv\.org\/(?:abs|pdf)\/|^arxiv:)?([a-z-]+\/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?/i)
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

export interface SourceGroupView {
  key: CollectionSourceGroupKey
  label: string
  sourceType: SourceType
  items: SourceItemView[]
}

/** Group a collection's stored sources for display, in a stable order. */
export function collectionGroups(collection: CollectionDetail | null): SourceGroupView[] {
  if (!collection) return []
  const groups: SourceGroupView[] = []
  for (const key of GROUP_ORDER) {
    const entries = collection.sources[key] ?? []
    if (!entries.length) continue
    const items = entries.map((entry, index) => buildItemView(key, entry, index))
    const existing = groups.find((g) => g.label === GROUP_META[key].label)
    if (existing) existing.items.push(...items)
    else groups.push({ key, label: GROUP_META[key].label, sourceType: GROUP_META[key].sourceType, items })
  }
  return groups
}
