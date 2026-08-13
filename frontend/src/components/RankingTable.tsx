import { useTranslation } from 'react-i18next'
import { Badge, ScoreBar, Spinner } from '@/components/ui'
import { HR_STATUS_TONE, RECOMMENDATION_TONE, formatDate } from '@/lib/format'
import type { CandidateListItem } from '@/types'

export default function RankingTable({
  items,
  selected,
  onToggle,
  onToggleAll,
  onOpen,
  activeId,
}: {
  items: CandidateListItem[]
  selected: Set<string>
  onToggle: (id: string) => void
  onToggleAll: () => void
  onOpen: (id: string) => void
  activeId: string | null
}) {
  const { t, i18n } = useTranslation()
  const locale = i18n.resolvedLanguage ?? 'fr'
  const allSelected = items.length > 0 && items.every((item) => selected.has(item.id))

  return (
    <div className="card overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[880px] text-sm">
          <thead className="table-head">
            <tr>
              <th className="w-10 px-3 py-2.5">
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-ink-300 text-ink-900 focus:ring-brand-500"
                  checked={allSelected}
                  onChange={onToggleAll}
                  aria-label={t('ranking.selected', { count: items.length })}
                />
              </th>
              <th className="w-12 px-2 py-2.5 text-right">{t('ranking.rank')}</th>
              <th className="px-3 py-2.5">{t('ranking.candidate')}</th>
              <th className="w-32 px-3 py-2.5">{t('ranking.score')}</th>
              <th className="w-40 px-3 py-2.5">{t('ranking.recommendation')}</th>
              <th className="w-36 px-3 py-2.5">{t('ranking.hrStatus')}</th>
              <th className="w-32 px-3 py-2.5">{t('ranking.source')}</th>
              <th className="w-28 px-3 py-2.5">{t('ranking.submitted')}</th>
            </tr>
          </thead>

          <tbody className="divide-y divide-ink-100">
            {items.map((candidate) => {
              const busy =
                candidate.analysis_status === 'PENDING' ||
                candidate.analysis_status === 'PROCESSING'
              return (
                <tr
                  key={candidate.id}
                  onClick={() => onOpen(candidate.id)}
                  className={`cursor-pointer transition-colors ${
                    activeId === candidate.id ? 'bg-brand-50' : 'hover:bg-ink-50'
                  }`}
                >
                  <td className="px-3 py-3" onClick={(event) => event.stopPropagation()}>
                    <input
                      type="checkbox"
                      className="h-4 w-4 rounded border-ink-300 text-ink-900 focus:ring-brand-500"
                      checked={selected.has(candidate.id)}
                      onChange={() => onToggle(candidate.id)}
                      aria-label={candidate.full_name ?? candidate.id}
                    />
                  </td>

                  <td className="px-2 py-3 text-right text-xs font-semibold tabular-nums text-ink-400">
                    {candidate.rank}
                  </td>

                  <td className="px-3 py-3">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-ink-900">
                        {candidate.full_name ?? '—'}
                      </span>
                      {candidate.duplicates.length > 0 && (
                        <Badge
                          tone="bg-amber-100 text-amber-800"
                          title={t('ranking.duplicateTooltip')}
                        >
                          {t('ranking.duplicateBadge')}
                        </Badge>
                      )}
                      {candidate.manual_score != null && (
                        <Badge tone="bg-brand-100 text-brand-800">
                          {t('ranking.manualBadge')}
                        </Badge>
                      )}
                    </div>
                    {candidate.email && (
                      <p className="mt-0.5 truncate text-xs text-ink-500">{candidate.email}</p>
                    )}
                    {candidate.missing_must_haves && candidate.missing_must_haves.length > 0 && (
                      <p className="mt-0.5 text-xs text-red-600">
                        {t('candidate.missingMustHaves')}:{' '}
                        {candidate.missing_must_haves.join(' · ')}
                      </p>
                    )}
                  </td>

                  <td className="px-3 py-3">
                    {busy ? (
                      <span className="flex items-center gap-2 text-xs text-ink-500">
                        <Spinner className="h-3.5 w-3.5" />
                        {t(`analysisStatus.${candidate.analysis_status}`)}
                      </span>
                    ) : candidate.analysis_status === 'FAILED' ? (
                      <Badge tone="bg-red-100 text-red-800">{t('analysisStatus.FAILED')}</Badge>
                    ) : (
                      <ScoreBar score={candidate.effective_score} size="sm" />
                    )}
                  </td>

                  <td className="px-3 py-3">
                    {candidate.ai_recommendation ? (
                      <Badge tone={RECOMMENDATION_TONE[candidate.ai_recommendation]}>
                        {t(`recommendation.${candidate.ai_recommendation}`)}
                      </Badge>
                    ) : (
                      <span className="text-xs text-ink-400">—</span>
                    )}
                  </td>

                  <td className="px-3 py-3">
                    <Badge tone={HR_STATUS_TONE[candidate.hr_status]}>
                      {t(`hrStatus.${candidate.hr_status}`)}
                    </Badge>
                  </td>

                  <td className="px-3 py-3 text-xs text-ink-500">
                    {t(`source.${candidate.source}`)}
                  </td>

                  <td className="px-3 py-3 text-xs text-ink-500">
                    {formatDate(candidate.submitted_at, locale)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
