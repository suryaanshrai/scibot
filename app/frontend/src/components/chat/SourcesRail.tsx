import { useEffect, useMemo, useState } from 'react'
import { LibraryBig, Plus, X } from 'lucide-react'
import { Spinner, UnderlineTabs } from '@/components/sb/primitives'
import { primaryButtonClass } from '@/components/sb/styles'
import { SourceStager } from '@/components/sources/SourceStager'
import { sourceDocLabel } from '@/lib/answer'
import { collectionGroups } from '@/lib/collectionView'
import { SOURCE_ICONS } from '@/lib/sourceMeta'
import { cn } from '@/lib/utils'
import type { SourceRecord } from '@/types/chat'
import type { CollectionDetail } from '@/types/collections'
import type { SourceEntry } from '@/types/sources'

export type RailTab = 'cited' | 'collection'

interface SourcesRailProps {
  tab: RailTab
  onTab: (tab: RailTab) => void
  cited: SourceRecord[]
  hoverRef: number | null
  onHoverRef: (ref: number | null) => void
  collectionName: string | null
  collection: CollectionDetail | null
  collectionLoading: boolean
  collectionError: string | null
  ingesting: boolean
  addError: string | null
  /** Stage sources and add them to this chat's collection. */
  onAddSources: (sources: SourceEntry[]) => Promise<boolean>
  addOpen: boolean
  onAddOpen: (open: boolean) => void
  overlay: boolean
  onClose: () => void
}

