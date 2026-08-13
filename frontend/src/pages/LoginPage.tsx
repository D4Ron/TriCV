import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuthStore } from '@/store/auth'
import { Logo } from '@/components/Layout'
import { Field, Spinner } from '@/components/ui'

export default function LoginPage() {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const login = useAuthStore((state) => state.login)
  const token = useAuthStore((state) => state.accessToken)

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (token) return <Navigate to="/sessions" replace />

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await login(email.trim(), password)
      navigate('/sessions')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('login.failed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex items-center justify-between">
          <Logo />
          <button
            type="button"
            className="text-xs font-semibold uppercase text-ink-500 hover:text-ink-900"
            onClick={() => void i18n.changeLanguage(i18n.resolvedLanguage === 'fr' ? 'en' : 'fr')}
          >
            {i18n.resolvedLanguage === 'fr' ? 'EN' : 'FR'}
          </button>
        </div>

        <div className="card p-6">
          <h1 className="text-lg font-semibold text-ink-900">{t('login.title')}</h1>
          <p className="mt-1 text-sm text-ink-500">{t('login.subtitle')}</p>

          <form className="mt-6 space-y-4" onSubmit={submit}>
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
                autoComplete="current-password"
                required
                className="input"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </Field>

            {error && (
              <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {error}
              </p>
            )}

            <button type="submit" className="btn-primary w-full" disabled={busy}>
              {busy && <Spinner />}
              {busy ? t('login.submitting') : t('login.submit')}
            </button>
          </form>
        </div>

        <p className="mt-6 text-center text-xs text-ink-400">{t('app.tagline')}</p>

        {/* This page is for HR. Candidates go to the careers index — no account. */}
        <p className="mt-2 text-center text-xs">
          <Link to="/careers" className="text-ink-500 underline-offset-2 hover:underline">
            {t('careers.backToRoles')}
          </Link>
        </p>
      </div>
    </div>
  )
}
