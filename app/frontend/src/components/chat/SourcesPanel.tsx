import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { SourceForm } from '@/components/sources/SourceForm'
import type { SourceEntry } from '@/types/sources'

interface SourcesPanelProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  sources: SourceEntry[]
  onSourcesChange: (sources: SourceEntry[]) => void
  onAddToChat: () => void
  busy?: boolean
  mode: 'new' | 'add'
}

export function SourcesPanel({ open, onOpenChange, sources, onSourcesChange, onAddToChat, busy = false, mode }: SourcesPanelProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-md flex flex-col p-0">
        <SheetHeader className="px-6 pt-6 pb-3 border-b">
          <SheetTitle>{mode === 'new' ? 'Add Sources' : 'Manage Sources'}</SheetTitle>
          <p className="text-xs text-muted-foreground">
            {mode === 'new'
              ? 'Ground the conversation with papers, videos, files and more.'
              : 'Add more sources to this ongoing conversation.'}
          </p>
        </SheetHeader>
        <div className="flex-1 min-h-0 overflow-hidden px-4 py-4">
          <SourceForm
            sources={sources}
            onChange={onSourcesChange}
            onSubmit={onAddToChat}
            submitLabel={mode === 'new' ? 'Start Chat' : 'Add to Chat'}
            submitDisabled={busy}
            submitLoading={busy}
            submitLoadingLabel={mode === 'new' ? 'Starting chat...' : 'Adding sources...'}
            compact
          />
        </div>
      </SheetContent>
    </Sheet>
  )
}
