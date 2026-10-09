import type { LucideIcon } from 'lucide-react'
import {
  BookOpen, Braces, Code2, Database, FileText, Film, FlaskConical, Github, Globe, Image, Music, Table2, Youtube,
} from 'lucide-react'
import type { SourceType } from '@/types/sources'

export const SOURCE_ICONS: Record<SourceType, LucideIcon> = {
  arxiv: BookOpen,
  youtube: Youtube,
  pubmed: FlaskConical,
  github: Github,
  pdf: FileText,
  csv: Table2,
  json: Braces,
  postgres: Database,
  mongodb: Database,
  markdown: FileText,
  latex: Code2,
  audio: Music,
  video: Film,
  image: Image,
  data: Table2,
  webpage: Globe,
  website: Globe,
}

export const SOURCE_LABELS: Record<SourceType, string> = {
  arxiv: 'arXiv Paper',
  youtube: 'YouTube Video',
  pubmed: 'PubMed Article',
  github: 'GitHub Repo',
  pdf: 'PDF Document',
  csv: 'CSV File',
  json: 'JSON File',
  postgres: 'PostgreSQL Table',
  mongodb: 'MongoDB Collection',
  markdown: 'Markdown',
  latex: 'LaTeX File',
  audio: 'Audio',
  video: 'Video',
  image: 'Image',
  data: 'Data File',
  webpage: 'Web Page',
  website: 'Website',
}

/** File extensions the upload endpoint ingests today. */
export const UPLOADABLE_TYPES: SourceType[] = ['pdf', 'markdown', 'latex', 'csv', 'json']
export const UPLOAD_ACCEPT = '.pdf,.md,.tex,.csv,.json'

export function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
