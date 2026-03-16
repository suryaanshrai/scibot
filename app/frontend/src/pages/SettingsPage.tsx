import { useEffect, useState } from 'react'
import { Loader2, Save, Database, Key, Search, Cpu, HardDrive } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'
import { LLMSettings } from '@/components/settings/LLMSettings'
import { EmbeddingSettings } from '@/components/settings/EmbeddingSettings'
import { StoreSettings } from '@/components/settings/StoreSettings'
import { APIKeysSettings } from '@/components/settings/APIKeysSettings'
import { SearchSettings } from '@/components/settings/SearchSettings'
import { useAuthStore } from '@/stores/authStore'
import { saveGlobalConfig } from '@/lib/api'
import type { UserConfig } from '@/types/config'

const SECTIONS = [
  { id: 'llm', label: 'LLM Model', icon: Cpu },
  { id: 'embedding', label: 'Embeddings', icon: HardDrive },
  { id: 'store', label: 'Vector Store', icon: Database },
  { id: 'api-keys', label: 'API Keys', icon: Key },
  { id: 'search', label: 'Web Search', icon: Search },
]

export function SettingsPage() {
  const { username, authHeader, globalConfig, configOptions, updateGlobalConfig } = useAuthStore()
  const [active, setActive] = useState('llm')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [localConfig, setLocalConfig] = useState<UserConfig>({ ...globalConfig })

  useEffect(() => {
    setLocalConfig(globalConfig)
  }, [globalConfig])

  const patchConfig = (key: keyof UserConfig, updates: unknown) => {
    setLocalConfig((c) => ({ ...c, [key]: { ...(c[key] as object), ...(updates as object) } }))
  }

  const handleSave = async () => {
    if (!username || !authHeader) return
    setSaving(true)
    try {
      const updated = await saveGlobalConfig({ username, authHeader }, localConfig)
      updateGlobalConfig(updated)
      setLocalConfig(updated)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex h-full">
      {/* Vertical nav */}
      <nav className="w-48 shrink-0 border-r p-2 space-y-0.5">
        <p className="px-2 py-1.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Settings</p>
        {SECTIONS.map(({ id, label, icon: Icon }) => (
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
        <div className="border-b px-6 py-4 flex items-center justify-between">
          <div>
            <h1 className="font-semibold">{SECTIONS.find((s) => s.id === active)?.label}</h1>
            <p className="text-xs text-muted-foreground mt-0.5">Global defaults — can be overridden per chat.</p>
          </div>
          <Button size="sm" onClick={handleSave} disabled={saving} className="gap-1.5">
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            {saved ? 'Saved!' : 'Save'}
          </Button>
        </div>

        <ScrollArea className="flex-1">
          <div className="p-6 max-w-lg">
            {active === 'llm' && (
              <LLMSettings
                config={localConfig.llm}
                options={configOptions.llms}
                onChange={(u) => patchConfig('llm', u)}
              />
            )}
            {active === 'embedding' && (
              <EmbeddingSettings
                config={localConfig.embedding}
                options={configOptions.embeddings}
                onChange={(u) => patchConfig('embedding', u)}
              />
            )}
            {active === 'store' && (
              <StoreSettings
                config={localConfig.store}
                options={configOptions.stores}
                onChange={(u) => patchConfig('store', u)}
              />
            )}
            {active === 'api-keys' && (
              <APIKeysSettings
                keys={localConfig.external_keys}
                onChange={(u) => patchConfig('external_keys', u)}
              />
            )}
            {active === 'search' && (
              <SearchSettings
                config={localConfig.search}
                onChange={(u) => patchConfig('search', u)}
                keys={localConfig.external_keys}
                onKeysChange={(u) => patchConfig('external_keys', u)}
              />
            )}
          </div>
        </ScrollArea>
      </div>
    </div>
  )
}
