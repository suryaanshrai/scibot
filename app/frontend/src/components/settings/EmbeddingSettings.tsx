import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
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
    <div className="grid gap-3">
      <div className="space-y-1.5">
        <Label>Provider</Label>
        <Select
          value={config.provider}
          onValueChange={(provider) => {
            const next = options.find((entry) => entry.provider === provider)
            onChange({ provider, model: next?.default_model ?? '', dimensions: undefined })
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
            placeholder={selectedProvider?.default_model || 'Embedding model id'}
          />
        )}
      </div>

      <div className="space-y-1.5">
        <Label>API Key</Label>
        <Input
          type="password"
          value={config.api_key ?? ''}
          onChange={(e) => onChange({ api_key: e.target.value || undefined })}
          placeholder="Leave blank to use env variable"
        />
      </div>

      {selectedProvider?.supports_dimensions && (
        <div className="space-y-1.5">
          <Label>Dimensions <span className="text-muted-foreground">(optional)</span></Label>
          <Input
            type="number"
            value={config.dimensions ?? ''}
            onChange={(e) => onChange({ dimensions: e.target.value ? Number(e.target.value) : undefined })}
            placeholder="Model default"
            min={1}
          />
        </div>
      )}
    </div>
  )
}
