export type SourceType =
  | 'arxiv'
  | 'youtube'
  | 'pubmed'
  | 'github'
  | 'pdf'
  | 'csv'
  | 'json'
  | 'postgres'
  | 'mongodb'
  | 'markdown'
  | 'latex'
  | 'audio'
  | 'video'
  | 'image'
  | 'data'
  | 'webpage'
  | 'website'

export interface RefParams {
  fetch_references: boolean
  depth: number           // 1-3
  max_refs: number        // 5-100
}

export interface PreviewMeta {
  label: string           // e.g. 'arXiv:1706.03762' or youtube video title placeholder
  thumbnailUrl?: string   // only for youtube
}

export interface SourceEntry {
  id: string
  inputType: 'url' | 'file' | 'database'
  url?: string
  file?: File
  fileName?: string
  detectedType: SourceType
  connectionString?: string
  database?: string
  table?: string
  mongoCollection?: string
  refParams?: RefParams
  previewMeta?: PreviewMeta
}

/** Source types that support reference fetching */
export const REF_PARAM_TYPES: SourceType[] = ['arxiv', 'pubmed', 'pdf', 'markdown', 'latex']

export const DEFAULT_REF_PARAMS: RefParams = {
  fetch_references: false,
  depth: 1,
  max_refs: 20,
}
