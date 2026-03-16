import { generateId } from '@/lib/utils'
import type { ChatMeta, HITLPayload, Message, SourceRecord, SSEEvent } from '@/types/chat'
import type { CollectionDetail } from '@/types/collections'
import type { ConfigOptions, UserConfig } from '@/types/config'
import type { SourceEntry } from '@/types/sources'
import { EMPTY_CONFIG_OPTIONS, normalizeUserConfig } from '@/types/config'

const API_BASE = normalizeApiBase(import.meta.env.BACKEND_URL)
const INGEST_POLL_MS = 1200
const INGEST_TIMEOUT_MS = 180000

function normalizeApiBase(raw?: string) {
  const fallback = '/api'
  const base = (raw || fallback).trim().replace(/\/$/, '')
  if (base.endsWith('/api')) return base
  return `${base}/api`
}

export interface AuthSession {
  username: string
  authHeader: string
}

interface LoginResult {
  username: string
  authHeader: string
  globalConfig: UserConfig
  configOptions: ConfigOptions
}

interface ChatHistoryResult {
  chat: ChatMeta
  messages: Message[]
  chatConfig: Partial<UserConfig>
}

interface ChatWithSourcesInput {
  title?: string
  configOverride?: Partial<UserConfig>
  sources?: SourceEntry[]
}

interface SourceBuckets {
  papers: Array<Record<string, unknown>>
  youtube: Array<Record<string, unknown>>
  github: Array<Record<string, unknown>>
  webpages: Array<Record<string, unknown>>
  dynamic_data_sources: Array<Record<string, unknown>>
}

interface SourceBuildResult {
  buckets: SourceBuckets
  files: File[]
  unsupported: string[]
  configOverride?: Partial<UserConfig>
}

interface IngestTaskResponse {
  task_id: string
}

interface CollectionDetailResponse {
  collection_name: string
  username: string
  created_at: string
  updated_at: string
  sources: CollectionDetail['sources']
  vector_collection?: string | null
  ingestion_task_id?: string | null
  ingestion_task_status?: string | null
}

function basicAuthHeader(username: string, password: string) {
  return `Basic ${btoa(`${username}:${password}`)}`
}

async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
  auth?: AuthSession | string
): Promise<T> {
  const headers = new Headers(init.headers)
  const authHeader = typeof auth === 'string' ? auth : auth?.authHeader
  if (authHeader) headers.set('Authorization', authHeader)
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const res = await fetch(`${API_BASE}${path}`, { ...init, headers })
  if (!res.ok) throw await toApiError(res)
  if (res.status === 204) return undefined as T
  const text = await res.text()
  return (text ? JSON.parse(text) : undefined) as T
}

async function toApiError(res: Response): Promise<Error> {
  let message = `${res.status} ${res.statusText}`
  try {
    const data = await res.json()
    message = data.detail ?? data.message ?? message
  } catch {
    // ignore non-json error bodies
  }
  return new Error(message)
}

function mapChatMeta(chat: {
  chat_id: string
  title?: string | null
  created_at: string
  updated_at: string
  collection_name?: string | null
  message_count?: number
}): ChatMeta {
  return {
    chatId: chat.chat_id,
    title: chat.title?.trim() || 'Untitled chat',
    createdAt: chat.created_at,
    updatedAt: chat.updated_at,
    collectionName: chat.collection_name ?? null,
    messageCount: chat.message_count,
  }
}

function mapMessage(chatId: string, message: {
  message_id: string
  role: string
  content: string
  timestamp: string
  source_records?: SourceRecord[] | null
  interrupted?: boolean
  status?: string
}): Message {
  return {
    id: message.message_id,
    chatId,
    role: message.role === 'user' ? 'user' : 'assistant',
    content: message.content,
    createdAt: message.timestamp,
    sources: message.source_records ?? undefined,
    interrupted: message.interrupted,
    status: message.status,
  }
}

function mapCollectionDetail(detail: CollectionDetailResponse): CollectionDetail {
  return {
    collectionName: detail.collection_name,
    username: detail.username,
    createdAt: detail.created_at,
    updatedAt: detail.updated_at,
    sources: detail.sources ?? {},
    vectorCollection: detail.vector_collection ?? null,
    ingestionTaskId: detail.ingestion_task_id ?? null,
    ingestionTaskStatus: detail.ingestion_task_status ?? null,
  }
}

function providerConfigOverride(config?: Partial<UserConfig>) {
  if (!config) return undefined
  return JSON.parse(JSON.stringify(config))
}

