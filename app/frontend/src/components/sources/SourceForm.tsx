import { Loader2, Plus, Rocket } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { SourceItem } from './SourceItem'
import type { SourceEntry } from '@/types/sources'
import { generateId } from '@/lib/utils'

const MAX_SOURCES = 50

interface SourceFormProps {
  sources: SourceEntry[]
  onChange: (sources: SourceEntry[]) => void
  onSubmit: () => void
  submitLabel?: string
  submitDisabled?: boolean
  submitLoading?: boolean
  submitLoadingLabel?: string
  compact?: boolean
}

function emptySource(): SourceEntry {
  return {
    id: generateId(),
    inputType: 'url',
    url: '',
    detectedType: 'webpage',
  }
}

export function SourceForm({
  sources,
  onChange,
  onSubmit,
  submitLabel = 'Start Chat',
  submitDisabled = false,
  submitLoading = false,
  submitLoadingLabel = 'Working...',
  compact = false,
}: SourceFormProps) {
  const addSource = () => {
    if (sources.length >= MAX_SOURCES) return
    onChange([...sources, emptySource()])
  }

  const updateSource = (id: string, updated: SourceEntry) => {
    onChange(sources.map((s) => (s.id === id ? updated : s)))
  }

  const removeSource = (id: string) => {
    onChange(sources.filter((s) => s.id !== id))
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      {/* Scroll area */}
      <ScrollArea className={compact ? 'min-h-0 flex-1 pr-2' : 'h-[min(60vh,32rem)] pr-2'}>
        <div className="space-y-2 pr-1">
          {sources.length === 0 && (
            <div className="text-center py-8 text-muted-foreground text-sm">
              <p>No sources added yet.</p>
              <p className="text-xs mt-1">Add URLs, upload files, or connect a database to ground the conversation.</p>
            </div>
          )}
          {sources.map((entry) => (
            <SourceItem
              key={entry.id}
              entry={entry}
              onChange={(updated) => updateSource(entry.id, updated)}
              onRemove={() => removeSource(entry.id)}
            />
          ))}
        </div>
      </ScrollArea>

      {/* Footer */}
      <div className="flex items-center gap-2 pt-1 border-t">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={addSource}
          disabled={sources.length >= MAX_SOURCES}
          className="gap-1.5"
        >
          <Plus size={14} />
          Add Source
        </Button>

        <Badge variant="secondary" className="text-xs ml-1">
          {sources.length} / {MAX_SOURCES}
        </Badge>

        <div className="flex-1" />

        <Button
          type="button"
          onClick={onSubmit}
          disabled={submitDisabled || submitLoading}
          className="gap-1.5"
          size="sm"
        >
          {submitLoading ? <Loader2 size={14} className="animate-spin" /> : <Rocket size={14} />}
          {submitLoading ? submitLoadingLabel : submitLabel}
        </Button>
      </div>
    </div>
  )
}
