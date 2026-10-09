import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Check, Cpu, Database, HardDrive, KeyRound, Search } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Field, SelectInput, Segmented, Spinner } from '@/components/sb/primitives'
import { ghostButtonClass, primaryButtonClass } from '@/components/sb/styles'
import { LLMSettings } from '@/components/settings/LLMSettings'
import { EmbeddingSettings } from '@/components/settings/EmbeddingSettings'
import { StoreSettings } from '@/components/settings/StoreSettings'
import { APIKeysSettings } from '@/components/settings/APIKeysSettings'
import { SearchSettings } from '@/components/settings/SearchSettings'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/stores/authStore'
import { useChatStore } from '@/stores/chatStore'
import { useConfigStore } from '@/stores/configStore'
import { getChatHistory, saveChatConfig, saveGlobalConfig } from '@/lib/api'
import { normalizeUserConfig, type UserConfig } from '@/types/config'

type SectionId = 'llm' | 'embedding' | 'store' | 'api-keys' | 'search'
type SettingsScope = 'global' | 'chat'

const SECTIONS: { id: SectionId; label: string; icon: LucideIcon }[] = [
  { id: 'llm', label: 'LLM Model', icon: Cpu },
  { id: 'embedding', label: 'Embeddings', icon: HardDrive },
  { id: 'store', label: 'Vector Store', icon: Database },
  { id: 'api-keys', label: 'API Keys', icon: KeyRound },
  { id: 'search', label: 'Web Search', icon: Search },
]

