import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Slider } from '@/components/ui/slider'
import type { LLMConfig, LLMProviderOption } from '@/types/config'

interface LLMSettingsProps {
  config: LLMConfig
  options: LLMProviderOption[]
  onChange: (updates: Partial<LLMConfig>) => void
  isOverride?: boolean
}

export function LLMSettings({ config, options, onChange, isOverride }: LLMSettingsProps) {
  const selectedProvider = options.find((provider) => provider.provider === config.provider)
  const hasListedModel = !!selectedProvider?.models.some((model) => model.id === config.model)
  const temperature = config.temperature ?? 0.7

  return (
    <div className="space-y-4">
      {isOverride && (
        <p className="text-xs text-muted-foreground bg-muted rounded px-2 py-1">
          Overrides global default for this chat only.
        </p>
      )}

      <div className="grid gap-3">
        <div className="space-y-1.5">
          <Label>Provider</Label>
          <Select
            value={config.provider}
            onValueChange={(provider) => {
              const next = options.find((entry) => entry.provider === provider)
              onChange({ provider, model: next?.default_model ?? '' })
            }}
          >
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              {options.map((provider) => (
                <SelectItem key={provider.provider} value={provider.provider}>{provider.human_name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label>Model</Label>
          {selectedProvider && hasListedModel ? (
            <Select value={config.model} onValueChange={(model) => onChange({ model })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {selectedProvider.models.map((model) => (
                  <SelectItem key={model.id} value={model.id}>{model.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (
            <Input
              value={config.model}
              onChange={(e) => onChange({ model: e.target.value })}
              placeholder={selectedProvider?.default_model || 'Model id'}
            />
          )}
        </div>

        <div className="space-y-1.5">
          <Label>API Key</Label>
          <Input
            type="password"
            value={config.api_key ?? ''}
            onChange={(e) => onChange({ api_key: e.target.value })}
            placeholder="Leave blank to use env variable"
          />
        </div>

        <div className="space-y-2">
          <div className="flex justify-between">
            <Label>Temperature</Label>
            <span className="text-sm tabular-nums text-muted-foreground">{temperature.toFixed(1)}</span>
          </div>
          <Slider
            min={0}
            max={2}
            step={0.1}
            value={temperature}
            onChange={(v) => onChange({ temperature: v })}
          />
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>Precise</span>
            <span>Creative</span>
          </div>
        </div>

        <div className="space-y-1.5">
          <Label>Max tokens <span className="text-muted-foreground">(optional)</span></Label>
          <Input
            type="number"
            value={config.max_tokens ?? ''}
            onChange={(e) => onChange({ max_tokens: e.target.value ? Number(e.target.value) : undefined })}
            placeholder="Model default"
            min={1}
          />
        </div>
      </div>
    </div>
  )
}
