import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { sessionsApi } from '@/lib/api'
import { SESSION_STATUS_TONE, formatDate } from '@/lib/format'
import { Badge, EmptyState, ErrorState, PageLoader } from '@/components/ui'
import type { SessionStatus } from '@/types'

const STATUSES: SessionStatus[] = ['DRAFT', 'OPEN', 'CLOSED', 'ARCHIVED']

export default function SessionsPage() {
  const { t, i18n } = useTranslation()
  const [status, setStatus] = useState<string>('')
  const [search, setSearch] = useState('')

  const query = useQuery({
    queryKey: ['sessions', status, search],
    queryFn: () => sessionsApi.list({ status: status || undefined, search: search || undefined }),
  })

  const filtered = Boolean(status || search)

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-ink-900">
            {t('sessions.title')}
          </h1>
          <p className="mt-1 text-sm text-ink-500">{t('sessions.subtitle')}</p>
        </div>
        <Link to="/sessions/new" className="btn-primary">
          {t('sessions.create')}
        </Link>
      </div>

      <div className="flex flex-wrap gap-3">
        <input
          className="input max-w-xs"
          placeholder={t('sessions.searchPlaceholder')}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <select
          className="input max-w-[200px]"
          value={status}
          onChange={(event) => setStatus(event.target.value)}
        >
          <option value="">{t('sessions.allStatuses')}</option>
          {STATUSES.map((value) => (
            <option key={value} value={value}>
              {t(`status.${value}`)}
            </option>
          ))}
        </select>
      </div>

      {query.isLoading ? (
        <PageLoader />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : query.data && query.data.length > 0 ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {query.data.map((session) => (
            <Link
              key={session.id}
              to={`/sessions/${session.id}`}
              className="card flex flex-col gap-3 p-5 transition-shadow hover:shadow-lg"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h2 className="truncate text-sm font-semibold text-ink-900">{session.title}</h2>
                  <p className="mt-0.5 truncate text-xs text-ink-500">
                    {session.position}
                    {session.department ? ` · ${session.department}` : ''}
                  </p>
                </div>
                <Badge tone={SESSION_STATUS_TONE[session.status]}>
                  {t(`status.${session.status}`)}
                </Badge>
              </div>

              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-500">
                <span>{t('sessions.criteriaCount', { count: session.criteria_count })}</span>
                <span>{t('sessions.candidatesCount', { count: session.counts.total })}</span>
                {session.counts.shortlisted > 0 && (
                  <span className="font-medium text-emerald-700">
                    {t('sessions.shortlisted', { count: session.counts.shortlisted })}
                  </span>
                )}
              </div>

              {session.counts.total > 0 && (
                <div className="flex h-1.5 overflow-hidden rounded-full bg-ink-100">
                  <span
                    className="bg-emerald-500"
                    style={{
                      width: `${(session.counts.analyzed / session.counts.total) * 100}%`,
                    }}
                  />
                  <span
                    className="bg-amber-400"
                    style={{
                      width: `${
                        ((session.counts.pending + session.counts.processing) /
                          session.counts.total) *
                        100
                      }%`,
                    }}
                  />
                  <span
                    className="bg-red-400"
                    style={{ width: `${(session.counts.failed / session.counts.total) * 100}%` }}
                  />
                </div>
              )}

              <p className="mt-auto text-xs text-ink-400">
                {t('sessions.createdOn', {
                  date: formatDate(session.created_at, i18n.resolvedLanguage ?? 'fr'),
                })}
              </p>
            </Link>
          ))}
        </div>
      ) : (
        <EmptyState
          title={filtered ? t('sessions.emptyFiltered') : t('sessions.empty')}
          hint={filtered ? undefined : t('sessions.emptyHint')}
          action={
            !filtered && (
              <Link to="/sessions/new" className="btn-primary">
                {t('sessions.create')}
              </Link>
            )
          }
        />
      )}
    </div>
  )
}
