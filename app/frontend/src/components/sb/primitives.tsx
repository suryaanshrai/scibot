import type { ReactNode } from 'react'
import { ChevronDown, LoaderCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { inputClass } from './styles'

export function Spinner({ size = 14, className }: { size?: number; className?: string }) {
  return <LoaderCircle size={size} className={cn('sb-spin shrink-0 text-acc', className)} aria-hidden />
}

export function IconButton({
  label,
  onClick,
  active,
  className,
  children,
  disabled,
}: {
  label: string
  onClick?: () => void
  active?: boolean
  className?: string
  children: ReactNode
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      disabled={disabled}
      className={cn(
        'flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg border-0 bg-transparent text-ink2 transition-colors hover:bg-line hover:text-ink disabled:cursor-not-allowed disabled:opacity-50',
        active && 'bg-line',
        className
      )}
    >
      {children}
    </button>
  )
}

export interface SegmentOption<T extends string | number> {
  value: T
  label: ReactNode
  icon?: ReactNode
}

export function Segmented<T extends string | number>({
  options,
  value,
  onChange,
  size = 'md',
  className,
}: {
  options: SegmentOption<T>[]
  value: T
  onChange: (value: T) => void
  size?: 'sm' | 'md'
  className?: string
}) {
  return (
    <div className={cn('flex w-max gap-0.5 rounded-[10px] bg-bg1 p-[3px]', size === 'sm' && 'rounded-[9px]', className)}>
      {options.map((option) => {
        const on = option.value === value
        return (
          <button
            key={String(option.value)}
            type="button"
            onClick={() => onChange(option.value)}
            aria-pressed={on}
            className={cn(
              'flex cursor-pointer items-center gap-1.5 border-0 font-medium transition-colors',
              size === 'sm'
                ? 'h-6 min-w-[34px] justify-center rounded-[7px] px-2 font-mono text-[12px] font-semibold'
                : 'h-7 rounded-lg px-3 text-[12.5px]',
              on ? 'bg-surface text-ink shadow-[0_1px_2px_rgb(0_0_0/.08)]' : 'bg-transparent text-ink2 hover:text-ink'
            )}
          >
            {option.icon}
            {option.label}
          </button>
        )
      })}
    </div>
  )
}

export function UnderlineTabs<T extends string>({
  tabs,
  value,
  onChange,
  className,
  size = 'md',
}: {
  tabs: { value: T; label: ReactNode; count?: number }[]
  value: T
  onChange: (value: T) => void
  className?: string
  size?: 'md' | 'lg'
}) {
  return (
    <div className={cn('flex gap-[22px]', className)} role="tablist">
      {tabs.map((tab) => {
        const on = tab.value === value
        return (
          <button
            key={tab.value}
            type="button"
            role="tab"
            aria-selected={on}
            onClick={() => onChange(tab.value)}
            className={cn(
              '-mb-px flex cursor-pointer gap-1.5 border-0 border-b-2 border-solid bg-transparent px-0 font-semibold transition-colors',
              size === 'lg' ? 'pb-3 text-[14px]' : 'pb-[11px] text-[13px]',
              on ? 'border-ink text-ink' : 'border-transparent text-ink3 hover:text-ink2'
            )}
          >
            {tab.label}
            {tab.count !== undefined && <span className="font-mono text-[11.5px] font-medium text-ink3">{tab.count}</span>}
          </button>
        )
      })}
    </div>
  )
}

export function Field({
  label,
  optional,
  hint,
  error,
  children,
  className,
}: {
  label: ReactNode
  optional?: boolean
  hint?: ReactNode
  error?: string | null
  children: ReactNode
  className?: string
}) {
  return (
    <label className={cn('flex flex-col gap-2 text-[13px] font-semibold', className)}>
      <span>
        {label}
        {optional && <span className="font-normal text-ink3"> (optional)</span>}
      </span>
      {children}
      {error ? (
        <span className="text-[12px] font-medium text-warn">{error}</span>
      ) : hint ? (
        <span className="text-[12px] font-normal text-ink3">{hint}</span>
      ) : null}
    </label>
  )
}

export function SelectInput({
  value,
  onChange,
  options,
  disabled,
  className,
  placeholder,
}: {
  value: string
  onChange: (value: string) => void
  options: { value: string; label: string }[]
  disabled?: boolean
  className?: string
  placeholder?: string
}) {
  const missing = !options.some((o) => o.value === value)
  return (
    <span className="relative block">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className={cn(inputClass, 'cursor-pointer appearance-none pr-[34px]', className)}
      >
        {missing && <option value={value}>{placeholder ?? (value || 'Select…')}</option>}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <ChevronDown size={14} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-ink3" />
    </span>
  )
}

export function Toggle({ on, onChange, label }: { on: boolean; onChange: (on: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={() => onChange(!on)}
      className="flex cursor-pointer items-center gap-[9px] border-0 bg-transparent p-0 text-[12.5px] font-medium whitespace-nowrap text-ink2"
    >
      {label}
      <span className={cn('relative h-[18px] w-[30px] rounded-full transition-colors duration-200', on ? 'bg-acc' : 'bg-line2')}>
        <span
          className={cn(
            'absolute left-0.5 top-0.5 h-3.5 w-3.5 rounded-full bg-white shadow-[0_1px_2px_rgb(0_0_0/.25)] transition-transform duration-300 ease-[cubic-bezier(.16,1,.3,1)]',
            on && 'translate-x-3'
          )}
        />
      </span>
    </button>
  )
}

export function RefChip({
  n,
  active,
  onEnter,
  onLeave,
  onClick,
}: {
  n: number
  active?: boolean
  onEnter?: () => void
  onLeave?: () => void
  onClick?: () => void
}) {
  return (
    <button
      type="button"
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
      onFocus={onEnter}
      onBlur={onLeave}
      onClick={onClick}
      aria-label={`Source ${n}`}
      className={cn(
        'mr-[1px] ml-[3px] inline-flex h-[17px] min-w-[19px] cursor-pointer items-center justify-center rounded-[5px] border-0 px-1 align-[3px] font-mono text-[10.5px] font-semibold leading-none transition-colors duration-200',
        active ? 'bg-acc text-accink' : 'bg-accsoft text-acc'
      )}
    >
      {n}
    </button>
  )
}

export function ModelPill({ label, onClick, className }: { label: string; onClick?: () => void; className?: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title="Model for this chat"
      className={cn(
        'flex h-7 max-w-[240px] shrink-0 cursor-pointer items-center gap-[7px] rounded-full border border-line2 bg-transparent px-[11px] font-mono text-[11.5px] font-medium whitespace-nowrap text-ink2 transition-colors hover:border-ink3 hover:text-ink',
        className
      )}
    >
      <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-ok" />
      <span className="truncate">{label}</span>
    </button>
  )
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn('font-serif font-medium tracking-[-0.025em]', className)}>
      Sci<em className="font-normal">Bot</em>
    </span>
  )
}
