import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import type { ExternalKeys } from '@/types/config'

interface APIKeysSettingsProps {
  keys: ExternalKeys
  onChange: (updates: Partial<ExternalKeys>) => void
}

const KEY_FIELDS: { key: keyof ExternalKeys; label: string; placeholder?: string }[] = [
  { key: 'SEMANTIC_SCHOLAR_API_KEY', label: 'Semantic Scholar API Key', placeholder: 'Optional — increases rate limit' },
  { key: 'NCBI_API_KEY', label: 'NCBI / PubMed API Key', placeholder: 'Optional — increases rate limit' },
  { key: 'TAVILY_API_KEY', label: 'Tavily API Key', placeholder: 'Required when Tavily is selected' },
  { key: 'SERPAPI_API_KEY', label: 'SerpAPI Key', placeholder: 'Required when SerpAPI is selected' },
  { key: 'GITHUB_TOKEN', label: 'GitHub Token', placeholder: 'ghp_...' },
]

export function APIKeysSettings({ keys, onChange }: APIKeysSettingsProps) {
  return (
    <div className="grid gap-3">
      {KEY_FIELDS.map(({ key, label, placeholder }) => (
        <div key={key} className="space-y-1.5">
          <Label>{label}</Label>
          <Input
            type="password"
            value={keys[key] ?? ''}
            onChange={(e) => onChange({ [key]: e.target.value || undefined })}
            placeholder={placeholder}
          />
        </div>
      ))}
    </div>
  )
}
