import { useRef, useState } from 'react'
import type { DragEvent, FormEvent } from 'react'
import { ChevronDown, Database, Link2, Upload, X } from 'lucide-react'
import { Field, Segmented, Toggle } from '@/components/sb/primitives'
import { monoInputClass } from '@/components/sb/styles'
import { detectFile, detectUrl } from '@/lib/sourceDetector'
import { SOURCE_ICONS, SOURCE_LABELS, UPLOADABLE_TYPES, UPLOAD_ACCEPT, formatBytes } from '@/lib/sourceMeta'
import { cn, generateId } from '@/lib/utils'
import { DEFAULT_REF_PARAMS, REF_PARAM_TYPES } from '@/types/sources'
import type { SourceEntry } from '@/types/sources'

const MAX_SOURCES = 50

type Mode = 'url' | 'file' | 'data'
type DataType = 'mongodb' | 'postgres'

interface SourceStagerProps {
  sources: SourceEntry[]
  onChange: (sources: SourceEntry[]) => void
  /** Narrow layout for the sources rail. */
  compact?: boolean
}

function describe(source: SourceEntry) {
  const kind = SOURCE_LABELS[source.detectedType]
  if (source.inputType === 'file' && source.file) return `${kind} · Local file · ${formatBytes(source.file.size)}`
  if (source.inputType === 'database') return `${kind} · ${[source.database, source.connectionString].filter(Boolean).join(' · ')}`
  return `${kind} · ${source.url ?? ''}`
}

function StagedRow({
  source,
  onUpdate,
  onRemove,
}: {
  source: SourceEntry
  onUpdate: (next: SourceEntry) => void
  onRemove: () => void
}) {
  const Icon = SOURCE_ICONS[source.detectedType]
  const canRefs = source.inputType === 'url' && REF_PARAM_TYPES.includes(source.detectedType)
  const refs = source.refParams ?? DEFAULT_REF_PARAMS
  const unsupported = source.inputType === 'file' && !UPLOADABLE_TYPES.includes(source.detectedType)
  const setRefs = (patch: Partial<typeof refs>) => onUpdate({ ...source, refParams: { ...refs, ...patch } })

  return (
    <div className="flex flex-col gap-3 border-b border-line px-4 py-3.5 last:border-b-0">
      <div className="flex flex-wrap items-center gap-3">
        <span className="flex h-[34px] w-[34px] flex-none items-center justify-center rounded-[9px] bg-bg1 text-ink2">
          <Icon size={16} />
        </span>
        <div className="min-w-0 flex-1 basis-40">
          <div className="truncate font-mono text-[13px] font-semibold">{source.previewMeta?.label ?? source.url ?? source.fileName}</div>
          <div className={cn('mt-0.5 truncate text-[12px]', unsupported ? 'text-warn' : 'text-ink3')}>
            {unsupported ? 'This file type can’t be uploaded yet' : describe(source)}
          </div>
        </div>
        {canRefs && <Toggle label="Fetch references" on={refs.fetch_references} onChange={(on) => setRefs({ fetch_references: on })} />}
        <button
          type="button"
          onClick={onRemove}
          aria-label="Remove source"
          className="flex h-[30px] w-[30px] flex-none cursor-pointer items-center justify-center rounded-lg border-0 bg-transparent text-ink3 hover:bg-line hover:text-ink"
        >
          <X size={14} />
        </button>
      </div>
      {canRefs && refs.fetch_references && (
        <>
          <div className="ml-[46px] grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-6 gap-y-3 text-[12.5px] text-ink2">
            <span>Depth</span>
            <Segmented
              size="sm"
              value={refs.depth}
              onChange={(depth) => setRefs({ depth })}
              options={[1, 2, 3].map((n) => ({ value: n, label: String(n) }))}
            />
            <span>Max references</span>
            <div className="flex items-center gap-3">
              <input
                type="range"
                min={5}
                max={100}
                step={5}
                value={refs.max_refs}
                onChange={(e) => setRefs({ max_refs: Number(e.target.value) })}
                className="min-w-0 flex-1"
                aria-label="Max references"
              />
              <span className="w-7 text-right font-mono text-[12px] font-medium text-ink">{refs.max_refs}</span>
            </div>
          </div>
          <p className="m-0 ml-[46px] text-[12px] leading-normal text-ink3">
            Recursively fetches references via Semantic Scholar up to this depth, then keeps the most-cited.
          </p>
        </>
      )}
    </div>
  )
}