function mergeConfigOverrides(
  base?: Partial<UserConfig>,
  updates?: Partial<UserConfig>
): Partial<UserConfig> | undefined {
  if (!base && !updates) return undefined
  if (!base) return updates ? JSON.parse(JSON.stringify(updates)) : undefined
  if (!updates) return JSON.parse(JSON.stringify(base))

  const merged: Partial<UserConfig> = {
    ...base,
    ...updates,
  }

  if (base.llm || updates.llm) merged.llm = { ...(base.llm ?? {}), ...(updates.llm ?? {}) } as UserConfig['llm']
  if (base.embedding || updates.embedding) {
    merged.embedding = { ...(base.embedding ?? {}), ...(updates.embedding ?? {}) } as UserConfig['embedding']
  }
  if (base.store || updates.store) merged.store = { ...(base.store ?? {}), ...(updates.store ?? {}) } as UserConfig['store']
  if (base.external_keys || updates.external_keys) {
    merged.external_keys = { ...(base.external_keys ?? {}), ...(updates.external_keys ?? {}) }
  }
  if (base.data_source_creds || updates.data_source_creds) {
    merged.data_source_creds = { ...(base.data_source_creds ?? {}), ...(updates.data_source_creds ?? {}) }
  }
  if (base.search || updates.search) {
    merged.search = { ...(base.search ?? {}), ...(updates.search ?? {}) } as UserConfig['search']
  }

  return merged
}

function buildSourceBuckets(sources: SourceEntry[]): SourceBuildResult {
  const buckets: SourceBuckets = { papers: [], youtube: [], github: [], webpages: [], dynamic_data_sources: [] }
  const files: File[] = []
  const unsupported: string[] = []
  const dataSourceCreds: NonNullable<Partial<UserConfig>['data_source_creds']> = {}

  for (const source of sources) {
    if (source.inputType === 'database') {
      const connectionString = source.connectionString?.trim()
      const sourceType = source.detectedType === 'mongodb' ? 'mongodb' : source.detectedType === 'postgres' ? 'postgres' : null
      if (!connectionString || !sourceType) {
        unsupported.push(source.previewMeta?.label || 'database source')
        continue
      }

      const credentialKey = `chat-${source.id}`
      dataSourceCreds[credentialKey] = {
        type: sourceType,
        connection_string: connectionString,
        ...(source.database?.trim() ? { database: source.database.trim() } : {}),
        ...(sourceType === 'postgres' && source.table?.trim() ? { table: source.table.trim() } : {}),
        ...(sourceType === 'mongodb' && source.mongoCollection?.trim()
          ? { collection: source.mongoCollection.trim() }
          : {}),
      }

      buckets.dynamic_data_sources.push({
        source_type: sourceType,
        credential_key: credentialKey,
        ...(source.database?.trim() ? { database: source.database.trim() } : {}),
        ...(sourceType === 'postgres' && source.table?.trim() ? { table: source.table.trim() } : {}),
        ...(sourceType === 'mongodb' && source.mongoCollection?.trim()
          ? { mongo_collection: source.mongoCollection.trim() }
          : {}),
      })
      continue
    }

    if (source.inputType === 'file') {
      if (!source.file) continue
      if (['pdf', 'markdown', 'latex', 'csv', 'json'].includes(source.detectedType)) {
        files.push(source.file)
      } else {
        unsupported.push(source.file.name)
      }
      continue
    }

    const url = source.url?.trim()
    if (!url) continue

    if (['arxiv', 'pubmed', 'pdf', 'markdown', 'latex'].includes(source.detectedType)) {
      buckets.papers.push({
        url_or_path: url,
        source_type: source.detectedType,
        fetch_references: source.refParams?.fetch_references,
        reference_depth: source.refParams?.depth,
        reference_top_n: source.refParams?.max_refs,
      })
      continue
    }

    if (source.detectedType === 'youtube') {
      buckets.youtube.push({ url })
      continue
    }

    if (source.detectedType === 'github') {
      buckets.github.push({ url })
      continue
    }

    if (['webpage', 'website'].includes(source.detectedType)) {
      buckets.webpages.push({
        url,
        crawl: source.detectedType === 'website',
        max_depth: source.detectedType === 'website' ? 2 : 1,
      })
      continue
    }

    unsupported.push(url)
  }

  return {
    buckets,
    files,
    unsupported,
    configOverride: Object.keys(dataSourceCreds).length ? { data_source_creds: dataSourceCreds } : undefined,
  }
}

