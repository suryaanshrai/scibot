export interface LLMConfig {
  provider: string
  model: string
  temperature?: number
  max_tokens?: number
  api_key?: string
}

export interface EmbeddingConfig {
  provider: string
  model: string
  api_key?: string
  dimensions?: number
}

export interface StoreConfig {
  provider: string
  collection_name: string
  namespace?: string
  connection_string?: string
  [key: string]: unknown
}

export interface ExternalKeys {
  SEMANTIC_SCHOLAR_API_KEY?: string
  NCBI_API_KEY?: string
  GITHUB_TOKEN?: string
  TAVILY_API_KEY?: string
  SERPAPI_API_KEY?: string
}

export interface DataSourceCred {
  type: 'postgres' | 'mongodb'
  connection_string: string
  [key: string]: unknown
}

export interface SearchConfig {
  tool: 'tavily' | 'serp' | 'duckduckgo'
  whitelist_extra?: string[]
}

export interface UserConfig {
  llm: LLMConfig
  embedding: EmbeddingConfig
  store: StoreConfig
  external_keys: ExternalKeys
  data_source_creds: Record<string, DataSourceCred>
  search: SearchConfig
}

export interface ModelOption {
  id: string
  name: string
}

export interface LLMProviderOption {
  provider: string
  human_name: string
  default_model: string
  models: ModelOption[]
}

export interface EmbeddingProviderOption {
  provider: string
  human_name: string
  default_model: string
  supports_dimensions: boolean
  models: ModelOption[]
}

export interface StoreProviderOption {
  provider: string
  human_name: string
  description: string
}

export interface ConfigOptions {
  llms: LLMProviderOption[]
  embeddings: EmbeddingProviderOption[]
  stores: StoreProviderOption[]
}

export const EMPTY_CONFIG: UserConfig = {
  llm: { provider: '', model: '', temperature: 0.7 },
  embedding: { provider: '', model: '' },
  store: { provider: '', collection_name: '' },
  external_keys: {},
  data_source_creds: {},
  search: { tool: 'duckduckgo', whitelist_extra: [] },
}

export const EMPTY_CONFIG_OPTIONS: ConfigOptions = {
  llms: [],
  embeddings: [],
  stores: [],
}

export function normalizeUserConfig(input?: Partial<UserConfig> | null): UserConfig {
  return {
    llm: {
      ...EMPTY_CONFIG.llm,
      ...(input?.llm ?? {}),
      temperature: input?.llm?.temperature ?? EMPTY_CONFIG.llm.temperature,
    },
    embedding: {
      ...EMPTY_CONFIG.embedding,
      ...(input?.embedding ?? {}),
    },
    store: {
      ...EMPTY_CONFIG.store,
      ...(input?.store ?? {}),
    },
    external_keys: {
      ...(input?.external_keys ?? {}),
    },
    data_source_creds: {
      ...(input?.data_source_creds ?? {}),
    },
    search: {
      ...EMPTY_CONFIG.search,
      ...(input?.search ?? {}),
      whitelist_extra: input?.search?.whitelist_extra ?? EMPTY_CONFIG.search.whitelist_extra,
    },
  }
}

export const SEARCH_TOOLS = [
  { value: 'duckduckgo', label: 'DuckDuckGo' },
  { value: 'tavily', label: 'Tavily' },
  { value: 'serp', label: 'SerpAPI' },
]
