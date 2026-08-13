import { useTranslation } from 'react-i18next'
import type { SessionStats } from '@/types'
import { SCORE_BG, SCORE_TEXT, scoreTone } from '@/lib/format'

function Stat({
  label,
  value,
  tone = 'text-ink-900',
}: {
  label: string
  value: string | number
  tone?: string
}) {
  return (
    <div className="px-4 py-3">
      <dt className="text-xs font-medium uppercase tracking-wide text-ink-500">{label}</dt>
      <dd className={`mt-1 text-xl font-semibold tabular-nums ${tone}`}>{value}</dd>
    </div>
  )
}

export default function StatsStrip({ stats }: { stats: SessionStats }) {
  const { t } = useTranslation()
  const maxBucket = Math.max(1, ...stats.distribution.map((bucket) => bucket.count))

  return (
    <div className="card overflow-hidden">
      <dl className="grid grid-cols-2 divide-x divide-ink-200 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label={t('stats.candidates')} value={stats.total_candidates} />
        <Stat label={t('stats.analyzed')} value={stats.by_analysis_status.ANALYZED ?? 0} />
        <Stat
          label={t('stats.pending')}
          value={(stats.by_analysis_status.PENDING ?? 0) + (stats.by_analysis_status.PROCESSING ?? 0)}
          tone="text-amber-700"
        />
        <Stat
          label={t('stats.average')}
          value={stats.average_score ?? '—'}
          tone={
            stats.average_score == null ? 'text-ink-400' : SCORE_TEXT[scoreTone(stats.average_score)]
          }
        />
        <Stat
          label={t('stats.aboveThreshold')}
          value={`${stats.above_threshold} / ${stats.total_candidates}`}
        />
        <Stat
          label={t('stats.shortlisted')}
          value={stats.by_hr_status.SHORTLISTED ?? 0}
          tone="text-emerald-700"
        />
      </dl>

      {stats.total_candidates > 0 && (
        <div className="border-t border-ink-200 px-4 py-3">
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-500">
            {t('stats.distribution')}
          </p>
          <div className="flex items-end gap-2">
            {stats.distribution.map((bucket) => {
              const midpoint = Number(bucket.label.split('-')[0]) + 10
              return (
                <div key={bucket.label} className="flex flex-1 flex-col items-center gap-1">
                  <span className="text-xs font-medium tabular-nums text-ink-600">
                    {bucket.count || ''}
                  </span>
                  <div
                    className={`w-full rounded-t ${SCORE_BG[scoreTone(midpoint)]} ${
                      bucket.count === 0 ? 'opacity-20' : ''
                    }`}
                    style={{ height: `${Math.max(4, (bucket.count / maxBucket) * 48)}px` }}
                  />
                  <span className="text-[10px] tabular-nums text-ink-400">{bucket.label}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