function compactBuckets(buckets: SourceBuckets) {
  return {
    ...(buckets.papers.length ? { papers: buckets.papers } : {}),
    ...(buckets.youtube.length ? { youtube: buckets.youtube } : {}),
    ...(buckets.github.length ? { github: buckets.github } : {}),
    ...(buckets.webpages.length ? { webpages: buckets.webpages } : {}),
    ...(buckets.dynamic_data_sources.length ? { dynamic_data_sources: buckets.dynamic_data_sources } : {}),
  }
}

async function waitForIngest(auth: AuthSession, collectionName: string, taskId?: string) {
  const startedAt = Date.now()
  const params = taskId ? `?task_id=${encodeURIComponent(taskId)}` : ''
  while (Date.now() - startedAt < INGEST_TIMEOUT_MS) {
    const status = await apiRequest<{ status: string; error?: string | null }>(
      `/collections/${encodeURIComponent(collectionName)}/ingest-status${params}`,
      {},
      auth
    )
    if (['success', 'completed'].includes(status.status)) return
    if (status.status === 'failure') throw new Error(status.error || 'Collection ingestion failed')
    await new Promise((resolve) => setTimeout(resolve, INGEST_POLL_MS))
  }
  throw new Error('Collection ingestion timed out')
}

async function createOrUpdateCollectionFromSources(
  auth: AuthSession,
  collectionName: string | null,
  sources: SourceEntry[]
): Promise<{ collectionName: string; configOverride?: Partial<UserConfig> }> {
  if (!sources.length && collectionName) return { collectionName }

  const { buckets, files, unsupported, configOverride } = buildSourceBuckets(sources)
  if (unsupported.length > 0) {
    throw new Error(`Unsupported source types for current backend: ${unsupported.join(', ')}`)
  }

  const compact = compactBuckets(buckets)
  const name = collectionName || `scibot-${generateId()}`

  if (collectionName) {
    if (Object.keys(compact).length) {
      const response = await apiRequest<IngestTaskResponse>(`/collections/${encodeURIComponent(name)}`, {
        method: 'PATCH',
        body: JSON.stringify({ sources: compact, ...(configOverride ? { config: configOverride } : {}) }),
      }, auth)
      await waitForIngest(auth, name, response.task_id)
    }
  } else {
    const response = await apiRequest<IngestTaskResponse>('/collections', {
      method: 'POST',
      body: JSON.stringify({ collection_name: name, sources: compact, ...(configOverride ? { config: configOverride } : {}) }),
    }, auth)
    await waitForIngest(auth, name, response.task_id)
  }

  if (files.length) {
    const form = new FormData()
    for (const file of files) form.append('files', file)
    const response = await apiRequest<IngestTaskResponse>(`/collections/${encodeURIComponent(name)}/files`, { method: 'POST', body: form }, auth)
    await waitForIngest(auth, name, response.task_id)
  }

  return { collectionName: name, configOverride }
}

function mergeOptionsWithConfig(options: ConfigOptions, config: UserConfig): UserConfig {
  const llmProvider = options.llms.find((entry) => entry.provider === config.llm.provider) ?? options.llms[0]
  const embeddingProvider =
    options.embeddings.find((entry) => entry.provider === config.embedding.provider) ?? options.embeddings[0]
  const storeProvider = options.stores.find((entry) => entry.provider === config.store.provider) ?? options.stores[0]

  return normalizeUserConfig({
    ...config,
    llm: {
      ...config.llm,
      provider: config.llm.provider || llmProvider?.provider || '',
      model: config.llm.model || llmProvider?.default_model || '',
    },
    embedding: {
      ...config.embedding,
      provider: config.embedding.provider || embeddingProvider?.provider || '',
      model: config.embedding.model || embeddingProvider?.default_model || '',
    },
    store: {
      ...config.store,
      provider: config.store.provider || storeProvider?.provider || '',
    },
  })
}

