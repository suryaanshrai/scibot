import { useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { DataSourceCred } from '@/types/config'

interface DataSourceCredsSettingsProps {
  creds: Record<string, DataSourceCred>
  onChange: (creds: Record<string, DataSourceCred>) => void
}

export function DataSourceCredsSettings({ creds, onChange }: DataSourceCredsSettingsProps) {
  const [newAlias, setNewAlias] = useState('')

  const addCred = () => {
    const alias = newAlias.trim()
    if (!alias || creds[alias]) return
    onChange({ ...creds, [alias]: { type: 'postgres', connection_string: '' } })
    setNewAlias('')
  }

  const removeCred = (alias: string) => {
    const next = { ...creds }
    delete next[alias]
    onChange(next)
  }

  const updateCred = (alias: string, updates: Partial<DataSourceCred>) => {
    onChange({ ...creds, [alias]: { ...creds[alias], ...updates } })
  }

  return (
    <div className="space-y-4">
      {Object.entries(creds).map(([alias, cred]) => (
        <div key={alias} className="space-y-2 border rounded-lg p-3 bg-muted/30">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium font-mono">{alias}</span>
            <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive" onClick={() => removeCred(alias)}>
              <Trash2 size={14} />
            </Button>
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs">Type</Label>
            <Select value={cred.type} onValueChange={(v) => updateCred(alias, { type: v as DataSourceCred['type'] })}>
              <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="postgres">PostgreSQL</SelectItem>
                <SelectItem value="mongodb">MongoDB</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs">Connection string</Label>
            <Input
              type="password"
              value={cred.connection_string}
              onChange={(e) => updateCred(alias, { connection_string: e.target.value })}
              placeholder={cred.type === 'postgres' ? 'postgresql://user:pass@host/db' : 'mongodb+srv://...'}
              className="h-8 text-xs"
            />
          </div>
        </div>
      ))}

      <div className="flex gap-2">
        <Input
          value={newAlias}
          onChange={(e) => setNewAlias(e.target.value)}
          placeholder="Alias (e.g. my-postgres)"
          className="h-8 text-sm"
          onKeyDown={(e) => e.key === 'Enter' && addCred()}
        />
        <Button type="button" variant="outline" size="sm" onClick={addCred} disabled={!newAlias.trim()}>
          <Plus size={14} />
        </Button>
      </div>
    </div>
  )
}
