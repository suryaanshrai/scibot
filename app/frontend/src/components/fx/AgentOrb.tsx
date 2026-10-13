import { ThinkingOrb } from 'thinking-orbs'
import type { OrbState } from 'thinking-orbs'
import { useFxPalette } from '@/lib/fxPalette'
import { cn } from '@/lib/utils'

export type OrbTone = 'ink' | 'warn' | 'muted'

/**
 * A thinking-orb inked in the theme's own colours. The orb shades its dots
 * toward the background, so a mid-tone like the accent washes out; ink keeps
 * it as legible as the status text beside it.
 */
export function AgentOrb({
  state = 'working',
  size = 20,
  tone = 'ink',
  className,
}: {
  state?: OrbState
  size?: 20 | 32 | 64
  tone?: OrbTone
  className?: string
}) {
  const palette = useFxPalette()
  const color = tone === 'warn' ? palette.warn : tone === 'muted' ? palette.ink3 : palette.ink
  return (
    <ThinkingOrb
      state={state}
      size={size}
      theme={palette.theme}
      color={color}
      dotSize={size === 20 ? 1.35 : 1}
      // 20px orbs stand in for 14px icons; keep the row height unchanged.
      className={cn('flex-none', size === 20 && '-my-[3px]', className)}
    />
  )
}
