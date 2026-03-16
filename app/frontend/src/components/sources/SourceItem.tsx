import React, { useCallback, useRef, useState } from 'react'
import { X, ChevronDown, ChevronUp, Link2, Upload, Database as DatabaseIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { detectUrl, detectFile } from '@/lib/sourceDetector'
import { SourceIcon, SOURCE_LABELS } from './SourceIcon'
import type { SourceEntry, RefParams } from '@/types/sources'
import { REF_PARAM_TYPES, DEFAULT_REF_PARAMS } from '@/types/sources'

interface SourceItemProps {
  entry: SourceEntry
  onChange: (updated: SourceEntry) => void
  onRemove: () => void
}

function useDebounce<T extends (...args: Parameters<T>) => void>(fn: T, delay = 350) {
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  return useCallback((...args: Parameters<T>) => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => fn(...args), delay)
  }, [fn, delay])
}

export function SourceItem({ entry, onChange, onRemove }: SourceItemProps) {
  const [refOpen, setRefOpen] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const showRefParams = REF_PARAM_TYPES.includes(entry.detectedType)

  const handleUrlChange = useDebounce((value: string) => {
    if (!value.trim()) {
      onChange({ ...entry, url: value, detectedType: 'webpage', previewMeta: undefined })
      return
    }
    const { type, preview } = detectUrl(value)
    const shouldAddRefParams = REF_PARAM_TYPES.includes(type) && !entry.refParams
    onChange({
      ...entry,
      url: value,
      detectedType: type,
      previewMeta: preview,
      refParams: shouldAddRefParams ? { ...DEFAULT_REF_PARAMS } : entry.refParams,
    })
  })

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const { type, preview } = detectFile(file)
    onChange({
      ...entry,
      inputType: 'file',
      file,
      fileName: file.name,
      detectedType: type,
      previewMeta: preview,
      refParams: REF_PARAM_TYPES.includes(type) ? { ...DEFAULT_REF_PARAMS } : undefined,
    })
  }

  const updateRefParams = (updates: Partial<RefParams>) => {
    onChange({ ...entry, refParams: { ...(entry.refParams ?? DEFAULT_REF_PARAMS), ...updates } })
  }

  const switchInputType = (inputType: SourceEntry['inputType']) => {
    if (inputType === 'url') {
      onChange({
        ...entry,
        inputType,
        file: undefined,
        fileName: undefined,
        detectedType: 'webpage',
        connectionString: undefined,
        database: undefined,
        table: undefined,
        mongoCollection: undefined,
        previewMeta: entry.url ? entry.previewMeta : undefined,
      })
      return
    }

    if (inputType === 'file') {
      onChange({
        ...entry,
        inputType,
        url: undefined,
        connectionString: undefined,
        database: undefined,
        table: undefined,
        mongoCollection: undefined,
        previewMeta: entry.fileName ? entry.previewMeta : undefined,
      })
      fileInputRef.current?.click()
      return
    }

    onChange({
      ...entry,
      inputType,
      url: undefined,
      file: undefined,
      fileName: undefined,
      detectedType: entry.detectedType === 'mongodb' ? 'mongodb' : 'postgres',
      previewMeta: undefined,
      refParams: undefined,
    })
  }

  const updateDatabaseType = (value: 'postgres' | 'mongodb') => {
    onChange({
      ...entry,
      inputType: 'database',
      detectedType: value,
      table: value === 'postgres' ? entry.table : undefined,
      mongoCollection: value === 'mongodb' ? entry.mongoCollection : undefined,
    })
  }

  const updateDatabaseField = (
    key: 'connectionString' | 'database' | 'table' | 'mongoCollection',
    value: string
  ) => {
    onChange({ ...entry, [key]: value })
  }

  return (
    <div className="rounded-lg border bg-card p-3 space-y-2">
      {/* Header row */}
      <div className="flex items-center gap-2">
        {/* Type icon + label */}
        <div className="flex items-center gap-1.5 min-w-0 flex-1">
          <SourceIcon type={entry.detectedType} size={16} />
          <span className="text-xs text-muted-foreground truncate">
            {SOURCE_LABELS[entry.detectedType]}
          </span>
          {entry.previewMeta?.label && (
            <span className="text-xs font-medium truncate text-foreground">
              — {entry.previewMeta.label}
            </span>
          )}
        </div>

        {/* Toggle URL / File / Data */}
        <div className="flex rounded-md border text-xs overflow-hidden shrink-0">
          <button
            type="button"
            onClick={() => switchInputType('url')}
            className={cn(
              'px-2 py-1 flex items-center gap-1',
              entry.inputType === 'url'
                ? 'bg-primary text-primary-foreground'
                : 'hover:bg-muted'
            )}
          >
            <Link2 size={12} /> URL
          </button>
          <button
            type="button"
            onClick={() => switchInputType('file')}
            className={cn(
              'px-2 py-1 flex items-center gap-1',
              entry.inputType === 'file'
                ? 'bg-primary text-primary-foreground'
                : 'hover:bg-muted'
            )}
          >
            <Upload size={12} /> File
          </button>
          <button
            type="button"
            onClick={() => switchInputType('database')}
            className={cn(
              'px-2 py-1 flex items-center gap-1',
              entry.inputType === 'database'
                ? 'bg-primary text-primary-foreground'
                : 'hover:bg-muted'
            )}
          >
            <DatabaseIcon size={12} /> Data
          </button>
        </div>

        <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0" onClick={onRemove} aria-label="Remove source">
          <X size={14} />
        </Button>
      </div>

      {/* URL input */}
      {entry.inputType === 'url' && (
        <div className="flex gap-2">
          {entry.previewMeta?.thumbnailUrl && (
            <img
              src={entry.previewMeta.thumbnailUrl}
              alt="thumbnail"
              className="h-10 w-16 rounded object-cover border shrink-0"
              onError={(e) => ((e.target as HTMLImageElement).style.display = 'none')}
            />
          )}
          <Input
            placeholder="Paste URL…"
            defaultValue={entry.url ?? ''}
            onChange={(e) => handleUrlChange(e.target.value)}
            className="h-8 text-sm"
          />
        </div>
      )}

      {/* File display */}
      {entry.inputType === 'file' && entry.fileName && (
        <div className="flex items-center gap-2 px-1">
          <SourceIcon type={entry.detectedType} size={14} />
          <span className="text-sm truncate">{entry.fileName}</span>
          <Button variant="ghost" size="icon" className="h-6 w-6 ml-auto shrink-0" onClick={() => fileInputRef.current?.click()}>
            <Upload size={12} />
          </Button>
        </div>
      )}

      {entry.inputType === 'database' && (
        <div className="space-y-3">
          <div className="space-y-1">
            <Label className="text-xs">Source type</Label>
            <Select value={entry.detectedType === 'mongodb' ? 'mongodb' : 'postgres'} onValueChange={(value) => updateDatabaseType(value as 'postgres' | 'mongodb')}>
              <SelectTrigger className="h-8 text-sm">
                <SelectValue placeholder="Choose database type" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="postgres">PostgreSQL</SelectItem>
                <SelectItem value="mongodb">MongoDB</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1">
            <Label className="text-xs">Connection string</Label>
            <Input
              value={entry.connectionString ?? ''}
              onChange={(e) => updateDatabaseField('connectionString', e.target.value)}
              placeholder={entry.detectedType === 'mongodb' ? 'mongodb+srv://user:pass@cluster/' : 'postgresql://user:pass@host:5432/db'}
              className="h-8 text-sm"
            />
          </div>

          <div className="space-y-1">
            <Label className="text-xs">Database</Label>
            <Input
              value={entry.database ?? ''}
              onChange={(e) => updateDatabaseField('database', e.target.value)}
              placeholder={entry.detectedType === 'mongodb' ? 'analytics' : 'public'}
              className="h-8 text-sm"
            />
          </div>

          {entry.detectedType === 'postgres' ? (
            <div className="space-y-1">
              <Label className="text-xs">Table</Label>
              <Input
                value={entry.table ?? ''}
                onChange={(e) => updateDatabaseField('table', e.target.value)}
                placeholder="events"
                className="h-8 text-sm"
              />
            </div>
          ) : (
            <div className="space-y-1">
              <Label className="text-xs">Collection</Label>
              <Input
                value={entry.mongoCollection ?? ''}
                onChange={(e) => updateDatabaseField('mongoCollection', e.target.value)}
                placeholder="events"
                className="h-8 text-sm"
              />
            </div>
          )}
        </div>
      )}

      {/* Hidden file input */}
      <input ref={fileInputRef} type="file" className="hidden" onChange={handleFileChange} />

      {/* Reference params */}
      {showRefParams && (
        <div>
          <button
            type="button"
            onClick={() => setRefOpen(!refOpen)}
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            {refOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            Reference fetching
          </button>

          {refOpen && (
            <div className="mt-2 pl-1 space-y-3 border-l-2 border-border ml-1 pl-3">
              <div className="flex items-center justify-between">
                <Label className="text-xs">Fetch references</Label>
                <Switch
                  checked={entry.refParams?.fetch_references ?? false}
                  onCheckedChange={(v) => updateRefParams({ fetch_references: v })}
                />
              </div>

              {entry.refParams?.fetch_references && (
                <>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1">
                      <Label className="text-xs">Depth (1–3)</Label>
                      <Input
                        type="number"
                        min={1}
                        max={3}
                        value={entry.refParams?.depth ?? 1}
                        onChange={(e) => updateRefParams({ depth: Math.min(3, Math.max(1, Number(e.target.value))) })}
                        className="h-7 text-xs"
                      />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-xs">Max refs (5–100)</Label>
                      <Input
                        type="number"
                        min={5}
                        max={100}
                        value={entry.refParams?.max_refs ?? 20}
                        onChange={(e) => updateRefParams({ max_refs: Math.min(100, Math.max(5, Number(e.target.value))) })}
                        className="h-7 text-xs"
                      />
                    </div>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
