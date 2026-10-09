import { Field, SelectInput } from '@/components/sb/primitives'
import { inputClass } from '@/components/sb/styles'
import type { StoreConfig, StoreProviderOption } from '@/types/config'

interface StoreSettingsProps {
  config: StoreConfig
  options: StoreProviderOption[]
  onChange: (updates: Partial<StoreConfig>) => void
}

const NEEDS_CONNECTION_STRING = ['chroma', 'pinecone', 'qdrant', 'milvus', 'mongodb', 'postgres']
const NEEDS_NAMESPACE = ['pinecone', 'qdrant', 'milvus', 'mongodb']

const PLACEHOLDERS: Record<string, string> = {
  chroma: 'http://localhost:8000',
  postgres: 'Leave blank to use the bundled Postgres',
  mongodb: 'mongodb+srv://…',
}

export function StoreSettings({ config, options, onChange }: StoreSettingsProps) {
  const selected = options.find((o) => o.provider === config.provider)

  return (
    <>
      <Field
        label="Vector store"
        hint={selected?.description || 'Non-analytical data is stored here with rich metadata for retrieval.'}
      >
        <SelectInput
          value={config.provider}
          onChange={(provider) => onChange({ provider })}
          options={options.map((p) => ({ value: p.provider, label: p.human_name }))}
        />
      </Field>

      <Field label="Collection name">
        <input
          value={config.collection_name}
          onChange={(e) => onChange({ collection_name: e.target.value })}
          placeholder="scibot"
          className={inputClass}
        />
      </Field>

      {NEEDS_NAMESPACE.includes(config.provider) && (
        <Field label="Namespace" optional>
          <input
            value={config.namespace ?? ''}
            onChange={(e) => onChange({ namespace: e.target.value || undefined })}
            className={inputClass}
          />
        </Field>
      )}

      {NEEDS_CONNECTION_STRING.includes(config.provider) && (
        <Field label="Connection string / API URL" optional={config.provider === 'postgres'}>
          <input
            value={config.connection_string ?? ''}
            onChange={(e) => onChange({ connection_string: e.target.value || undefined })}
            placeholder={PLACEHOLDERS[config.provider] ?? 'https://…'}
            className={`${inputClass} font-mono text-[13px]`}
          />
        </Field>
      )}
    </>
  )
}
