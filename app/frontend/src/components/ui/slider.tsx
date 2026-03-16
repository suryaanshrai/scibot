import { cn } from '@/lib/utils'

interface SliderProps {
  min?: number
  max?: number
  step?: number
  value: number
  onChange: (value: number) => void
  className?: string
}

export function Slider({ min = 0, max = 100, step = 1, value, onChange, className }: SliderProps) {
  return (
    <input
      type="range"
      min={min}
      max={max}
      step={step}
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      className={cn(
        'w-full h-2 rounded-lg appearance-none cursor-pointer accent-primary bg-secondary',
        className
      )}
    />
  )
}
