import { useEffect, useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuthStore } from '@/store/auth'
import { authApi } from '@/lib/api'
import { Logo } from '@/components/Layout'
import { Field, Spinner } from '@/components/ui'

const MIN_PASSWORD = 8

export default function SignupPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const signup = useAuthStore((state) => state.signup)
  const token = useAuthStore((state) => state.accessToken)

  const [config, setConfig] = useState<{ enabled: boolean; requires_code: boolean } | null>(null)
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [signupCode, setSignupCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let cancelled = false
    authApi
      .signupConfig()
      .then((value) => {
        if (!cancelled) setConfig(value)
      })
      .catch(() => {
        // Treat an unreachable config as "closed" rather than showing a form
        // that cannot succeed.
        if (!cancelled) setConfig({ enabled: false, requires_code: false })
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (token) return <Navigate to="/mandats" replace />

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)

    // Checked here as well as by the API so the mismatch is caught before a
    // round trip, and so the two password fields can be compared at all.
    if (password !== confirm) {
      setError(t('signup.mismatch'))
      return
    }
    if (password.length < MIN_PASSWORD) {
      setError(t('signup.tooShort', { count: MIN_PASSWORD }))
      return
    }

    setBusy(true)
    try {
      await signup({
        email: email.trim(),
        password,
        fullName: fullName.trim(),
        signupCode: signupCode.trim(),
      })
      navigate('/mandats')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('signup.failed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-8">
          <Logo />
        </div>

        <div className="card p-6">
          <h1 className="text-lg font-semibold text-ink-900">{t('signup.title')}</h1>
          <p className="mt-1 text-sm text-ink-500">{t('signup.subtitle')}</p>

          {config === null && (
            <div className="mt-6 flex justify-center py-6">
              <Spinner />
            </div>
          )}

          {config !== null && !config.enabled && (
            <p className="mt-6 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
              {t('signup.disabled')}
            </p>
          )}

          {config?.enabled && (
            <form className="mt-6 space-y-4" onSubmit={submit}>
              <Field label={t('signup.fullName')} htmlFor="full-name">
                <input
                  id="full-name"
                  type="text"
                  autoComplete="name"
                  required
                  className="input"
                  value={fullName}
                  onChange={(event) => setFullName(event.target.value)}
                />
              </Field>

              <Field label={t('login.email')} htmlFor="email">
                <input
                  id="email"
                  type="email"
                  autoComplete="username"
                  required
                  className="input"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                />
              </Field>

              <Field label={t('login.password')} htmlFor="password">
                <input
                  id="password"
                  type="password"
                  autoComplete="new-password"
                  required
                  minLength={MIN_PASSWORD}
                  className="input"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                />
              </Field>

              <Field label={t('signup.confirm')} htmlFor="confirm">
                <input
                  id="confirm"
                  type="password"
                  autoComplete="new-password"
                  required
                  className="input"
                  value={confirm}
                  onChange={(event) => setConfirm(event.target.value)}
                />
              </Field>

              {config.requires_code && (
                <Field label={t('signup.code')} htmlFor="signup-code" hint={t('signup.codeHint')}>
                  <input
                    id="signup-code"
                    type="text"
                    required
                    className="input"
                    value={signupCode}
                    onChange={(event) => setSignupCode(event.target.value)}
                  />
                </Field>
              )}

              {error && (
                <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                  {error}
                </p>
              )}

              <button type="submit" className="btn-primary w-full" disabled={busy}>
                {busy && <Spinner />}
                {busy ? t('signup.submitting') : t('signup.submit')}
              </button>
            </form>
          )}
        </div>

        <p className="mt-6 text-center text-xs">
          <Link to="/login" className="text-ink-500 underline-offset-2 hover:underline">
            {t('signup.haveAccount')}
          </Link>
        </p>
      </div>
    </div>
  )
}
