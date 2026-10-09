import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { Eye, EyeOff } from 'lucide-react'
import { Field, Spinner, UnderlineTabs } from '@/components/sb/primitives'
import { inputClass } from '@/components/sb/styles'
import { useAuthStore } from '@/stores/authStore'
import { login, register } from '@/lib/api'

type Tab = 'signin' | 'register'
type Errors = Partial<Record<'username' | 'password' | 'confirm' | 'form', string>>

function validate(tab: Tab, username: string, password: string, confirm: string): Errors {
  const errors: Errors = {}
  const name = username.trim()
  if (!name) errors.username = 'Username is required'
  if (tab === 'register') {
    if (name && (name.length < 3 || name.length > 64)) errors.username = 'Use 3 to 64 characters'
    else if (name && !/^[a-zA-Z0-9_-]+$/.test(name)) errors.username = 'Letters, numbers, _ and - only'
    if (password.length < 8) errors.password = 'Use at least 8 characters'
    if (confirm !== password) errors.confirm = 'Passwords don’t match'
  } else if (!password) {
    errors.password = 'Password is required'
  }
  return errors
}

export function LoginPage() {
  const navigate = useNavigate()
  const { isAuthenticated, login: storeLogin } = useAuthStore()
  const [tab, setTab] = useState<Tab>('signin')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [showPw, setShowPw] = useState(false)
  const [errors, setErrors] = useState<Errors>({})
  const [busy, setBusy] = useState(false)

  if (isAuthenticated) return <Navigate to="/chat" replace />

  const isRegister = tab === 'register'

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    const found = validate(tab, username, password, confirm)
    setErrors(found)
    if (Object.keys(found).length) return

    setBusy(true)
    try {
      const name = username.trim()
      if (isRegister) await register(name, password)
      const result = await login(name, password)
      storeLogin(result.username, result.authHeader, result.globalConfig, result.configOptions)
      navigate('/chat')
    } catch (error) {
      setErrors({ form: error instanceof Error ? error.message : isRegister ? 'Registration failed' : 'Sign in failed' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-screen bg-bg font-ui text-ink md:grid-cols-[minmax(0,1.3fr)_minmax(400px,1fr)]">
      <section
        data-screen-label="Login"
        className="flex flex-col justify-end border-line bg-bg1 max-md:border-b md:border-r"
        style={{ padding: 'clamp(32px,6vw,96px)' }}
      >
        <Link to="/" className="text-ink no-underline">
          <h1 className="m-0 font-serif font-normal leading-[.88] tracking-[-0.04em]" style={{ fontSize: 'clamp(80px,13vw,200px)' }}>
            Sci<em className="font-light italic">Bot</em>
          </h1>
        </Link>
        <p className="mt-7 mb-0 max-w-[30ch] text-[19px] leading-normal text-pretty text-ink2">AI-powered scientific research assistant</p>
      </section>

      <section className="flex items-center justify-center p-12 max-sm:px-5 max-sm:py-10">
        <form onSubmit={handleSubmit} noValidate className="flex w-full max-w-[360px] flex-col gap-5">
          <UnderlineTabs
            size="lg"
            className="mb-2 gap-6 border-b border-line"
            value={tab}
            onChange={(next) => {
              setTab(next)
              setErrors({})
            }}
            tabs={[
              { value: 'signin', label: 'Sign in' },
              { value: 'register', label: 'Create account' },
            ]}
          />

          <Field label="Username" error={errors.username}>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder={isRegister ? 'choose-a-username' : 'your-username'}
              autoComplete="username"
              autoFocus
              className={inputClass}
            />
          </Field>

          <Field label="Password" error={errors.password}>
            <span className="relative block">
              <input
                type={showPw ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={isRegister ? 'min. 8 characters' : '••••••••'}
                autoComplete={isRegister ? 'new-password' : 'current-password'}
                className={`${inputClass} pr-10`}
              />
              <button
                type="button"
                onClick={() => setShowPw((v) => !v)}
                aria-label={showPw ? 'Hide password' : 'Show password'}
                className="absolute top-[7px] right-1.5 flex h-7 w-7 cursor-pointer items-center justify-center border-0 bg-transparent text-ink3 hover:text-ink"
              >
                {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </span>
          </Field>

          {isRegister && (
            <Field label="Confirm password" error={errors.confirm}>
              <input
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                placeholder="••••••••"
                autoComplete="new-password"
                className={inputClass}
              />
            </Field>
          )}

          {errors.form && <p className="m-0 text-[13px] font-medium text-warn">{errors.form}</p>}

          <button
            type="submit"
            disabled={busy}
            className="mt-2 flex h-11 cursor-pointer items-center justify-center gap-2 rounded-[10px] border-0 bg-acc text-[14px] font-semibold text-accink transition-[filter] hover:brightness-110 disabled:cursor-wait disabled:opacity-70"
          >
            {busy && <Spinner className="text-accink" />}
            {isRegister ? 'Create account' : 'Sign in'}
          </button>
        </form>
      </section>
    </div>
  )
}
