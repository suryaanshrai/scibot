import { BorderBeam } from 'border-beam'
import type { BorderBeamColorVariant, BorderBeamProps } from 'border-beam'
import { useFxPalette, useReducedMotion } from '@/lib/fxPalette'
import type { Accent } from '@/stores/themeStore'

/** border-beam's built-in palettes closest to each SciBot accent. */
const ACCENT_VARIANT: Record<Accent, BorderBeamColorVariant> = {
  cobalt: 'ocean',
  teal: 'ice',
  vermilion: 'sunset',
}

type BeamProps = Omit<BorderBeamProps, 'theme' | 'colorVariant'> & {
  /** `warn` uses the amber beam that matches --warn. */
  tone?: 'accent' | 'warn'
}

/**
 * A border beam toned down to SciBot's palette and the in-app theme.
 * The wrapper clips its child (overflow: hidden), so put the child's
 * box-shadow and outer margins on the Beam rather than the child.
 */
export function Beam({ tone = 'accent', active = true, children, ...props }: BeamProps) {
  const palette = useFxPalette()
  const reducedMotion = useReducedMotion()
  return (
    <BorderBeam
      theme={palette.theme}
      colorVariant={tone === 'warn' ? 'sunset' : ACCENT_VARIANT[palette.accent]}
      staticColors
      hueRange={0}
      saturation={0.9}
      glowSize={0.8}
      strength={palette.theme === 'dark' ? 0.6 : 0.8}
      {...props}
      active={active && !reducedMotion}
    >
      {children}
    </BorderBeam>
  )
}
