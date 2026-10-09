import { useState } from 'react'
import { Field, SelectInput } from '@/components/sb/primitives'
import { inputClass, textareaClass } from '@/components/sb/styles'
import type { ExternalKeys, SearchConfig } from '@/types/config'
import { SEARCH_TOOLS } from '@/types/config'

interface SearchSettingsProps {
  config: SearchConfig
  onChange: (updates: Partial<SearchConfig>) => void
  keys: ExternalKeys
  onKeysChange: (updates: Partial<ExternalKeys>) => void
}

const parseList = (text: string) =>
  text
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean)

export function SearchSettings({ config, onChange, keys, onKeysChange }: SearchSettingsProps) {
  // Raw text is kept locally so blank lines survive while typing.
  const [whitelist, setWhitelist] = useState(() => (config.whitelist_extra ?? []).join('\n'))

  const keyHint =
    config.tool === 'tavily'
      ? 'Tavily requires a TAVILY_API_KEY in API Keys.'
      : config.tool === 'serp'
        ? 'SerpAPI requires a SERPAPI_API_KEY in API Keys.'
        : 'DuckDuckGo works without an API key.'

  const activeKeyField =
    config.tool === 'tavily'
      ? { key: 'TAVILY_API_KEY' as const, label: 'Tavily API key' }
      : config.tool === 'serp'
        ? { key: 'SERPAPI_API_KEY' as const, label: 'SerpAPI key' }
        : null

  return (
    <>
      <Field label="Search tool" hint={<span className="text-ink2">{keyHint}</span>}>
        <SelectInput
          value={config.tool}
          onChange={(tool) => onChange({ tool: tool as SearchConfig['tool'] })}
          options={SEARCH_TOOLS}
        />
      </Field>

      {activeKeyField && (
        <Field label={activeKeyField.label}>
          <input
            type="password"
            value={keys[activeKeyField.key] ?? ''}
            onChange={(e) => onKeysChange({ [activeKeyField.key]: e.target.value || undefined })}
            placeholder={activeKeyField.key}
            autoComplete="off"
            className={`${inputClass} font-mono text-[13px]`}
          />
        </Field>
      )}

      <Field label={<>Extra domain whitelist <span className="font-normal text-ink3">(newline-separated)</span></>}>
        <textarea
          rows={4}
          value={whitelist}
          onChange={(e) => {
            setWhitelist(e.target.value)
            onChange({ whitelist_extra: parseList(e.target.value) })
          }}
          placeholder="example.com"
          className={textareaClass}
        />
      </Field>
    </>
  )
}
