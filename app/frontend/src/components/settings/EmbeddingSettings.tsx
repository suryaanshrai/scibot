import { Field, SelectInput } from '@/components/sb/primitives'
import { inputClass } from '@/components/sb/styles'
import type { EmbeddingConfig, EmbeddingProviderOption } from '@/types/config'

interface EmbeddingSettingsProps {
  config: EmbeddingConfig
  options: EmbeddingProviderOption[]
  onChange: (updates: Partial<EmbeddingConfig>) => void
}

export function EmbeddingSettings({ config, options, onChange }: EmbeddingSettingsProps) {
  const selectedProvider = options.find((provider) => provider.provider === config.provider)
  const hasListedModel = !!selectedProvider?.models.some((model) => model.id === config.model)

  return (
    <>
      <Field label="Provider">
        <SelectInput
          value={config.provider}
          onChange={(provider) => {
            const next = options.find((entry) => entry.provider === provider)
            onChange({ provider, model: next?.default_model ?? '', dimensions: undefined })
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
            placeholder={selectedProvider?.default_model || 'Embedding model id'}
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

      {selectedProvider?.supports_dimensions && (
        <Field label="Dimensions" optional>
          <input
            type="number"
            min={1}
            value={config.dimensions ?? ''}
            onChange={(e) => onChange({ dimensions: e.target.value ? Number(e.target.value) : undefined })}
            placeholder="Model default"
            className={inputClass}
          />
        </Field>
      )}
    </>
  )
}
