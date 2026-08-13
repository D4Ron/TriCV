import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { publicApi } from '@/lib/api'
import { Logo } from '@/components/Layout'
import { Field, Spinner } from '@/components/ui'

const MAX_MB = 10

/**
 * The candidate-facing page. It shows the role and a form — never a score, a
 * rank, or anything about other applicants.
 */
export default function ApplyPage() {
  const { publicKey = '' } = useParams()
  const { t, i18n } = useTranslation()
  const fileRef = useRef<HTMLInputElement>(null)

  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [cv, setCv] = useState<File | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  const session = useQuery({
    queryKey: ['public-session', publicKey],
    queryFn: () => publicApi.session(publicKey),
    retry: false,
  })

  // The advert's own language wins over the browser's.
  useEffect(() => {
    if (session.data?.language) void i18n.changeLanguage(session.data.language)
  }, [session.data?.language, i18n])

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    const found: Record<string, string> = {}
    if (!fullName.trim()) found.fullName = t('apply.required')
    if (!email.trim()) found.email = t('apply.required')
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) found.email = t('apply.invalidEmail')
    if (!cv) found.cv = t('apply.cvRequired')
    setErrors(found)
    if (Object.keys(found).length > 0) return

    setSubmitting(true)
    setSubmitError(null)
    try {
      await publicApi.apply(publicKey, {
        full_name: fullName.trim(),
        email: email.trim(),
        phone: phone.trim() || undefined,
        cv: cv!,
      })
      setDone(true)
    } catch (caught) {
      setSubmitError(caught instanceof Error ? caught.message : t('app.error'))
    } finally {
      setSubmitting(false)
    }
  }

  const shell = (children: React.ReactNode) => (
    <div className="min-h-screen bg-ink-50">
      <header className="border-b border-ink-200 bg-white">
        <div className="mx-auto flex h-14 max-w-3xl items-center justify-between px-4">
          <Logo />
          <button
            type="button"
            className="text-xs font-semibold uppercase text-ink-500 hover:text-ink-900"
            onClick={() => void i18n.changeLanguage(i18n.resolvedLanguage === 'fr' ? 'en' : 'fr')}
          >
            {i18n.resolvedLanguage === 'fr' ? 'EN' : 'FR'}
          </button>
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-4 py-10">
        <Link to="/careers" className="btn-ghost -ml-2 mb-3 text-xs">
          ← {t('careers.backToRoles')}
        </Link>
        {children}
      </main>
    </div>
  )

  if (session.isLoading) {
    return shell(
      <div className="flex justify-center py-20">
        <Spinner className="h-6 w-6 text-ink-400" />
      </div>,
    )
  }

  if (session.isError || !session.data) {
    return shell(
      <div className="card p-8 text-center">
        <h1 className="text-lg font-semibold text-ink-900">{t('apply.notFoundTitle')}</h1>
        <p className="mt-2 text-sm text-ink-500">{t('apply.notFoundBody')}</p>
      </div>,
    )
  }

  const data = session.data

  if (done) {
    return shell(
      <div className="card p-10 text-center">
        <div className="mx-auto grid h-12 w-12 place-items-center rounded-full bg-emerald-100 text-xl text-emerald-700">
          ✓
        </div>
        <h1 className="mt-4 text-lg font-semibold text-ink-900">{t('apply.successTitle')}</h1>
        <p className="mt-2 text-sm text-ink-500">{t('apply.successBody')}</p>
      </div>,
    )
  }

  return shell(
    <div className="space-y-6">
      <div className="card p-6">
        <h1 className="text-xl font-semibold tracking-tight text-ink-900">{data.position}</h1>
        <p className="mt-1 text-sm text-ink-500">
          {data.title}
          {data.department ? ` · ${data.department}` : ''}
        </p>
        {data.description && (
          <div className="mt-4 border-t border-ink-100 pt-4">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
              {t('apply.about')}
            </h2>
            <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-ink-700">
              {data.description}
            </p>
          </div>
        )}
      </div>

      {!data.accepts_applications ? (
        <div className="card p-8 text-center">
          <h2 className="text-base font-semibold text-ink-900">{t('apply.closedTitle')}</h2>
          <p className="mt-2 text-sm text-ink-500">{t('apply.closedBody')}</p>
        </div>
      ) : (
        <form className="card space-y-4 p-6" onSubmit={submit} noValidate>
          <h2 className="text-sm font-semibold text-ink-900">{t('apply.formTitle')}</h2>

          <Field label={t('apply.fullName')} error={errors.fullName} htmlFor="fullName">
            <input
              id="fullName"
              className="input"
              autoComplete="name"
              value={fullName}
              onChange={(event) => setFullName(event.target.value)}
            />
          </Field>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t('apply.email')} error={errors.email} htmlFor="email">
              <input
                id="email"
                type="email"
                className="input"
                autoComplete="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </Field>
            <Field label={t('apply.phoneOptional')} htmlFor="phone">
              <input
                id="phone"
                type="tel"
                className="input"
                autoComplete="tel"
                value={phone}
                onChange={(event) => setPhone(event.target.value)}
              />
            </Field>
          </div>

          <Field
            label={t('apply.cv')}
            hint={t('apply.cvHint', { size: MAX_MB })}
            error={errors.cv}
          >
            <input
              ref={fileRef}
              type="file"
              accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              className="sr-only"
              onChange={(event) => setCv(event.target.files?.[0] ?? null)}
            />
            <div className="flex items-center gap-3">
              <button
                type="button"
                className="btn-secondary"
                onClick={() => fileRef.current?.click()}
              >
                {t('apply.chooseFile')}
              </button>
              <span className="truncate text-sm text-ink-600">{cv?.name ?? '—'}</span>
            </div>
          </Field>

          {submitError && (
            <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {submitError}
            </p>
          )}

          <button type="submit" className="btn-primary w-full" disabled={submitting}>
            {submitting && <Spinner />}
            {submitting ? t('apply.submitting') : t('apply.submit')}
          </button>

          <p className="text-center text-xs text-ink-400">{t('apply.privacyNote')}</p>
        </form>
      )}
    </div>,
  )
}
