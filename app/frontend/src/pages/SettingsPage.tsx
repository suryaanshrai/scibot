import { useEffect, useState } from 'react'
import { Loader2, Save, Database, Key, Search, Cpu, HardDrive, RotateCcw, MessageSquare } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { cn } from '@/lib/utils'
import { LLMSettings } from '@/components/settings/LLMSettings'
import { EmbeddingSettings } from '@/components/settings/EmbeddingSettings'
import { StoreSettings } from '@/components/settings/StoreSettings'
import { APIKeysSettings } from '@/components/settings/APIKeysSettings'
import { SearchSettings } from '@/components/settings/SearchSettings'
import { useAuthStore } from '@/stores/authStore'
import { useChatStore } from '@/stores/chatStore'
import { useConfigStore } from '@/stores/configStore'
import { getChatHistory, saveChatConfig, saveGlobalConfig } from '@/lib/api'
import { normalizeUserConfig, type UserConfig } from '@/types/config'

const SECTIONS = [
  { id: 'llm', label: 'LLM Model', icon: Cpu },
  { id: 'embedding', label: 'Embeddings', icon: HardDrive },
  { id: 'store', label: 'Vector Store', icon: Database },
  { id: 'api-keys', label: 'API Keys', icon: Key },
  { id: 'search', label: 'Web Search', icon: Search },
]

const CHAT_SECTION_IDS = new Set(['llm', 'embedding', 'store'])

type SettingsScope = 'global' | 'chat'

function mergeChatConfig(globalConfig: UserConfig, chatOverride?: Partial<UserConfig>) {
  return normalizeUserConfig({
    ...globalConfig,
    ...chatOverride,
    llm: { ...globalConfig.llm, ...(chatOverride?.llm ?? {}) },
    embedding: { ...globalConfig.embedding, ...(chatOverride?.embedding ?? {}) },
    store: { ...globalConfig.store, ...(chatOverride?.store ?? {}) },
    external_keys: { ...globalConfig.external_keys, ...(chatOverride?.external_keys ?? {}) },
    data_source_creds: { ...globalConfig.data_source_creds, ...(chatOverride?.data_source_creds ?? {}) },
    search: { ...globalConfig.search, ...(chatOverride?.search ?? {}) },
  })
}