export async function register(username: string, password: string): Promise<void> {
  await apiRequest('/auth/register', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
}

export async function login(username: string, password: string): Promise<LoginResult> {
  const authHeader = basicAuthHeader(username, password)
  const auth = { username, authHeader }
  const loginResponse = await apiRequest<{ username: string }>('/auth/login', { method: 'POST' }, authHeader)
  const [configResponse, optionsResponse] = await Promise.all([
    apiRequest<Partial<UserConfig>>('/config', {}, auth),
    apiRequest<ConfigOptions>('/config/options', {}, auth).catch(() => EMPTY_CONFIG_OPTIONS),
  ])
  const globalConfig = mergeOptionsWithConfig(optionsResponse, normalizeUserConfig(configResponse))

  return {
    username: loginResponse.username,
    authHeader,
    globalConfig,
    configOptions: optionsResponse,
  }
}

export async function getChats(auth: AuthSession): Promise<ChatMeta[]> {
  const data = await apiRequest<Array<{
    chat_id: string
    title?: string | null
    created_at: string
    updated_at: string
    collection_name?: string | null
    message_count?: number
  }>>('/chats', {}, auth)
  return data.map(mapChatMeta)
}

export async function getCollectionDetail(auth: AuthSession, collectionName: string): Promise<CollectionDetail> {
  const data = await apiRequest<CollectionDetailResponse>(`/collections/${encodeURIComponent(collectionName)}`, {}, auth)
  return mapCollectionDetail(data)
}

export async function createChat(auth: AuthSession, input: ChatWithSourcesInput = {}): Promise<ChatMeta> {
  let collectionName: string | null | undefined = undefined
  let configOverride = input.configOverride
  if (input.sources?.length) {
    const built = await createOrUpdateCollectionFromSources(auth, null, input.sources)
    collectionName = built.collectionName
    configOverride = mergeConfigOverrides(input.configOverride, built.configOverride)
  }

  const chat = await apiRequest<{
    chat_id: string
    title?: string | null
    created_at: string
    updated_at: string
    collection_name?: string | null
  }>('/chats', {
    method: 'POST',
    body: JSON.stringify({
      title: input.title,
      collection_name: collectionName,
      config_override: providerConfigOverride(configOverride),
    }),
  }, auth)

  return mapChatMeta(chat)
}

export async function addSourcesToChat(
  auth: AuthSession,
  chat: ChatMeta,
  sources: SourceEntry[],
  existingConfigOverride?: Partial<UserConfig>
): Promise<{ chat: ChatMeta; configOverride?: Partial<UserConfig> }> {
  if (!sources.length) return { chat, configOverride: existingConfigOverride }

  const built = await createOrUpdateCollectionFromSources(auth, chat.collectionName ?? null, sources)
  const nextConfigOverride = mergeConfigOverrides(existingConfigOverride, built.configOverride)
  const collectionName = built.collectionName
  if (chat.collectionName === collectionName && !nextConfigOverride) {
    return { chat: { ...chat, collectionName }, configOverride: undefined }
  }

  const updated = await apiRequest<{
    chat_id: string
    title?: string | null
    created_at: string
    updated_at: string
    collection_name?: string | null
  }>(`/chats/${encodeURIComponent(chat.chatId)}`, {
    method: 'PATCH',
    body: JSON.stringify({
      ...(chat.collectionName !== collectionName ? { collection_name: collectionName } : {}),
      ...(nextConfigOverride ? { config_override: providerConfigOverride(nextConfigOverride) } : {}),
    }),
  }, auth)

  return { chat: mapChatMeta(updated), configOverride: nextConfigOverride }
}

export async function getChatHistory(auth: AuthSession, chatId: string): Promise<ChatHistoryResult> {
  const [chat, messages] = await Promise.all([
    apiRequest<{
      chat_id: string
      title?: string | null
      created_at: string
      updated_at: string
      collection_name?: string | null
      config_override?: Partial<UserConfig> | null
    }>(`/chats/${encodeURIComponent(chatId)}`, {}, auth),
    apiRequest<Array<{
      message_id: string
      role: string
      content: string
      timestamp: string
      source_records?: SourceRecord[] | null
      interrupted?: boolean
      status?: string
    }>>(`/chats/${encodeURIComponent(chatId)}/messages`, {}, auth),
  ])

  return {
    chat: mapChatMeta(chat),
    messages: messages.map((message) => mapMessage(chatId, message)),
    chatConfig: chat.config_override ?? {},
  }
}

export async function saveGlobalConfig(auth: AuthSession, config: UserConfig): Promise<UserConfig> {
  const { data_source_creds: _ignored, ...globalOnlyConfig } = config
  const updated = await apiRequest<Partial<UserConfig>>('/config', {
    method: 'PUT',
    body: JSON.stringify(globalOnlyConfig),
  }, auth)
  return normalizeUserConfig(updated)
}

export async function saveChatConfig(auth: AuthSession, chatId: string, config: Partial<UserConfig>) {
  return await apiRequest<{
    chat_id: string
    title?: string | null
    created_at: string
    updated_at: string
    collection_name?: string | null
    config_override?: Partial<UserConfig> | null
  }>(`/chats/${encodeURIComponent(chatId)}`, {
    method: 'PATCH',
    body: JSON.stringify({ config_override: providerConfigOverride(config) }),
  }, auth)
}

export async function updateChatTitle(auth: AuthSession, chatId: string, title: string) {
  return await apiRequest<{
    chat_id: string
    title?: string | null
    created_at: string
    updated_at: string
    collection_name?: string | null
  }>(`/chats/${encodeURIComponent(chatId)}`, {
    method: 'PATCH',
    body: JSON.stringify({ title }),
  }, auth)
}

export async function deleteChat(auth: AuthSession, chatId: string): Promise<void> {
  await apiRequest(`/chats/${encodeURIComponent(chatId)}`, { method: 'DELETE' }, auth)
}

function parseSseChunk(buffer: string): { rest: string; events: string[] } {
  const parts = buffer.split('\n\n')
  const rest = parts.pop() ?? ''
  return { rest, events: parts }
}

function parseSseEvent(rawEvent: string): SSEEvent | '[DONE]' | null {
  const dataLines = rawEvent
    .split('\n')
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trim())
  if (!dataLines.length) return null
  const payload = dataLines.join('\n')
  if (payload === '[DONE]') return '[DONE]'
  try {
    return JSON.parse(payload) as SSEEvent
  } catch {
    return null
  }
}

