import { useEffect, useState } from 'react'
import { RotateCcw, Save } from 'lucide-react'
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetFooter,
} from '@/components/ui/sheet'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ScrollArea } from '@/components/ui/scroll-area'
import { LLMSettings } from '@/components/settings/LLMSettings'
import { EmbeddingSettings } from '@/components/settings/EmbeddingSettings'
import { StoreSettings } from '@/components/settings/StoreSettings'
import { useAuthStore } from '@/stores/authStore'
import { useConfigStore } from '@/stores/configStore'
import { saveChatConfig } from '@/lib/api'
import { normalizeUserConfig, type UserConfig } from '@/types/config'

interface ChatSettingsSheetProps {
  chatId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function ChatSettingsSheet({ chatId, open, onOpenChange }: ChatSettingsSheetProps) {
  const { username, authHeader, globalConfig, configOptions } = useAuthStore()
  const { getChatConfig, setChatConfig, resetChatConfig } = useConfigStore()
  const chatOverride = getChatConfig(chatId)

  // Merge global → chat override as local editable state
  const [local, setLocal] = useState<UserConfig>({
    ...globalConfig,
    ...chatOverride,
    llm: { ...globalConfig.llm, ...(chatOverride.llm ?? {}) },
    embedding: { ...globalConfig.embedding, ...(chatOverride.embedding ?? {}) },
    store: { ...globalConfig.store, ...(chatOverride.store ?? {}) },
  })

  useEffect(() => {
    setLocal({
      ...globalConfig,
      ...chatOverride,
      llm: { ...globalConfig.llm, ...(chatOverride.llm ?? {}) },
      embedding: { ...globalConfig.embedding, ...(chatOverride.embedding ?? {}) },
      store: { ...globalConfig.store, ...(chatOverride.store ?? {}) },
    })
  }, [chatOverride, globalConfig, open])

  const patch = (key: keyof UserConfig, updates: unknown) => {
    setLocal((c) => ({ ...c, [key]: { ...(c[key] as object), ...(updates as object) } }))
  }

  const handleSave = async () => {
    if (!username || !authHeader) return
    const updated = await saveChatConfig({ username, authHeader }, chatId, local)
    setChatConfig(chatId, normalizeUserConfig(updated.config_override ?? local))
    onOpenChange(false)
  }

  const handleReset = () => {
    resetChatConfig(chatId)
    setLocal({ ...globalConfig })
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-md flex flex-col p-0">
        <SheetHeader className="px-6 pt-6 pb-3 border-b">
          <SheetTitle>Chat Settings</SheetTitle>
          <p className="text-xs text-muted-foreground">
            Overrides global defaults for this chat only.
          </p>
        </SheetHeader>

        <ScrollArea className="flex-1 px-6 py-4">
          <Tabs defaultValue="llm">
            <TabsList className="mb-4">
              <TabsTrigger value="llm">LLM</TabsTrigger>
              <TabsTrigger value="embedding">Embeddings</TabsTrigger>
              <TabsTrigger value="store">Vector Store</TabsTrigger>
            </TabsList>

            <TabsContent value="llm">
              <LLMSettings config={local.llm} options={configOptions.llms} onChange={(u) => patch('llm', u)} isOverride />
            </TabsContent>
            <TabsContent value="embedding">
              <EmbeddingSettings config={local.embedding} options={configOptions.embeddings} onChange={(u) => patch('embedding', u)} />
            </TabsContent>
            <TabsContent value="store">
              <StoreSettings config={local.store} options={configOptions.stores} onChange={(u) => patch('store', u)} />
            </TabsContent>
          </Tabs>
        </ScrollArea>

        <SheetFooter className="px-6 py-4 border-t gap-2 flex-row">
          <Button variant="outline" size="sm" className="gap-1.5 flex-1" onClick={handleReset}>
            <RotateCcw size={13} />
            Reset to global
          </Button>
          <Button size="sm" className="gap-1.5 flex-1" onClick={handleSave}>
            <Save size={13} />
            Save
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}
