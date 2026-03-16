import { useEffect, useState } from 'react'
import { RotateCcw, Save } from 'lucide-react'
import {
  Sheet, SheetContent, SheetFooter, SheetHeader, SheetTitle,
} from '@/components/ui/sheet'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { LLMSettings } from '@/components/settings/LLMSettings'
import { EmbeddingSettings } from '@/components/settings/EmbeddingSettings'
import { StoreSettings } from '@/components/settings/StoreSettings'
import { useAuthStore } from '@/stores/authStore'
import { useConfigStore } from '@/stores/configStore'
import { normalizeUserConfig, type UserConfig } from '@/types/config'

interface NewChatSettingsSheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

function mergeConfig(globalConfig: UserConfig, override?: Partial<UserConfig>) {
  return normalizeUserConfig({
    ...globalConfig,
    ...override,
    llm: { ...globalConfig.llm, ...(override?.llm ?? {}) },
    embedding: { ...globalConfig.embedding, ...(override?.embedding ?? {}) },
    store: { ...globalConfig.store, ...(override?.store ?? {}) },
  })
}

export function NewChatSettingsSheet({ open, onOpenChange }: NewChatSettingsSheetProps) {
  const { globalConfig, configOptions } = useAuthStore()
  const { pendingChatConfig, setPendingChatConfig, resetPendingChatConfig } = useConfigStore()

  const [local, setLocal] = useState<UserConfig>(mergeConfig(globalConfig, pendingChatConfig))

  useEffect(() => {
    setLocal(mergeConfig(globalConfig, pendingChatConfig))
  }, [globalConfig, open, pendingChatConfig])

  const patch = (key: keyof UserConfig, updates: unknown) => {
    setLocal((config) => ({
      ...config,
      [key]: { ...(config[key] as object), ...(updates as object) },
    }))
  }

  const handleSave = () => {
    setPendingChatConfig(local)
    onOpenChange(false)
  }

  const handleReset = () => {
    resetPendingChatConfig()
    setLocal({ ...globalConfig })
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-md flex flex-col p-0">
        <SheetHeader className="px-6 pt-6 pb-3 border-b">
          <SheetTitle>New Chat Settings</SheetTitle>
          <p className="text-xs text-muted-foreground">
            Choose overrides that will be applied when this chat is created.
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