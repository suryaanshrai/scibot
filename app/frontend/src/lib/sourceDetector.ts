import type { SourceType, PreviewMeta } from '@/types/sources'

interface DetectionResult {
  type: SourceType
  preview: PreviewMeta
}

function youtubeVideoId(url: string): string | null {
  try {
    const u = new URL(url)
    if (u.hostname === 'youtu.be') return u.pathname.slice(1)
    return u.searchParams.get('v')
  } catch {
    return null
  }
}

function arxivId(url: string): string | null {
  const m = url.match(/arxiv\.org\/(?:abs|pdf)\/([0-9]{4}\.[0-9]+(?:v\d+)?)/)
  return m ? m[1] : null
}

function pubmedId(url: string): string | null {
  const m = url.match(/pubmed\.ncbi\.nlm\.nih\.gov\/(\d+)/)
  return m ? m[1] : null
}

function githubRepo(url: string): string | null {
  const m = url.match(/github\.com\/([^/]+\/[^/]+?)(?:\/|$)/)
  return m ? m[1] : null
}

function ext(url: string): string {
  try {
    const pathname = new URL(url).pathname
    const dot = pathname.lastIndexOf('.')
    return dot >= 0 ? pathname.slice(dot + 1).toLowerCase() : ''
  } catch {
    return ''
  }
}

/** Detect source type and preview metadata from a URL */
export function detectUrl(url: string): DetectionResult {
  const trimmed = url.trim()

  const ytId = youtubeVideoId(trimmed)
  if (ytId) {
    return {
      type: 'youtube',
      preview: {
        label: `YouTube video`,
        thumbnailUrl: `https://img.youtube.com/vi/${ytId}/mqdefault.jpg`,
      },
    }
  }

  const axId = arxivId(trimmed)
  if (axId) {
    return { type: 'arxiv', preview: { label: `arXiv:${axId}` } }
  }

  const pmId = pubmedId(trimmed)
  if (pmId) {
    return { type: 'pubmed', preview: { label: `PubMed:${pmId}` } }
  }

  const ghRepo = githubRepo(trimmed)
  if (ghRepo) {
    return { type: 'github', preview: { label: ghRepo } }
  }

  const extension = ext(trimmed)
  if (extension === 'pdf') return { type: 'pdf', preview: { label: 'PDF document' } }
  if (extension === 'md') return { type: 'markdown', preview: { label: 'Markdown file' } }
  if (extension === 'tex') return { type: 'latex', preview: { label: 'LaTeX file' } }
  if (['mp3', 'wav', 'm4a', 'ogg', 'flac'].includes(extension))
    return { type: 'audio', preview: { label: 'Audio file' } }
  if (['mp4', 'mov', 'avi', 'mkv', 'webm'].includes(extension))
    return { type: 'video', preview: { label: 'Video file' } }
  if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'].includes(extension))
    return { type: 'image', preview: { label: 'Image file' } }
  try {
    const hostname = new URL(trimmed).hostname
    return { type: 'webpage', preview: { label: hostname } }
  } catch {
    return { type: 'webpage', preview: { label: trimmed } }
  }
}

/** Detect source type from a File object */
export function detectFile(file: File): DetectionResult {
  const name = file.name.toLowerCase()
  const ext = name.slice(name.lastIndexOf('.') + 1)

  if (ext === 'pdf') return { type: 'pdf', preview: { label: file.name } }
  if (ext === 'csv') return { type: 'csv', preview: { label: file.name } }
  if (ext === 'json') return { type: 'json', preview: { label: file.name } }
  if (ext === 'md') return { type: 'markdown', preview: { label: file.name } }
  if (ext === 'tex') return { type: 'latex', preview: { label: file.name } }
  if (['mp3', 'wav', 'm4a', 'ogg', 'flac'].includes(ext))
    return { type: 'audio', preview: { label: file.name } }
  if (['mp4', 'mov', 'avi', 'mkv', 'webm'].includes(ext))
    return { type: 'video', preview: { label: file.name } }
  if (['jpg', 'jpeg', 'png', 'gif', 'webp'].includes(ext))
    return { type: 'image', preview: { label: file.name } }
  if (['xlsx', 'xls', 'parquet'].includes(ext))
    return { type: 'data', preview: { label: file.name } }

  return { type: 'webpage', preview: { label: file.name } }
}
