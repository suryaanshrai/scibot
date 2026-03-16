import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import type { ExternalKeys, SearchConfig } from '@/types/config'
import { SEARCH_TOOLS } from '@/types/config'

interface SearchSettingsProps {
  config: SearchConfig
  onChange: (updates: Partial<SearchConfig>) => void
  keys: ExternalKeys
  onKeysChange: (updates: Partial<ExternalKeys>) => void
}

export function SearchSettings({ config, onChange, keys, onKeysChange }: SearchSettingsProps) {
  const keyHint =
    config.tool === 'tavily'
      ? 'Tavily requires a TAVILY_API_KEY in API Keys.'
      : config.tool === 'serp'
      ? 'SerpAPI requires a SERPAPI_API_KEY in API Keys.'
      : 'DuckDuckGo works without an API key.'

  const activeKeyField =
    config.tool === 'tavily'
      ? { key: 'TAVILY_API_KEY' as const, label: 'Tavily API Key' }
      : config.tool === 'serp'
      ? { key: 'SERPAPI_API_KEY' as const, label: 'SerpAPI Key' }
      : null

  return (
    <div className="grid gap-3">
      <div className="space-y-1.5">
        <Label>Search tool</Label>
        <Select value={config.tool} onValueChange={(v) => onChange({ tool: v as SearchConfig['tool'] })}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            {SEARCH_TOOLS.map((t) => (
              <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className={cn(
          'text-xs',
          config.tool === 'duckduckgo' ? 'text-muted-foreground' : 'text-foreground'
        )}>
          {keyHint}
        </p>
      </div>

      {activeKeyField && (
        <div className="space-y-1.5">
          <Label>{activeKeyField.label}</Label>
          <Input
            type="password"
            value={keys[activeKeyField.key] ?? ''}
            onChange={(e) => onKeysChange({ [activeKeyField.key]: e.target.value || undefined })}
            placeholder={`Enter ${activeKeyField.label}`}
          />
        </div>
      )}

      <div className="space-y-1.5">
        <Label>Extra domain whitelist <span className="text-muted-foreground">(newline-separated)</span></Label>
        <Textarea
          value={(config.whitelist_extra ?? []).join('\n')}
          onChange={(e) =>
            onChange({ whitelist_extra: e.target.value.split('\n').map((s) => s.trim()).filter(Boolean) })
          }
          placeholder="example.com&#10;another-site.org"
          rows={3}
        />
      </div>
    </div>
  )
}
