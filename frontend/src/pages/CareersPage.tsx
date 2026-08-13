import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { publicApi } from '@/lib/api'
import { Logo } from '@/components/Layout'
import { EmptyState, ErrorState, Spinner } from '@/components/ui'
import { formatDate } from '@/lib/format'

/**
 * The public careers index — the entry point for the standalone deployment.
 * Lists every role open to applications and links each to its own apply page.
 * Like the rest of the candidate-facing surface, it never shows a score, a
 * ranking, or how many other people applied.
 */
export default function CareersPage() {
  const { t, i18n } = useTranslation()
  const locale = i18n.resolvedLanguage ?? 'fr'

  const query = useQuery({ queryKey: ['public-roles'], queryFn: publicApi.roles })

  return (
    <div className="min-h-screen bg-ink-50">
      <header className="border-b border-ink-200 bg-white">
        <div className="mx-auto flex h-14 max-w-3xl items-center justify-between px-4">
          <Logo />
          <button
            type="button"
            className="text-xs font-semibold uppercase text-ink-500 hover:text-ink-900"
            onClick={() => void i18n.changeLanguage(locale === 'fr' ? 'en' : 'fr')}
          >
            {locale === 'fr' ? 'EN' : 'FR'}
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-10">
        <div className="mb-8">
          <h1 className="text-2xl font-semibold tracking-tight text-ink-900">
            {t('careers.title')}
          </h1>
          <p className="mt-2 text-sm text-ink-500">{t('careers.subtitle')}</p>
        </div>

        {query.isLoading ? (
          <div className="flex justify-center py-20">
            <Spinner className="h-6 w-6 text-ink-400" />
          </div>
        ) : query.isError ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        ) : !query.data || query.data.length === 0 ? (
          <EmptyState title={t('careers.empty')} hint={t('careers.emptyHint')} />
        ) : (
          <ul className="space-y-4">
            {query.data.map((role) => (
              <li key={role.public_key}>
                <Link
                  to={`/apply/${role.public_key}`}
                  className="card block p-5 transition-shadow hover:shadow-lg"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <h2 className="text-base font-semibold text-ink-900">{role.position}</h2>
                      <p className="mt-0.5 text-xs text-ink-500">
                        {role.department ? `${role.department} · ` : ''}
                        {t('careers.postedOn', {
                          date: formatDate(role.posted_at, locale),
                        })}
                      </p>
                    </div>
                    <span className="shrink-0 text-sm font-medium text-brand-700">
                      {t('careers.apply')} →
                    </span>
                  </div>

                  {role.description && (
                    <p className="mt-3 line-clamp-3 text-sm leading-relaxed text-ink-600">
                      {role.description}
                    </p>
                  )}
                </Link>
              </li>
            ))}
          </ul>
        )}

        <p className="mt-10 border-t border-ink-200 pt-4 text-xs text-ink-400">
          {t('careers.privacyNote')}
        </p>
      </main>
    </div>
  )
}