export function sendMessage(
  auth: AuthSession,
  chatId: string,
  query: string,
  configOverride: Partial<UserConfig> | undefined,
  handlers: {
    onToken: (token: string) => void
    onToolStart: (tool: string) => void
    onSources: (sources: SourceRecord[]) => void
    onInterrupt: (payload: HITLPayload, content: string, sources?: SourceRecord[]) => void
    onDone: (content: string, sources?: SourceRecord[]) => void
    onError: (err: Error) => void
  }
): () => void {
  return streamChatEndpoint(
    `${API_BASE}/chats/${encodeURIComponent(chatId)}/messages`,
    auth,
    { content: query, config_override: providerConfigOverride(configOverride) },
    handlers
  )
}

export function resumeChat(
  auth: AuthSession,
  chatId: string,
  response: unknown,
  handlers: {
    onToken: (token: string) => void
    onToolStart: (tool: string) => void
    onSources: (sources: SourceRecord[]) => void
    onInterrupt: (payload: HITLPayload, content: string, sources?: SourceRecord[]) => void
    onDone: (content: string, sources?: SourceRecord[]) => void
    onError: (err: Error) => void
  }
): () => void {
  return streamChatEndpoint(
    `${API_BASE}/chats/${encodeURIComponent(chatId)}/resume`,
    auth,
    { response },
    handlers
  )
}

function streamChatEndpoint(
  url: string,
  auth: AuthSession,
  body: unknown,
  handlers: {
    onToken: (token: string) => void
    onToolStart: (tool: string) => void
    onSources: (sources: SourceRecord[]) => void
    onInterrupt: (payload: HITLPayload, content: string, sources?: SourceRecord[]) => void
    onDone: (content: string, sources?: SourceRecord[]) => void
    onError: (err: Error) => void
  }
): () => void {
  const controller = new AbortController()

  ;(async () => {
    const res = await fetch(url, {
      method: 'POST',
      headers: {
        Authorization: auth.authHeader,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    })

    if (!res.ok) throw await toApiError(res)
    if (!res.body) throw new Error('Streaming response body missing')

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let finalContent = ''
    let finalSources: SourceRecord[] | undefined

    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parsed = parseSseChunk(buffer)
      buffer = parsed.rest

      for (const eventText of parsed.events) {
        const event = parseSseEvent(eventText)
        if (!event) continue
        if (event === '[DONE]') {
          handlers.onDone(finalContent, finalSources)
          return
        }
        if (event.type === 'token') {
          finalContent += event.content
          handlers.onToken(event.content)
        } else if (event.type === 'tool_start') {
          handlers.onToolStart(event.tool)
        } else if (event.type === 'sources') {
          finalSources = event.records ?? finalSources
          if (event.records) handlers.onSources(event.records)
        } else if (event.type === 'interrupt') {
          handlers.onInterrupt(event.payload, finalContent, finalSources)
          return
        } else if (event.type === 'done') {
          finalContent = event.result.answer
          finalSources = event.result.source_records
          handlers.onDone(finalContent, finalSources)
          return
        } else if (event.type === 'error') {
          throw new Error(event.detail || event.error || 'Streaming failed')
        }
      }
    }

    handlers.onDone(finalContent, finalSources)
  })().catch((error) => {
    if (controller.signal.aborted) return
    handlers.onError(error instanceof Error ? error : new Error('Unknown stream error'))
  })

  return () => controller.abort()
}

export { generateId }
