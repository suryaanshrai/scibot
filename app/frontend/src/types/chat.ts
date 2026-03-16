import type { UserConfig } from './config'

export interface ChatMeta {
  chatId: string
  title: string
  createdAt: string
  updatedAt: string
  collectionName?: string | null
  messageCount?: number
  config?: Partial<UserConfig>   // per-chat settings override
}

export interface SourceRecord {
  ref_id: number
  title: string
  url: string
  source_type: 'paper' | 'webpage' | 'vector_store' | 'data' | 'unknown'
  tool_name: string
  snippet: string
  relevance_score: number
  filtered: boolean
}

export interface ToolCall {
  name: string
  status: 'running' | 'done'
}

export interface Message {
  id: string
  chatId: string
  role: 'user' | 'assistant'
  content: string
  sources?: SourceRecord[]
  toolCalls?: ToolCall[]
  streaming?: boolean
  interrupted?: boolean
  status?: string
  createdAt: string
}

export interface HITLPayload {
  question?: string
  tool?: string
  args?: unknown
  description?: string
  details?: string
}

export type SSEEvent =
  | { type: 'token'; content: string }
  | { type: 'tool_start'; tool: string }
  | { type: 'sources'; records?: SourceRecord[]; count?: number; filtered?: number }
  | { type: 'interrupt'; payload: HITLPayload }
  | { type: 'done'; result: { answer: string; thread_id: string; source_records: SourceRecord[] } }
  | { type: 'error'; detail?: string; error?: string; error_type?: string }
