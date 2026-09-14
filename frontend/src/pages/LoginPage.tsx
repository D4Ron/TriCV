import { useEffect, useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuthStore } from '@/store/auth'
import { authApi } from '@/lib/api'
import { LogoKapi } from '@/components/Marque'
import { Field, Spinner } from '@/components/ui'

export default function LoginPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const login = useAuthStore((state) => state.login)
  const token = useAuthStore((state) => state.accessToken)

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // Only offer the link where the deployment actually accepts signups.
  const [signupOpen, setSignupOpen] = useState(false)

  useEffect(() => {
    let cancelled = false
    authApi
      .signupConfig()
      .then((config) => {
        if (!cancelled) setSignupOpen(config.enabled)
      })
      .catch(() => {
        /* no link is the safe default */
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (token) return <Navigate to="/mandats" replace />

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await login(email.trim(), password)
      navigate('/mandats')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('login.failed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    // Fond bleu profond de la marque : le premier écran doit dire à qui
    // appartient l'outil avant de demander un mot de passe.
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-brand-900 px-4 py-12">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 opacity-[0.07]"
        style={{
          backgroundImage:
            'radial-gradient(circle at 20% 20%, #6B7FE8 0, transparent 45%), radial-gradient(circle at 80% 70%, #B8892A 0, transparent 40%)',
        }}
      />

      <div className="relative w-full max-w-sm">
        <div className="mb-7 flex flex-col items-center text-center">
          <LogoKapi taille={54} />
          <p className="mt-4 font-titre text-2xl font-bold text-white">Kapi Consult</p>
          <p className="mt-1 text-[11px] font-medium uppercase tracking-[0.18em] text-or-300">
            Nous développons vos métiers
          </p>
        </div>

        <div className="card animate-rise p-6">
          <p className="text-[11px] font-medium uppercase tracking-wider text-brand-700">
            TriCV · outil interne de recrutement
          </p>
          <h1 className="mt-1 text-lg font-semibold text-ink-900">{t('login.title')}</h1>
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

          {signupOpen && (
            <p className="mt-4 border-t border-ink-100 pt-4 text-center text-sm text-ink-500">
              {t('login.noAccount')}{' '}
              <Link to="/signup" className="font-medium text-ink-900 hover:underline">
                {t('login.createAccount')}
              </Link>
            </p>
          )}
        </div>

        <p className="mt-6 text-center text-xs text-brand-200">{t('app.tagline')}</p>

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
