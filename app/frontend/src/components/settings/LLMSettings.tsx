import { Field, SelectInput } from '@/components/sb/primitives'
import { inputClass } from '@/components/sb/styles'
import type { LLMConfig, LLMProviderOption } from '@/types/config'

interface LLMSettingsProps {
  config: LLMConfig
  options: LLMProviderOption[]
  onChange: (updates: Partial<LLMConfig>) => void
}

export function LLMSettings({ config, options, onChange }: LLMSettingsProps) {
  const selectedProvider = options.find((provider) => provider.provider === config.provider)
  const hasListedModel = !!selectedProvider?.models.some((model) => model.id === config.model)
  const temperature = config.temperature ?? 0.7

  return (
    <>
      <Field label="Provider">
        <SelectInput
          value={config.provider}
          onChange={(provider) => {
            const next = options.find((entry) => entry.provider === provider)
            onChange({ provider, model: next?.default_model ?? '' })
          }}
          options={options.map((p) => ({ value: p.provider, label: p.human_name }))}
        />
      </Field>

      <Field label="Model">
        {selectedProvider && (hasListedModel || !config.model) && selectedProvider.models.length > 0 ? (
          <SelectInput
            value={config.model}
            onChange={(model) => onChange({ model })}
            options={selectedProvider.models.map((m) => ({ value: m.id, label: m.name }))}
          />
        ) : (
          <input
            value={config.model}
            onChange={(e) => onChange({ model: e.target.value })}
            placeholder={selectedProvider?.default_model || 'Model id'}
            className={inputClass}
          />
        )}
      </Field>

      <Field label="API key">
        <input
          type="password"
          value={config.api_key ?? ''}
          onChange={(e) => onChange({ api_key: e.target.value || undefined })}
          placeholder="Leave blank to use env variable"
          autoComplete="off"
          className={inputClass}
        />
      </Field>

      <div className="flex flex-col gap-2.5">
        <div className="flex justify-between text-[13px] font-semibold">
          Temperature
          <span className="font-mono text-[13px] font-medium text-ink2">{temperature.toFixed(1)}</span>
        </div>
        <input
          type="range"
          min={0}
          max={2}
          step={0.1}
          value={temperature}
          onChange={(e) => onChange({ temperature: Number(e.target.value) })}
          className="w-full"
          aria-label="Temperature"
        />
        <div className="flex justify-between text-[12px] text-ink3">
          <span>Precise</span>
          <span>Creative</span>
        </div>
      </div>

      <Field label="Max tokens" optional>
        <input
          type="number"
          min={1}
          value={config.max_tokens ?? ''}
          onChange={(e) => onChange({ max_tokens: e.target.value ? Number(e.target.value) : undefined })}
          placeholder="Model default"
          className={inputClass}
        />
      </Field>
    </>
  )
}
