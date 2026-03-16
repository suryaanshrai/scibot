import {
  FileText, Youtube, FlaskConical, Github, FileType2,
  Music, Film, Image, Table2, Globe, Code2, BookOpen, Database, Braces,
} from 'lucide-react'
import type { SourceType } from '@/types/sources'
import { cn } from '@/lib/utils'

const iconMap: Record<SourceType, React.ElementType> = {
  arxiv: BookOpen,
  youtube: Youtube,
  pubmed: FlaskConical,
  github: Github,
  pdf: FileType2,
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

const colorMap: Record<SourceType, string> = {
  arxiv: 'text-red-500',
  youtube: 'text-red-600',
  pubmed: 'text-blue-600',
  github: 'text-gray-700 dark:text-gray-300',
  pdf: 'text-orange-500',
  csv: 'text-emerald-600',
  json: 'text-amber-600',
  postgres: 'text-sky-600',
  mongodb: 'text-green-700',
  markdown: 'text-blue-500',
  latex: 'text-green-600',
  audio: 'text-purple-500',
  video: 'text-pink-500',
  image: 'text-cyan-500',
  data: 'text-yellow-600',
  webpage: 'text-gray-500',
  website: 'text-gray-500',
}

interface SourceIconProps {
  type: SourceType
  className?: string
  size?: number
}

export function SourceIcon({ type, className, size = 16 }: SourceIconProps) {
  const Icon = iconMap[type] ?? Globe
  return <Icon className={cn(colorMap[type], className)} size={size} />
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
