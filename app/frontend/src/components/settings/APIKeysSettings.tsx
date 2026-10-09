import { Field } from '@/components/sb/primitives'
import { inputClass } from '@/components/sb/styles'
import type { ExternalKeys } from '@/types/config'

interface APIKeysSettingsProps {
  keys: ExternalKeys
  onChange: (updates: Partial<ExternalKeys>) => void
}

const KEY_FIELDS: { key: keyof ExternalKeys; label: string; hint?: string }[] = [
  { key: 'TAVILY_API_KEY', label: 'Tavily API key', hint: 'Required when Tavily is the search tool.' },
  { key: 'SERPAPI_API_KEY', label: 'SerpAPI key', hint: 'Required when SerpAPI is the search tool.' },
  { key: 'SEMANTIC_SCHOLAR_API_KEY', label: 'Semantic Scholar API key', hint: 'Optional. Raises the rate limit for reference fetching.' },
  { key: 'NCBI_API_KEY', label: 'NCBI / PubMed API key', hint: 'Optional. Raises the PubMed rate limit.' },
  { key: 'GITHUB_TOKEN', label: 'GitHub token', hint: 'Optional. Needed for private repositories.' },
]

export function APIKeysSettings({ keys, onChange }: APIKeysSettingsProps) {
  return (
    <>
      {KEY_FIELDS.map(({ key, label, hint }) => (
        <Field key={key} label={label} hint={hint}>
          <input
            type="password"
            value={keys[key] ?? ''}
            onChange={(e) => onChange({ [key]: e.target.value || undefined })}
            placeholder={key}
            autoComplete="off"
            className={`${inputClass} font-mono text-[13px]`}
          />
        </Field>
      ))}
      <p className="m-0 text-[12px] leading-normal text-ink3">Keys are encrypted per user and used only by the tools that need them.</p>
    </>
  )
}