export function SourcesRail({
  tab,
  onTab,
  cited,
  hoverRef,
  onHoverRef,
  collectionName,
  collection,
  collectionLoading,
  collectionError,
  ingesting,
  addError,
  onAddSources,
  addOpen,
  onAddOpen,
  overlay,
  onClose,
}: SourcesRailProps) {
  const [staged, setStaged] = useState<SourceEntry[]>([])
  const groups = useMemo(() => collectionGroups(collection), [collection])
  const collCount = groups.reduce((n, g) => n + g.items.length, 0)

  // Scroll the hovered excerpt into view when a citation chip is hovered.
  useEffect(() => {
    if (hoverRef === null || tab !== 'cited') return
    document.getElementById(`cited-${hoverRef}`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [hoverRef, tab])

  const submit = async () => {
    if (!staged.length) return
    const ok = await onAddSources(staged)
    if (ok) setStaged([])
  }

  return (
    <>
      {overlay && <div className="fixed inset-0 z-30 bg-[rgb(0_0_0/.25)]" onClick={onClose} aria-hidden />}
      <aside
        className={cn(
          'flex min-h-0 w-[344px] flex-none flex-col border-l border-line bg-bg1',
          overlay && 'fixed top-0 right-0 bottom-0 z-40 max-w-[92vw] shadow-sb'
        )}
      >
        <div className="flex flex-col gap-3.5 border-b border-line px-[18px] pt-4">
          <div className="flex items-baseline justify-between gap-3">
            <span className="font-serif text-[21px] font-medium tracking-[-0.015em]">Sources</span>
            <span className="flex min-w-0 items-center gap-1">
              <span className="truncate font-mono text-[11px] font-medium whitespace-nowrap text-ink3">
                {collectionName ?? 'No collection attached'}
              </span>
              {overlay && (
                <button
                  type="button"
                  onClick={onClose}
                  aria-label="Close sources"
                  className="ml-1 flex h-7 w-7 cursor-pointer items-center justify-center self-center rounded-md border-0 bg-transparent text-ink3 hover:bg-line"
                >
                  <X size={14} />
                </button>
              )}
            </span>
          </div>
          <UnderlineTabs
            value={tab}
            onChange={onTab}
            tabs={[
              { value: 'cited', label: 'Cited', count: cited.length },
              { value: 'collection', label: 'Collection', count: collCount },
            ]}
          />
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-2 pt-2 pb-5">
          {tab === 'cited' && (
            <>
              {cited.map((s) => {
                const on = hoverRef === s.ref_id
                return (
                  <div
                    key={s.ref_id}
                    id={`cited-${s.ref_id}`}
                    onMouseEnter={() => onHoverRef(s.ref_id)}
                    onMouseLeave={() => onHoverRef(null)}
                    className="grid grid-cols-[28px_minmax(0,1fr)] gap-2.5 rounded-[10px] px-2.5 py-3 transition-colors duration-200"
                    style={{ background: on ? 'var(--surface)' : 'transparent' }}
                  >
                    <span
                      className="flex h-[22px] items-center justify-center rounded-md font-mono text-[11px] font-semibold transition-colors duration-200"
                      style={{ background: on ? 'var(--acc)' : 'var(--surface)', color: on ? 'var(--accink)' : 'var(--ink2)' }}
                    >
                      {s.ref_id}
                    </span>
                    <div className="min-w-0">
                      <div className="flex items-baseline justify-between gap-2.5">
                        <span className="text-[13px] leading-[1.35] font-semibold">{s.title || 'Untitled excerpt'}</span>
                        {typeof s.relevance_score === 'number' && (
                          <span className="font-mono text-[11px] font-medium text-ink3 tabular-nums">{s.relevance_score.toFixed(2)}</span>
                        )}
                      </div>
                      {s.snippet && (
                        <p className="mt-[5px] mb-0 line-clamp-5 font-serif text-[14px] leading-normal text-ink2">{s.snippet}</p>
                      )}
                      {s.url ? (
                        <a
                          href={s.url}
                          target="_blank"
                          rel="noreferrer"
                          className="mt-1.5 block truncate text-[11.5px] text-ink3 no-underline hover:text-acc"
                        >
                          {sourceDocLabel(s)}
                        </a>
                      ) : (
                        <p className="mt-1.5 mb-0 truncate text-[11.5px] text-ink3">{sourceDocLabel(s)}</p>
                      )}
                    </div>
                  </div>
                )
              })}
              {cited.length === 0 && (
                <p className="mx-2.5 my-3 text-[13px] leading-normal text-ink3">
                  Excerpts cited in the latest answer appear here, with their relevance scores.
                </p>
              )}
            </>
          )}

          {tab === 'collection' && (
            <>
              {ingesting && (
                <div className="mx-2.5 mt-2 mb-1 flex items-center gap-2.5 rounded-[10px] border border-line bg-surface px-3 py-2.5 text-[12.5px] text-ink2">
                  <Spinner />
                  Ingesting sources…
                </div>
              )}
              {collectionLoading && !ingesting && (
                <div className="mx-2.5 mt-2 flex items-center gap-2.5 text-[12.5px] text-ink3">
                  <Spinner /> Loading collection…
                </div>
              )}
              {collectionError && <p className="mx-2.5 my-3 text-[12.5px] text-warn">{collectionError}</p>}

              {groups.map((g) => {
                const Icon = SOURCE_ICONS[g.sourceType]
                return (
                  <div key={g.key}>
                    <div className="flex items-center gap-2 px-2.5 pt-3.5 pb-1 text-[12px] font-semibold text-ink2">
                      <Icon size={14} />
                      {g.label}
                      <span className="ml-auto font-mono text-[11px] font-medium text-ink3">{g.items.length}</span>
                    </div>
                    {g.items.map((it) =>
                      it.href ? (
                        <a
                          key={it.id}
                          href={it.href}
                          target="_blank"
                          rel="noreferrer"
                          className="block rounded-[10px] px-2.5 py-[9px] text-ink no-underline hover:bg-line"
                        >
                          <span className="block text-[13px] leading-[1.4] font-medium break-words">{it.label}</span>
                          {it.description && <span className="mt-[3px] block text-[11.5px] leading-[1.45] text-ink3">{it.description}</span>}
                        </a>
                      ) : (
                        <div key={it.id} className="rounded-[10px] px-2.5 py-[9px]">
                          <span className="block text-[13px] leading-[1.4] font-medium break-words">{it.label}</span>
                          {it.description && <span className="mt-[3px] block text-[11.5px] leading-[1.45] text-ink3">{it.description}</span>}
                        </div>
                      )
                    )}
                  </div>
                )
              })}

              {!collectionLoading && !ingesting && groups.length === 0 && !addOpen && (
                <p className="mx-2.5 my-3 text-[13px] leading-normal text-ink3">This chat does not have a collection attached yet.</p>
              )}

              <div className="mx-1 mt-3">
                {addOpen ? (
                  <div className="overflow-hidden rounded-[14px] border border-line2 bg-surface">
                    <SourceStager sources={staged} onChange={setStaged} compact />
                    <div className="flex items-center justify-between gap-2 border-t border-line px-4 py-3">
                      <button
                        type="button"
                        onClick={() => {
                          setStaged([])
                          onAddOpen(false)
                        }}
                        className="cursor-pointer border-0 bg-transparent p-0 text-[13px] font-medium text-ink2 underline decoration-line2 underline-offset-4 hover:text-ink"
                      >
                        Cancel
                      </button>
                      <button type="button" onClick={() => void submit()} disabled={!staged.length || ingesting} className={primaryButtonClass}>
                        {ingesting && <Spinner className="text-accink" />}
                        Add to chat
                      </button>
                    </div>
                    {addError && <p className="m-0 px-4 pb-3 text-[12.5px] text-warn">{addError}</p>}
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => onAddOpen(true)}
                    disabled={ingesting}
                    className="flex h-9 w-full cursor-pointer items-center justify-center gap-2 rounded-[10px] border border-dashed border-line2 bg-transparent text-[13px] font-medium text-ink2 hover:border-acc hover:text-ink disabled:opacity-60"
                  >
                    {groups.length ? <Plus size={14} /> : <LibraryBig size={14} />}
                    Add sources
                  </button>
                )}
              </div>
            </>
          )}
        </div>
      </aside>
    </>
  )
}