const CHAT_SECTION_IDS = new Set<SectionId>(['llm', 'embedding', 'store'])

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
  const [params, setParams] = useSearchParams()
  const { username, authHeader, globalConfig, configOptions, updateGlobalConfig } = useAuthStore()
  const { chats } = useChatStore()
  const { chatConfigs, setChatConfig, resetChatConfig } = useConfigStore()

  const scope: SettingsScope = params.get('scope') === 'chat' ? 'chat' : 'global'
  const requestedSection = (params.get('section') as SectionId | null) ?? 'llm'
  const section: SectionId =
    SECTIONS.some((s) => s.id === requestedSection) && (scope === 'global' || CHAT_SECTION_IDS.has(requestedSection))
      ? requestedSection
      : 'llm'
  const requestedChat = params.get('chat') ?? ''
  const selectedChatId = chats.some((c) => c.chatId === requestedChat) ? requestedChat : (chats[0]?.chatId ?? '')

  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loadingChatConfig, setLoadingChatConfig] = useState(false)
  const [localGlobalConfig, setLocalGlobalConfig] = useState<UserConfig>(globalConfig)
  const [localChatConfig, setLocalChatConfig] = useState<UserConfig>(() => mergeChatConfig(globalConfig))

  const update = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(patch)) {
      if (value === null) next.delete(key)
      else next.set(key, value)
    }
    setParams(next, { replace: true })
  }

  useEffect(() => {
    setLocalGlobalConfig(globalConfig)
  }, [globalConfig])

  useEffect(() => {
    let cancelled = false
    const sync = async () => {
      if (!selectedChatId) {
        setLocalChatConfig(mergeChatConfig(globalConfig))
        return
      }
      if (Object.prototype.hasOwnProperty.call(chatConfigs, selectedChatId)) {
        setLoadingChatConfig(false)
        setLocalChatConfig(mergeChatConfig(globalConfig, chatConfigs[selectedChatId]))
        return
      }
      if (!username || !authHeader) return
      setLoadingChatConfig(true)
      try {
        const history = await getChatHistory({ username, authHeader }, selectedChatId)
        if (cancelled) return
        setChatConfig(selectedChatId, history.chatConfig)
      } catch (err) {
        if (!cancelled) {
          console.error(err)
          setLocalChatConfig(mergeChatConfig(globalConfig))
        }
      } finally {
        if (!cancelled) setLoadingChatConfig(false)
      }
    }
    void sync()
    return () => {
      cancelled = true
    }
  }, [authHeader, chatConfigs, globalConfig, selectedChatId, setChatConfig, username])

  const sections = scope === 'chat' ? SECTIONS.filter((s) => CHAT_SECTION_IDS.has(s.id)) : SECTIONS
  const currentConfig = scope === 'chat' ? localChatConfig : localGlobalConfig
  const selectedChat = useMemo(() => chats.find((c) => c.chatId === selectedChatId) ?? null, [chats, selectedChatId])
  const noChats = scope === 'chat' && chats.length === 0
  const disabled = saving || loadingChatConfig || (scope === 'chat' && !selectedChatId)

  const patchConfig = (key: keyof UserConfig, updates: unknown) => {
    const patch = (config: UserConfig) => ({ ...config, [key]: { ...(config[key] as object), ...(updates as object) } })
    if (scope === 'chat') setLocalChatConfig(patch)
    else setLocalGlobalConfig(patch)
  }

  const flashSaved = () => {
    setSaved(true)
    window.setTimeout(() => setSaved(false), 2000)
  }

  const handleSave = async () => {
    if (!username || !authHeader) return
    setSaving(true)
    setError(null)
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
      flashSaved()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save settings')
    } finally {
      setSaving(false)
    }
  }

  const handleResetChat = async () => {
    if (!selectedChatId || !username || !authHeader) return
    setSaving(true)
    setError(null)
    try {
      const updated = await saveChatConfig({ username, authHeader }, selectedChatId, {})
      const nextOverride = updated.config_override ?? {}
      if (Object.keys(nextOverride).length === 0) resetChatConfig(selectedChatId)
      else setChatConfig(selectedChatId, nextOverride)
      setLocalChatConfig(mergeChatConfig(globalConfig, nextOverride))
      flashSaved()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reset overrides')
    } finally {
      setSaving(false)
    }
  }

  const title = SECTIONS.find((s) => s.id === section)?.label ?? ''

  return (
    <>
      <header data-screen-label="Settings" className="flex h-14 flex-none items-center border-b border-line px-7 max-sm:px-4">
        <span className="text-[14.5px] font-semibold">Settings</span>
      </header>
      <div className="grid min-h-0 flex-1 grid-cols-[220px_minmax(0,1fr)] max-md:grid-cols-1 max-md:grid-rows-[auto_minmax(0,1fr)]">
        <nav className="flex flex-col gap-0.5 border-r border-line px-2.5 py-4 max-md:flex-row max-md:overflow-x-auto max-md:border-r-0 max-md:border-b max-md:py-2">
          {sections.map(({ id, label, icon: Icon }) => {
            const on = section === id
            return (
              <button
                key={id}
                type="button"
                onClick={() => update({ section: id })}
                className={cn(
                  'flex h-9 flex-none cursor-pointer items-center gap-2.5 rounded-[9px] border-0 px-3 text-left text-[13.5px] whitespace-nowrap transition-colors',
                  on ? 'bg-line font-semibold text-ink' : 'bg-transparent font-medium text-ink2 hover:bg-line hover:text-ink'
                )}
              >
                <Icon size={15} />
                {label}
              </button>
            )
          })}
        </nav>

        <div className="min-h-0 overflow-y-auto">
          <div className="max-w-[640px] px-12 pt-11 pb-[72px] max-sm:px-5 max-sm:pt-8">
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div>
                <h1 className="m-0 font-serif text-[38px] leading-[1.05] font-normal tracking-[-0.025em]">{title}</h1>
                <p className="mt-2.5 mb-0 text-[13.5px] leading-normal text-ink2">
                  {scope === 'global'
                    ? 'Global defaults that apply across chats unless overridden.'
                    : 'Chat-specific overrides layered on top of the global defaults.'}
                </p>
              </div>
              <div className="flex flex-none gap-2">
                {scope === 'chat' && (
                  <button type="button" onClick={() => void handleResetChat()} disabled={disabled} className={ghostButtonClass}>
                    Reset to global
                  </button>
                )}
                <button type="button" onClick={() => void handleSave()} disabled={disabled} className={primaryButtonClass}>
                  {saving ? <Spinner className="text-accink" /> : saved ? <Check size={14} /> : null}
                  {saved ? 'Saved' : 'Save'}
                </button>
              </div>
            </div>

            <Segmented
              className="mt-7"
              value={scope}
              onChange={(next) => update({ scope: next === 'chat' ? 'chat' : null })}
              options={[
                { value: 'global', label: 'Global defaults' },
                { value: 'chat', label: 'Chat overrides' },
              ]}
            />

            {scope === 'chat' && !noChats && (
              <Field
                className="mt-5"
                label="Chat"
                hint={selectedChat ? `Overrides currently apply only to “${selectedChat.title}”.` : undefined}
              >
                <SelectInput
                  value={selectedChatId}
                  onChange={(chat) => update({ chat })}
                  options={chats.map((c) => ({ value: c.chatId, label: c.title }))}
                  disabled={loadingChatConfig}
                />
              </Field>
            )}

            {error && <p className="mt-5 mb-0 text-[13px] font-medium text-warn">{error}</p>}

            <div className="mt-8 flex flex-col gap-[22px] border-t border-line pt-7">
              {noChats ? (
                <p className="m-0 text-[13.5px] leading-normal text-ink2">
                  Start a chat first, then return here to configure per-chat overrides.
                </p>
              ) : scope === 'chat' && loadingChatConfig ? (
                <p className="m-0 flex items-center gap-2 text-[13px] text-ink3">
                  <Spinner /> Loading chat settings…
                </p>
              ) : (
                <>
                  {section === 'llm' && (
                    <LLMSettings config={currentConfig.llm} options={configOptions.llms} onChange={(u) => patchConfig('llm', u)} />
                  )}
                  {section === 'embedding' && (
                    <EmbeddingSettings
                      config={currentConfig.embedding}
                      options={configOptions.embeddings}
                      onChange={(u) => patchConfig('embedding', u)}
                    />
                  )}
                  {section === 'store' && (
                    <StoreSettings config={currentConfig.store} options={configOptions.stores} onChange={(u) => patchConfig('store', u)} />
                  )}
                  {section === 'api-keys' && (
                    <APIKeysSettings keys={currentConfig.external_keys} onChange={(u) => patchConfig('external_keys', u)} />
                  )}
                  {section === 'search' && (
                    <SearchSettings
                      config={currentConfig.search}
                      onChange={(u) => patchConfig('search', u)}
                      keys={currentConfig.external_keys}
                      onKeysChange={(u) => patchConfig('external_keys', u)}
                    />
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