export function SourceStager({ sources, onChange, compact }: SourceStagerProps) {
  const [mode, setMode] = useState<Mode>('url')
  const [urlDraft, setUrlDraft] = useState('')
  const [dataType, setDataType] = useState<DataType>('mongodb')
  const [conn, setConn] = useState('')
  const [db, setDb] = useState('')
  const [coll, setColl] = useState('')
  const [dragging, setDragging] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const full = sources.length >= MAX_SOURCES
  const trimmed = urlDraft.trim()
  const detected = trimmed ? detectUrl(/^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`) : null
  const DetectedIcon = detected ? SOURCE_ICONS[detected.type] : null

  const add = (entries: SourceEntry[]) => onChange([...sources, ...entries].slice(0, MAX_SOURCES))

  const addUrl = (e: FormEvent) => {
    e.preventDefault()
    if (!detected || full) return
    const url = /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`
    add([
      {
        id: generateId(),
        inputType: 'url',
        url,
        detectedType: detected.type,
        previewMeta: detected.preview.label === 'YouTube video' ? { ...detected.preview, label: url.replace(/^https?:\/\//, '') } : detected.preview,
        refParams: REF_PARAM_TYPES.includes(detected.type) ? { ...DEFAULT_REF_PARAMS } : undefined,
      },
    ])
    setUrlDraft('')
  }

  const addFiles = (files: FileList | File[]) => {
    const entries = Array.from(files).map((file) => {
      const { type, preview } = detectFile(file)
      return { id: generateId(), inputType: 'file' as const, file, fileName: file.name, detectedType: type, previewMeta: preview }
    })
    if (entries.length) add(entries)
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files)
  }

  const addData = () => {
    if (!conn.trim() || full) return
    add([
      {
        id: generateId(),
        inputType: 'database',
        detectedType: dataType,
        connectionString: conn.trim(),
        database: db.trim() || undefined,
        ...(dataType === 'mongodb' ? { mongoCollection: coll.trim() || undefined } : { table: coll.trim() || undefined }),
        previewMeta: { label: coll.trim() || db.trim() || (dataType === 'mongodb' ? 'MongoDB' : 'PostgreSQL') },
      },
    ])
    setColl('')
  }

  return (
    <div>
      <div className="flex flex-col gap-3 p-4">
        <div className="flex items-center justify-between gap-3">
          <Segmented
            value={mode}
            onChange={setMode}
            options={[
              { value: 'url', label: 'URL', icon: <Link2 size={13} /> },
              { value: 'file', label: 'File', icon: <Upload size={13} /> },
              { value: 'data', label: 'Data', icon: <Database size={13} /> },
            ]}
          />
          <span className="font-mono text-[11.5px] font-medium text-ink3">
            {sources.length} / {MAX_SOURCES}
          </span>
        </div>

        {mode === 'url' && (
          <>
            <form onSubmit={addUrl} className="flex gap-2">
              <input
                value={urlDraft}
                onChange={(e) => setUrlDraft(e.target.value)}
                placeholder={compact ? 'Paste a URL' : 'Paste an arXiv, PubMed, YouTube, GitHub or web URL'}
                className="h-[42px] min-w-0 flex-1 rounded-[10px] border border-line2 bg-bg px-3 text-[14px] text-ink outline-none focus:border-ink3"
              />
              <button
                type="submit"
                disabled={!detected || full}
                className="h-[42px] cursor-pointer rounded-[10px] border border-line2 bg-surface px-4 text-[13px] font-semibold text-ink hover:border-ink3 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Add
              </button>
            </form>
            {detected && DetectedIcon && (
              <p className="m-0 flex min-w-0 items-center gap-[7px] text-[12.5px] text-ink2">
                <DetectedIcon size={14} className="flex-none" />
                <span className="flex-none">Detected {SOURCE_LABELS[detected.type]}</span>
                <span className="truncate font-mono text-[12px] text-ink">{detected.preview.label}</span>
              </p>
            )}
          </>
        )}

        {mode === 'file' && (
          <>
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              onDragOver={(e) => {
                e.preventDefault()
                setDragging(true)
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              disabled={full}
              className={cn(
                'flex h-28 cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border border-dashed bg-bg px-4 text-center text-[13px] text-ink2 transition-colors hover:border-acc hover:text-ink',
                dragging ? 'border-acc text-ink' : 'border-line2'
              )}
            >
              <Upload size={18} />
              <span>
                Drop PDF, LaTeX, Markdown, CSV or JSON files, or <span className="font-semibold text-acc">browse</span>
              </span>
            </button>
            <input
              ref={fileRef}
              type="file"
              multiple
              accept={UPLOAD_ACCEPT}
              className="hidden"
              onChange={(e) => {
                if (e.target.files) addFiles(e.target.files)
                e.target.value = ''
              }}
            />
          </>
        )}

        {mode === 'data' && (
          <>
            <div className={cn('grid gap-3', compact ? 'grid-cols-1' : 'grid-cols-1 sm:grid-cols-2')}>
              <Field label="Source type" className="text-[12.5px]">
                <span className="relative block">
                  <select
                    value={dataType}
                    onChange={(e) => setDataType(e.target.value as DataType)}
                    className="h-10 w-full cursor-pointer appearance-none rounded-[10px] border border-line2 bg-bg pr-[34px] pl-3 text-[14px] text-ink outline-none"
                  >
                    <option value="mongodb">MongoDB</option>
                    <option value="postgres">PostgreSQL</option>
                  </select>
                  <ChevronDown size={14} className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-ink3" />
                </span>
              </Field>
              <Field label="Connection string" className="text-[12.5px]">
                <input
                  value={conn}
                  onChange={(e) => setConn(e.target.value)}
                  placeholder={dataType === 'mongodb' ? 'mongodb://host:27017' : 'postgresql://user:pass@host:5432/db'}
                  className={monoInputClass}
                />
              </Field>
              <Field label="Database" className="text-[12.5px]">
                <input value={db} onChange={(e) => setDb(e.target.value)} className={monoInputClass} />
              </Field>
              <Field label={dataType === 'mongodb' ? 'Collection' : 'Table'} className="text-[12.5px]">
                <input value={coll} onChange={(e) => setColl(e.target.value)} className={monoInputClass} />
              </Field>
            </div>
            <div className="flex justify-end">
              <button
                type="button"
                onClick={addData}
                disabled={!conn.trim() || full}
                className="h-9 cursor-pointer rounded-[10px] border border-line2 bg-surface px-3.5 text-[13px] font-semibold text-ink hover:border-ink3 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Add data source
              </button>
            </div>
          </>
        )}
      </div>

      {sources.length > 0 && (
        <div className="border-t border-line">
          {sources.map((source) => (
            <StagedRow
              key={source.id}
              source={source}
              onUpdate={(next) => onChange(sources.map((s) => (s.id === source.id ? next : s)))}
              onRemove={() => onChange(sources.filter((s) => s.id !== source.id))}
            />
          ))}
        </div>
      )}
    </div>
  )
}
