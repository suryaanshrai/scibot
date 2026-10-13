import { lazy, Suspense, useCallback } from 'react'
import type { MetalFxProps } from 'metal-fx'
import { useFxPalette } from '@/lib/fxPalette'
import { cn } from '@/lib/utils'

// WebGL and ~40 kB gzipped: load it beside the page, not in the main bundle.
const MetalFx = lazy(() => import('metal-fx').then((m) => ({ default: m.MetalFx })))

const RING_CSS_PX = 1.5
/** Room around the child for the ring, which is painted beneath it. */
const GAP_CSS_PX = 2

/**
 * A liquid-metal ring in a finish that sits with the current accent. The
 * shader is masked to a thin ring just outside the element, and host styles are
 * left alone (metal-fx would otherwise blank the child and paint its own
 * white/#272727 surface), so the button keeps its own accent or surface fill.
 */
export function Metal({ children, borderRadius, className, ...props }: Omit<MetalFxProps, 'theme' | 'preset' | 'mask' | 'glowMode'>) {
  const palette = useFxPalette()
  const ring = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, dpr: number) => {
      const line = RING_CSS_PX * dpr
      const radius = Math.min(borderRadius === undefined ? h / 2 : (borderRadius + GAP_CSS_PX) * dpr, h / 2, w / 2)
      ctx.lineWidth = line
      ctx.strokeStyle = '#fff'
      ctx.beginPath()
      ctx.roundRect(line / 2, line / 2, w - line, h - line, Math.max(radius - line / 2, 0))
      ctx.stroke()
    },
    [borderRadius]
  )
  return (
    <Suspense
      fallback={
        <span className={className} style={{ display: 'inline-flex', padding: GAP_CSS_PX }}>
          {children}
        </span>
      }
    >
      <MetalFx
        theme={palette.theme}
        preset={palette.accent === 'vermilion' ? 'gold' : 'silver'}
        strength={0.6}
        borderRadius={borderRadius === undefined ? undefined : borderRadius + GAP_CSS_PX}
        glowGain={0.6}
        mask={ring}
        glowMode="ring"
        normalizeHostStyles={false}
        className={cn('bg-transparent!', className)}
        style={{ padding: GAP_CSS_PX }}
        {...props}
      >
        {children}
      </MetalFx>
    </Suspense>
  )
}