export function SettingsPage() {
  const { username, authHeader, globalConfig, configOptions, updateGlobalConfig } = useAuthStore()
  const { chats } = useChatStore()
  const { chatConfigs, setChatConfig, resetChatConfig } = useConfigStore()
  const [active, setActive] = useState('llm')
  const [scope, setScope] = useState<SettingsScope>('global')
  const [selectedChatId, setSelectedChatId] = useState('')
  const [saving, setSaving] = useState(false)
  const [savedScope, setSavedScope] = useState<SettingsScope | null>(null)
  const [loadingChatConfig, setLoadingChatConfig] = useState(false)
  const [localGlobalConfig, setLocalGlobalConfig] = useState<UserConfig>({ ...globalConfig })
  const [localChatConfig, setLocalChatConfig] = useState<UserConfig>(mergeChatConfig(globalConfig))

  useEffect(() => {
    setLocalGlobalConfig(globalConfig)
  }, [globalConfig])

  useEffect(() => {
    if (!chats.length) {
      setSelectedChatId('')
      return
    }
    if (!selectedChatId || !chats.some((chat) => chat.chatId === selectedChatId)) {
      setSelectedChatId(chats[0].chatId)
    }
  }, [chats, selectedChatId])

  useEffect(() => {
    if (scope === 'chat' && !CHAT_SECTION_IDS.has(active)) {
      setActive('llm')
    }
  }, [active, scope])

  useEffect(() => {
    let cancelled = false

    const syncChatConfig = async () => {
      if (!selectedChatId) {
        setLocalChatConfig(mergeChatConfig(globalConfig))
        return
      }

      if (Object.prototype.hasOwnProperty.call(chatConfigs, selectedChatId)) {
        setLoadingChatConfig(false)
        setLocalChatConfig(mergeChatConfig(globalConfig, chatConfigs[selectedChatId]))
        return
      }

      if (!username || !authHeader) {
        setLocalChatConfig(mergeChatConfig(globalConfig))
        return
      }

      setLoadingChatConfig(true)
      try {
        const history = await getChatHistory({ username, authHeader }, selectedChatId)
        if (cancelled) return
        setChatConfig(selectedChatId, history.chatConfig)
        setLocalChatConfig(mergeChatConfig(globalConfig, history.chatConfig))
      } catch (error) {
        if (cancelled) return
        console.error(error)
        setLocalChatConfig(mergeChatConfig(globalConfig))
      } finally {
        if (!cancelled) setLoadingChatConfig(false)
      }
    }

    void syncChatConfig()

    return () => {
      cancelled = true
    }
  }, [authHeader, chatConfigs, globalConfig, selectedChatId, setChatConfig, username])

  const sections = scope === 'chat'
    ? SECTIONS.filter((section) => CHAT_SECTION_IDS.has(section.id))
    : SECTIONS

  const selectedChat = chats.find((chat) => chat.chatId === selectedChatId) ?? null
  const currentConfig = scope === 'chat' ? localChatConfig : localGlobalConfig

  const patchConfig = (key: keyof UserConfig, updates: unknown) => {
    const patch = (config: UserConfig) => ({
      ...config,
      [key]: { ...(config[key] as object), ...(updates as object) },
    })

    if (scope === 'chat') {
      setLocalChatConfig((config) => patch(config))
      return
    }

    setLocalGlobalConfig((config) => patch(config))
  }

  const handleSave = async () => {
    if (!username || !authHeader) return
    setSaving(true)
    try {
      if (scope === 'chat') {
        if (!selectedChatId) return
        const updated = await saveChatConfig({ username, authHeader }, selectedChatId, localChatConfig)
        const nextOverride = updated.config_override ?? localChatConfig
        setChatConfig(selectedChatId, nextOverride)
        setLocalChatConfig(mergeChatConfig(globalConfig, nextOverride))
      } else {
        const updated = await saveGlobalConfig({ username, authHeader }, localGlobalConfig)
        updateGlobalConfig(updated)
        setLocalGlobalConfig(updated)
      }
      setSavedScope(scope)
      setTimeout(() => setSavedScope((current) => (current === scope ? null : current)), 2000)
    } finally {
      setSaving(false)
    }
  }

  const handleResetChat = async () => {
    if (!selectedChatId || !username || !authHeader) return
    setSaving(true)
    try {
      const updated = await saveChatConfig({ username, authHeader }, selectedChatId, {})
      const nextOverride = updated.config_override ?? {}
      if (Object.keys(nextOverride).length === 0) {
        resetChatConfig(selectedChatId)
      } else {
        setChatConfig(selectedChatId, nextOverride)
      }
      setLocalChatConfig(mergeChatConfig(globalConfig, nextOverride))
      setSavedScope('chat')
      setTimeout(() => setSavedScope((current) => (current === 'chat' ? null : current)), 2000)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex h-full">
      {/* Vertical nav */}
      <nav className="w-48 shrink-0 border-r p-2 space-y-0.5">
        <p className="px-2 py-1.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Settings</p>
        {sections.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setActive(id)}
            className={cn(
              'w-full flex items-center gap-2 px-2 py-2 rounded-md text-sm transition-colors text-left',
              active === id
                ? 'bg-primary/10 text-primary font-medium'
                : 'hover:bg-muted text-foreground'
            )}
          >
            <Icon size={15} className="shrink-0" />
            {label}
          </button>
        ))}
      </nav>

      {/* Content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="border-b px-6 py-4 space-y-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h1 className="font-semibold">{sections.find((section) => section.id === active)?.label}</h1>
              <p className="text-xs text-muted-foreground mt-0.5">
                {scope === 'global'
                  ? 'Global defaults that apply across chats unless overridden.'
                  : 'Chat-specific overrides layered on top of the global defaults.'}
              </p>
            </div>
            <div className="flex items-center gap-2">
              {scope === 'chat' && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleResetChat}
                  disabled={saving || loadingChatConfig || !selectedChatId}
                  className="gap-1.5"
                >
                  <RotateCcw size={14} />
                  Reset to global
                </Button>
              )}
              <Button
                size="sm"
                onClick={handleSave}
                disabled={saving || loadingChatConfig || (scope === 'chat' && !selectedChatId)}
                className="gap-1.5"
              >
                {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                {savedScope === scope ? 'Saved!' : 'Save'}
              </Button>
            </div>
          </div>

          <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <Tabs value={scope} onValueChange={(value) => setScope(value as SettingsScope)}>
              <TabsList>
                <TabsTrigger value="global">Global defaults</TabsTrigger>
                <TabsTrigger value="chat">Chat overrides</TabsTrigger>
              </TabsList>
            </Tabs>

            {scope === 'chat' && (
              <div className="flex w-full flex-col gap-2 lg:w-auto lg:min-w-80">
                <p className="text-xs font-medium text-muted-foreground">Chat</p>
                <Select value={selectedChatId} onValueChange={setSelectedChatId} disabled={!chats.length || loadingChatConfig}>
                  <SelectTrigger>
                    <SelectValue placeholder={chats.length ? 'Select a chat' : 'No chats available'} />
                  </SelectTrigger>
                  <SelectContent>
                    {chats.map((chat) => (
                      <SelectItem key={chat.chatId} value={chat.chatId}>
                        {chat.title}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {selectedChat && (
                  <p className="text-xs text-muted-foreground">
                    Overrides currently apply only to “{selectedChat.title}”.
                  </p>
                )}
              </div>
            )}
          </div>
        </div>

        <ScrollArea className="flex-1">
          <div className="p-6 max-w-lg">
            {scope === 'chat' && !chats.length && (
              <div className="rounded-lg border border-dashed p-5 text-sm text-muted-foreground">
                <div className="flex items-center gap-2 text-foreground">
                  <MessageSquare size={16} />
                  <span className="font-medium">No chats available yet</span>
                </div>
                <p className="mt-2">
                  Start a chat first, then return here to configure per-chat overrides.
                </p>
              </div>
            )}

            {scope === 'chat' && chats.length > 0 && loadingChatConfig && (
              <div className="flex items-center gap-2 rounded-lg border p-4 text-sm text-muted-foreground">
                <Loader2 size={16} className="animate-spin" />
                <span>Loading chat settings…</span>
              </div>
            )}

            {(!loadingChatConfig || scope === 'global') && (scope === 'global' || chats.length > 0) && active === 'llm' && (
              <LLMSettings
                config={currentConfig.llm}
                options={configOptions.llms}
                onChange={(u) => patchConfig('llm', u)}
                isOverride={scope === 'chat'}
              />
            )}
            {(!loadingChatConfig || scope === 'global') && (scope === 'global' || chats.length > 0) && active === 'embedding' && (
              <EmbeddingSettings
                config={currentConfig.embedding}
                options={configOptions.embeddings}
                onChange={(u) => patchConfig('embedding', u)}
              />
            )}
            {(!loadingChatConfig || scope === 'global') && (scope === 'global' || chats.length > 0) && active === 'store' && (
              <StoreSettings
                config={currentConfig.store}
                options={configOptions.stores}
                onChange={(u) => patchConfig('store', u)}
              />
            )}
            {scope === 'global' && active === 'api-keys' && (
              <APIKeysSettings
                keys={currentConfig.external_keys}
                onChange={(u) => patchConfig('external_keys', u)}
              />
            )}
            {scope === 'global' && active === 'search' && (
              <SearchSettings
                config={currentConfig.search}
                onChange={(u) => patchConfig('search', u)}
                keys={currentConfig.external_keys}
                onKeysChange={(u) => patchConfig('external_keys', u)}
              />
            )}
          </div>
        </ScrollArea>
      </div>
    </div>
  )
}
