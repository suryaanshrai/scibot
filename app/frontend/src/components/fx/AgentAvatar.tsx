import { lazy, Suspense } from 'react'
import type { BotAvatarState } from 'bot-avatars'
import { useFxPalette } from '@/lib/fxPalette'

// The largest of the effect libraries; keep it out of the main bundle.
const BotAvatar = lazy(() => import('bot-avatars').then((m) => ({ default: m.BotAvatar })))

/** SciBot's assistant: one bot, its body in the current accent colour. */
export function AgentAvatar({
  state = 'default',
  size = 28,
  className,
}: {
  state?: BotAvatarState
  size?: number
  className?: string
}) {
  const palette = useFxPalette()
  return (
    <Suspense fallback={<span aria-hidden className={className} style={{ display: 'block', width: size, height: size }} />}>
      <BotAvatar
        type="droid"
        state={state}
        size={size}
        color={palette.acc}
        shading="smooth"
        saturation={1}
        brightness={1.05}
        aria-label="SciBot"
        className={className}
      />
    </Suspense>
  )
}
