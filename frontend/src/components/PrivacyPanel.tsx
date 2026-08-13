import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { candidatesApi } from '@/lib/api'
import { Spinner } from '@/components/ui'
import type { RedactionSummary } from '@/types'

/** Renders "name, email, phone, 2 URLs hidden from the AI" in the active language. */
function describe(counts: Record<string, number>, t: (key: string) => string): string {
  return Object.entries(counts)
    .map(([type, count]) => {
      const label = t(`privacy.type.${type}`)
      return count > 1 ? `${count} ${label}` : label
    })
    .join(', ')
}

export default function PrivacyPanel({
  candidateId,
  redaction,
}: {
  candidateId: string
  redaction: RedactionSummary
}) {
  const { t } = useTranslation()
  const [showPayload, setShowPayload] = useState(false)

  const preview = useQuery({
    queryKey: ['redaction', candidateId],
    queryFn: () => candidatesApi.redactionPreview(candidateId),
    enabled: showPayload,
  })

  const hasCounts = Object.keys(redaction.counts).length > 0

  return (
    <section
      className={`rounded-lg border p-4 ${
        redaction.applied
          ? 'border-emerald-200 bg-emerald-50/60'
          : 'border-amber-200 bg-amber-50/60'
      }`}
    >
      <div className="flex items-start gap-3">
        <span aria-hidden="true" className="mt-0.5 text-base">
          {redaction.applied ? '🛡️' : '⚠️'}
        </span>
        <div className="min-w-0 flex-1">
          <h3
            className={`text-sm font-semibold ${
              redaction.applied ? 'text-emerald-900' : 'text-amber-900'
            }`}
          >
            {t('privacy.title')}
          </h3>

          <p
            className={`mt-0.5 text-xs ${
              redaction.applied ? 'text-emerald-800' : 'text-amber-800'
            }`}
          >
            {redaction.applied ? t('privacy.applied') : t('privacy.notApplied')}
          </p>

          {redaction.applied && (
            <p className="mt-2 text-sm font-medium text-emerald-900">
              {hasCounts ? describe(redaction.counts, t) : t('privacy.nothing')}
            </p>
          )}

          <div className="mt-2 flex flex-wrap items-center gap-3">
            <span className="rounded-full bg-white/80 px-2 py-0.5 text-[11px] font-medium text-ink-600">
              {redaction.mode === 'full_document'
                ? t('privacy.modeFull')
                : t('privacy.modeRedacted')}
            </span>
            <button
              type="button"
              className="text-xs font-medium text-ink-700 underline underline-offset-2 hover:text-ink-900"
              onClick={() => setShowPayload((current) => !current)}
            >
              {showPayload ? t('privacy.hidePayload') : t('privacy.seePayload')}
            </button>
          </div>

          {showPayload && (
            <div className="mt-3">
              <p className="mb-1 text-xs font-medium text-ink-600">{t('privacy.payloadTitle')}</p>
              {preview.isLoading ? (
                <Spinner />
              ) : (
                <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-md border border-ink-200 bg-white p-3 text-[11px] leading-relaxed text-ink-700">
                  {preview.data?.payload_sent ?? '—'}
                </pre>
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
