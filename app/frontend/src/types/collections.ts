export type CollectionSourceGroupKey =
  | 'papers'
  | 'youtube'
  | 'github'
  | 'github_repos'
  | 'webpages'
  | 'videos'
  | 'audios'
  | 'images'
  | 'dynamic_data_sources'

export type CollectionSourceValue = Record<string, unknown>

export type CollectionSources = Partial<Record<CollectionSourceGroupKey, CollectionSourceValue[]>>

export interface CollectionDetail {
  collectionName: string
  username: string
  createdAt: string
  updatedAt: string
  sources: CollectionSources
  vectorCollection?: string | null
  ingestionTaskId?: string | null
  ingestionTaskStatus?: string | null
}