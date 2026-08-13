import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { sessionsApi } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import { EmptyState, Spinner } from '@/components/ui'

/** Actions that bypassed a privacy control are called out, not buried in a list. */
const SENSITIVE = new Set(['candidate.reanalyze_full_document', 'retention.purge'])

export default function AuditPanel({ sessionId }: { sessionId: string }) {
  const { t, i18n } = useTranslation()
  const locale = i18n.resolvedLanguage ?? 'fr'

  const query = useQuery({
    queryKey: ['audit', sessionId],
    queryFn: () => sessionsApi.audit(sessionId),
  })

  return (
    <div className="card p-5">
      <h2 className="text-sm font-semibold text-ink-900">{t('audit.title')}</h2>
      <p className="mt-1 text-xs text-ink-500">{t('audit.hint')}</p>

      {query.isLoading ? (
        <div className="flex justify-center py-8">
          <Spinner className="h-5 w-5 text-ink-400" />
        </div>
      ) : !query.data || query.data.length === 0 ? (
        <div className="mt-4">
          <EmptyState title={t('audit.empty')} />
        </div>
      ) : (
        <ol className="mt-4 space-y-3">
          {query.data.map((entry) => (
            <li
              key={entry.id}
              className={`rounded-lg border px-3 py-2 text-sm ${
                SENSITIVE.has(entry.action)
                  ? 'border-amber-200 bg-amber-50'
                  : 'border-ink-200 bg-white'
              }`}
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="font-medium text-ink-900">
                  {t(`audit.action.${entry.action}`, { defaultValue: entry.action })}
                </span>
                <span className="text-xs text-ink-400">
                  {formatDateTime(entry.created_at, locale)}
                </span>
              </div>
              <p className="mt-0.5 text-xs text-ink-500">
                {t('audit.by')} {entry.user_name ?? t('audit.system')}
              </p>
              {entry.details && Object.keys(entry.details).length > 0 && (
                <p className="mt-1 truncate font-mono text-[11px] text-ink-400">
                  {JSON.stringify(entry.details)}
                </p>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
