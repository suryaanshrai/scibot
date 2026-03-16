import { useState } from 'react'
import { useNavigate, Navigate } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Bot, Eye, EyeOff, Loader2 } from 'lucide-react'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAuthStore } from '@/stores/authStore'
import { login, register } from '@/lib/api'

const loginSchema = z.object({
  username: z.string().min(1, 'Username is required'),
  password: z.string().min(1, 'Password is required'),
})

const registerSchema = z.object({
  username: z.string().min(3, 'At least 3 characters').max(64).regex(/^[a-zA-Z0-9_-]+$/, 'Letters, numbers, _ and - only'),
  password: z.string().min(8, 'At least 8 characters'),
  confirm: z.string(),
}).refine((d) => d.password === d.confirm, { message: "Passwords don't match", path: ['confirm'] })

type LoginData = z.infer<typeof loginSchema>
type RegisterData = z.infer<typeof registerSchema>

function PasswordInput({ id, placeholder, registration }: {
  id: string
  placeholder?: string
  registration: ReturnType<ReturnType<typeof useForm>['register']>
}) {
  const [show, setShow] = useState(false)
  return (
    <div className="relative">
      <Input id={id} type={show ? 'text' : 'password'} placeholder={placeholder} {...registration} className="pr-9" />
      <button
        type="button"
        className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
        onClick={() => setShow(!show)}
        tabIndex={-1}
      >
        {show ? <EyeOff size={16} /> : <Eye size={16} />}
      </button>
    </div>
  )
}

export function LoginPage() {
  const navigate = useNavigate()
  const { isAuthenticated, login: storeLogin } = useAuthStore()
  const [error, setError] = useState<string | null>(null)

  const loginForm = useForm<LoginData>({ resolver: zodResolver(loginSchema) })
  const registerForm = useForm<RegisterData>({ resolver: zodResolver(registerSchema) })

  if (isAuthenticated) return <Navigate to="/chat" replace />

  const handleLogin = loginForm.handleSubmit(async ({ username, password }) => {
    setError(null)
    try {
      const result = await login(username, password)
      storeLogin(result.username, result.authHeader, result.globalConfig, result.configOptions)
      navigate('/chat')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Login failed')
    }
  })

  const handleRegister = registerForm.handleSubmit(async ({ username, password }) => {
    setError(null)
    try {
      await register(username, password)
      const result = await login(username, password)
      storeLogin(result.username, result.authHeader, result.globalConfig, result.configOptions)
      navigate('/chat')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Registration failed')
    }
  })

  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-gradient-to-br from-background to-muted">
      <div className="w-full max-w-md space-y-6">
        {/* Logo */}
        <div className="flex flex-col items-center gap-2">
          <div className="h-12 w-12 rounded-xl bg-primary flex items-center justify-center">
            <Bot size={26} className="text-white" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight">SciBot</h1>
          <p className="text-sm text-muted-foreground">AI-powered scientific research assistant</p>
        </div>

        <Card>
          <CardHeader className="pb-3">
            <Tabs defaultValue="login" onValueChange={() => setError(null)}>
              <TabsList className="w-full">
                <TabsTrigger value="login" className="flex-1">Sign in</TabsTrigger>
                <TabsTrigger value="register" className="flex-1">Create account</TabsTrigger>
              </TabsList>

              {/* LOGIN */}
              <TabsContent value="login">
                <CardContent className="px-0 pb-0 pt-4">
                  <form onSubmit={handleLogin} className="space-y-4">
                    <div className="space-y-1.5">
                      <Label htmlFor="login-username">Username</Label>
                      <Input
                        id="login-username"
                        placeholder="your-username"
                        autoComplete="username"
                        {...loginForm.register('username')}
                      />
                      {loginForm.formState.errors.username && (
                        <p className="text-xs text-destructive">{loginForm.formState.errors.username.message}</p>
                      )}
                    </div>

                    <div className="space-y-1.5">
                      <Label htmlFor="login-password">Password</Label>
                      <PasswordInput
                        id="login-password"
                        placeholder="••••••••"
                        registration={loginForm.register('password')}
                      />
                      {loginForm.formState.errors.password && (
                        <p className="text-xs text-destructive">{loginForm.formState.errors.password.message}</p>
                      )}
                    </div>

                    {error && <p className="text-xs text-destructive bg-destructive/10 rounded px-3 py-2">{error}</p>}

                    <Button type="submit" className="w-full" disabled={loginForm.formState.isSubmitting}>
                      {loginForm.formState.isSubmitting && <Loader2 size={14} className="animate-spin mr-2" />}
                      Sign in
                    </Button>
                  </form>
                </CardContent>
              </TabsContent>

              {/* REGISTER */}
              <TabsContent value="register">
                <CardContent className="px-0 pb-0 pt-4">
                  <form onSubmit={handleRegister} className="space-y-4">
                    <div className="space-y-1.5">
                      <Label htmlFor="reg-username">Username</Label>
                      <Input
                        id="reg-username"
                        placeholder="choose-a-username"
                        autoComplete="username"
                        {...registerForm.register('username')}
                      />
                      {registerForm.formState.errors.username && (
                        <p className="text-xs text-destructive">{registerForm.formState.errors.username.message}</p>
                      )}
                    </div>

                    <div className="space-y-1.5">
                      <Label htmlFor="reg-password">Password</Label>
                      <PasswordInput
                        id="reg-password"
                        placeholder="min. 8 characters"
                        registration={registerForm.register('password')}
                      />
                      {registerForm.formState.errors.password && (
                        <p className="text-xs text-destructive">{registerForm.formState.errors.password.message}</p>
                      )}
                    </div>

                    <div className="space-y-1.5">
                      <Label htmlFor="reg-confirm">Confirm password</Label>
                      <PasswordInput
                        id="reg-confirm"
                        placeholder="••••••••"
                        registration={registerForm.register('confirm')}
                      />
                      {registerForm.formState.errors.confirm && (
                        <p className="text-xs text-destructive">{registerForm.formState.errors.confirm.message}</p>
                      )}
                    </div>

                    {error && <p className="text-xs text-destructive bg-destructive/10 rounded px-3 py-2">{error}</p>}

                    <Button type="submit" className="w-full" disabled={registerForm.formState.isSubmitting}>
                      {registerForm.formState.isSubmitting && <Loader2 size={14} className="animate-spin mr-2" />}
                      Create account
                    </Button>
                  </form>
                </CardContent>
              </TabsContent>
            </Tabs>
          </CardHeader>
        </Card>
      </div>
    </div>
  )
}
