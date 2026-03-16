import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { StoreConfig, StoreProviderOption } from '@/types/config'

interface StoreSettingsProps {
  config: StoreConfig
  options: StoreProviderOption[]
  onChange: (updates: Partial<StoreConfig>) => void
}

const NEEDS_CONNECTION_STRING = ['chroma', 'pinecone', 'qdrant', 'milvus', 'mongodb', 'postgres']
const NEEDS_NAMESPACE = ['pinecone', 'qdrant', 'milvus', 'mongodb']

export function StoreSettings({ config, options, onChange }: StoreSettingsProps) {
  return (
    <div className="grid gap-3">
      <div className="space-y-1.5">
        <Label>Provider</Label>
        <Select value={config.provider} onValueChange={(v) => onChange({ provider: v })}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            {options.map((provider) => (
              <SelectItem key={provider.provider} value={provider.provider}>{provider.human_name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1.5">
        <Label>Collection name</Label>
        <Input
          value={config.collection_name}
          onChange={(e) => onChange({ collection_name: e.target.value })}
          placeholder="scibot"
        />
      </div>

      {NEEDS_NAMESPACE.includes(config.provider) && (
        <div className="space-y-1.5">
          <Label>Namespace <span className="text-muted-foreground">(optional)</span></Label>
          <Input
            value={config.namespace ?? ''}
            onChange={(e) => onChange({ namespace: e.target.value || undefined })}
          />
        </div>
      )}

      {NEEDS_CONNECTION_STRING.includes(config.provider) && (
        <div className="space-y-1.5">
          <Label>Connection string / API URL</Label>
          <Input
            value={config.connection_string ?? ''}
            onChange={(e) => onChange({ connection_string: e.target.value })}
            placeholder={
              config.provider === 'chroma'
                ? 'http://localhost:8000'
                : config.provider === 'postgres'
                ? 'postgresql://user:pass@host:5432/db'
                : config.provider === 'mongodb'
                ? 'mongodb+srv://...'
                : 'https://...'
            }
          />
        </div>
      )}
    </div>
  )
}
