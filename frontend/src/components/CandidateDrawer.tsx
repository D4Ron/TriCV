import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { candidatesApi } from '@/lib/api'
import {
  HR_STATUS_TONE,
  RECOMMENDATION_TONE,
  SCORE_BG,
  SCORE_TEXT,
  formatDateTime,
  scoreTone,
} from '@/lib/format'
import { Badge, Callout, ErrorState, Modal, ScoreBar, Spinner } from '@/components/ui'
import PrivacyPanel from '@/components/PrivacyPanel'
import type { HrStatus } from '@/types'

const HR_STATUSES: HrStatus[] = ['NEW', 'SHORTLISTED', 'MAYBE', 'REJECTED']

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-500">{title}</h3>
      {children}
    </section>
  )
}

export default function CandidateDrawer({
  candidateId,
  sessionId,
  provider,
  onClose,
}: {
  candidateId: string
  sessionId: string
  provider: string
  onClose: () => void
}) {
  const { t, i18n } = useTranslation()
  const locale = i18n.resolvedLanguage ?? 'fr'
  const queryClient = useQueryClient()

  const [hrStatus, setHrStatus] = useState<HrStatus>('NEW')
  const [manualScore, setManualScore] = useState<string>('')
  const [notes, setNotes] = useState('')
  const [dirty, setDirty] = useState(false)
  const [saved, setSaved] = useState(false)
  const [showFullDocWarning, setShowFullDocWarning] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)

  const query = useQuery({
    queryKey: ['candidate', candidateId],
    queryFn: () => candidatesApi.get(candidateId),
    // Keep polling while the analysis is still running.
    refetchInterval: (result) => {
      const status = result.state.data?.analysis_status
      return status === 'PENDING' || status === 'PROCESSING' ? 3000 : false
    },
  })
  const candidate = query.data

  useEffect(() => {
    if (!candidate) return
    setHrStatus(candidate.hr_status)
    setManualScore(candidate.manual_score != null ? String(candidate.manual_score) : '')
    setNotes(candidate.hr_notes ?? '')
    setDirty(false)
    setSaved(false)
  }, [candidate?.id, candidate?.hr_status, candidate?.manual_score, candidate?.hr_notes])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)

    // Freeze the page behind the drawer, so a wheel event inside it cannot
    // scroll the ranking underneath.
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = previousOverflow
    }
  }, [onClose])

  // Each candidate opens at the top, not wherever the previous one was left.
  const bodyRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    bodyRef.current?.scrollTo({ top: 0 })
  }, [candidateId])

  // The CV lives behind a bearer token, so it is fetched and turned into an
  // object URL. Revoke it on unmount or when moving to another candidate.
  const [cvUrl, setCvUrl] = useState<string | null>(null)
  const [cvError, setCvError] = useState<string | null>(null)
  useEffect(() => {
    let objectUrl: string | null = null
    let cancelled = false

    setCvUrl(null)
    setCvError(null)

    candidatesApi
      .cvObjectUrl(candidateId)
      .then((url) => {
        objectUrl = url
        if (cancelled) URL.revokeObjectURL(url)
        else setCvUrl(url)
      })
      .catch((error: unknown) => {
        if (!cancelled) setCvError(error instanceof Error ? error.message : t('app.error'))
      })

    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [candidateId, t])

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ['candidate', candidateId] })
    void queryClient.invalidateQueries({ queryKey: ['candidates', sessionId] })
    void queryClient.invalidateQueries({ queryKey: ['stats', sessionId] })
    void queryClient.invalidateQueries({ queryKey: ['audit', sessionId] })
  }

  const save = useMutation({
    mutationFn: () =>
      candidatesApi.update(candidateId, {
        hr_status: hrStatus,
        hr_notes: notes,
        ...(manualScore === ''
          ? { clear_manual_score: true }
          : { manual_score: Number(manualScore) }),
      }),
    onSuccess: () => {
      setDirty(false)
      setSaved(true)
      invalidate()
    },
  })

  const reanalyze = useMutation({
    mutationFn: (fullDocument: boolean) => candidatesApi.reanalyze(candidateId, fullDocument),
    onSuccess: () => {
      setShowFullDocWarning(false)
      invalidate()
    },
  })

  const remove = useMutation({
    mutationFn: () => candidatesApi.remove(candidateId),
    onSuccess: () => {
      invalidate()
      onClose()
    },
  })

  return (
    <>
      <div className="fixed inset-0 z-40 bg-ink-900/20" onClick={onClose} aria-hidden="true" />

      <aside
        className="animate-slide-in fixed right-0 top-0 z-40 flex h-full w-full max-w-2xl flex-col bg-white shadow-drawer"
        role="dialog"
        aria-modal="true"
        aria-label={candidate?.full_name ?? t('app.loading')}
      >
        {/* header */}
        <header className="flex items-start justify-between gap-4 border-b border-ink-200 px-6 py-4">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold text-ink-900">
              {candidate?.full_name ?? t('app.loading')}
            </h2>
            <p className="mt-0.5 truncate text-xs text-ink-500">
              {candidate?.email ?? candidate?.cv_filename ?? ''}
            </p>
          </div>
          <button
            type="button"
            className="btn-ghost -my-1 px-2 py-1 text-lg leading-none"
            onClick={onClose}
            aria-label={t('app.close')}
          >
            ×
          </button>
        </header>

        <div ref={bodyRef} className="flex-1 space-y-6 overflow-y-auto overscroll-contain px-6 py-5">
          {query.isLoading ? (
            <div className="flex justify-center py-16">
              <Spinner className="h-6 w-6 text-ink-400" />
            </div>
          ) : query.isError || !candidate ? (
            <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          ) : (
            <>
              {/* score header */}
              {candidate.analysis_status === 'ANALYZED' && (
                <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
                  <div>
                    <p className="text-xs font-medium uppercase tracking-wide text-ink-500">
                      {t('ranking.score')}
                    </p>
                    <div className="mt-1 flex items-baseline gap-2">
                      <span
                        className={`text-3xl font-semibold tabular-nums ${
                          SCORE_TEXT[scoreTone(candidate.effective_score)]
                        }`}
                      >
                        {candidate.effective_score == null
                          ? '—'
                          : Math.round(candidate.effective_score)}
                      </span>
                      <span className="text-sm text-ink-400">/ 100</span>
                    </div>
                    {candidate.manual_score != null && candidate.ai_score != null && (
                      <p className="mt-0.5 text-xs text-ink-500">
                        {t('ranking.manualBadge')} · IA {Math.round(candidate.ai_score)}
                      </p>
                    )}
                  </div>

                  {candidate.ai_recommendation && (
                    <Badge tone={RECOMMENDATION_TONE[candidate.ai_recommendation]}>
                      {t(`recommendation.${candidate.ai_recommendation}`)}
                    </Badge>
                  )}
                  <Badge tone={HR_STATUS_TONE[candidate.hr_status]}>
                    {t(`hrStatus.${candidate.hr_status}`)}
                  </Badge>
                </div>
              )}

              {candidate.analysis_status === 'FAILED' && (
                <Callout tone="danger" title={t('candidate.failedTitle')}>
                  <p>{candidate.analysis_error}</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      type="button"
                      className="btn-secondary"
                      disabled={reanalyze.isPending}
                      onClick={() => reanalyze.mutate(false)}
                    >
                      {reanalyze.isPending && <Spinner />}
                      {t('candidate.reanalyze')}
                    </button>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => setShowFullDocWarning(true)}
                    >
                      {t('candidate.reanalyzeFull')}
                    </button>
                  </div>
                </Callout>
              )}

              {(candidate.analysis_status === 'PENDING' ||
                candidate.analysis_status === 'PROCESSING') && (
                <Callout tone="info" title={t('candidate.pendingTitle')}>
                  <span className="flex items-center gap-2">
                    <Spinner />
                    {t('candidate.pendingHint')}
                  </span>
                </Callout>
              )}

              {candidate.duplicates.length > 0 && (
                <Callout tone="warning" title={t('ranking.duplicateBadge')}>
                  <p>{t('ranking.duplicateTooltip')}</p>
                  <ul className="mt-1 text-xs">
                    {candidate.duplicates.map((duplicate) => (
                      <li key={duplicate.candidate_id}>{duplicate.full_name ?? duplicate.candidate_id}</li>
                    ))}
                  </ul>
                </Callout>
              )}

              <PrivacyPanel candidateId={candidate.id} redaction={candidate.redaction} />

              {/* extracted profile */}
              <Section title={t('candidate.profile')}>
                <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
                  <div>
                    <dt className="text-xs text-ink-500">{t('candidate.experience')}</dt>
                    <dd className="text-ink-900">
                      {candidate.years_experience != null
                        ? t('candidate.years', { count: candidate.years_experience })
                        : '—'}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-ink-500">{t('candidate.education')}</dt>
                    <dd className="text-ink-900">{candidate.education_level ?? '—'}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-ink-500">{t('candidate.phone')}</dt>
                    <dd className="text-ink-900">{candidate.phone ?? '—'}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-ink-500">{t('ranking.submitted')}</dt>
                    <dd className="text-ink-900">
                      {formatDateTime(candidate.submitted_at, locale)}
                    </dd>
                  </div>
                </dl>

                {candidate.extracted_skills && candidate.extracted_skills.length > 0 && (
                  <div className="mt-3">
                    <p className="text-xs text-ink-500">{t('candidate.skills')}</p>
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      {candidate.extracted_skills.map((skill) => (
                        <span
                          key={skill}
                          className="rounded-md bg-ink-100 px-2 py-0.5 text-xs text-ink-700"
                        >
                          {skill}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </Section>

              {candidate.demographics && Object.keys(candidate.demographics).length > 0 && (
                <Section title={t('candidate.demographics')}>
                  <div className="rounded-lg border border-ink-200 bg-ink-50/60 p-3">
                    <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
                      {Object.entries(candidate.demographics).map(([key, value]) => (
                        <div key={key}>
                          <dt className="text-xs text-ink-500">
                            {t(`candidate.demographic.${key}`, { defaultValue: key })}
                          </dt>
                          <dd className="text-ink-900">{value}</dd>
                        </div>
                      ))}
                    </dl>
                    <p className="mt-2 text-xs text-ink-500">
                      {candidate.redaction.counts.GENDER ||
                      candidate.redaction.counts.AGE ||
                      candidate.redaction.counts.NATIONALITY
                        ? t('candidate.demographicsHint')
                        : t('candidate.demographicsShown')}
                    </p>
                  </div>
                </Section>
              )}

              {candidate.ai_summary && (
                <Section title={t('candidate.summary')}>
                  <p className="text-sm leading-relaxed text-ink-700">{candidate.ai_summary}</p>
                </Section>
              )}

              {candidate.missing_must_haves && candidate.missing_must_haves.length > 0 && (
                <Callout tone="danger" title={t('candidate.missingMustHaves')}>
                  <ul className="mt-1 list-disc space-y-0.5 pl-4 text-sm">
                    {candidate.missing_must_haves.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </Callout>
              )}

              <div className="grid gap-5 sm:grid-cols-2">
                {candidate.ai_strengths && candidate.ai_strengths.length > 0 && (
                  <Section title={t('candidate.strengths')}>
                    <ul className="space-y-1.5 text-sm text-ink-700">
                      {candidate.ai_strengths.map((item) => (
                        <li key={item} className="flex gap-2">
                          <span className="text-emerald-600">+</span>
                          <span>{item}</span>
                        </li>
                      ))}
                    </ul>
                  </Section>
                )}
                {candidate.ai_gaps && candidate.ai_gaps.length > 0 && (
                  <Section title={t('candidate.gaps')}>
                    <ul className="space-y-1.5 text-sm text-ink-700">
                      {candidate.ai_gaps.map((item) => (
                        <li key={item} className="flex gap-2">
                          <span className="text-amber-600">−</span>
                          <span>{item}</span>
                        </li>
                      ))}
                    </ul>
                  </Section>
                )}
              </div>

              {/* per-criterion breakdown */}
              {candidate.criterion_scores.length > 0 && (
                <Section title={t('candidate.criteriaScores')}>
                  <ul className="space-y-3">
                    {candidate.criterion_scores.map((score) => (
                      <li key={score.criterion_id} className="rounded-lg border border-ink-200 p-3">
                        <div className="flex items-center justify-between gap-3">
                          <span className="text-sm font-medium text-ink-900">
                            {score.criterion_name}
                            {score.is_must_have && (
                              <span className="ml-1.5 text-xs font-normal text-red-600">
                                · {t('builder.mustHave')}
                              </span>
                            )}
                          </span>
                          <span className="shrink-0 text-xs text-ink-400">
                            {t('builder.weight')} {score.weight}/10
                          </span>
                        </div>

                        <div className="mt-2 flex items-center gap-3">
                          <span className="h-2 flex-1 overflow-hidden rounded-full bg-ink-100">
                            <span
                              className={`block h-full rounded-full ${SCORE_BG[scoreTone(score.score)]}`}
                              style={{ width: `${score.score}%` }}
                            />
                          </span>
                          <span
                            className={`w-8 text-right text-sm font-semibold tabular-nums ${SCORE_TEXT[scoreTone(score.score)]}`}
                          >
                            {Math.round(score.score)}
                          </span>
                        </div>

                        <p className="mt-2 text-xs leading-relaxed text-ink-600">
                          {score.justification || t('candidate.noJustification')}
                        </p>
                      </li>
                    ))}
                  </ul>
                </Section>
              )}

              {/* CV preview */}
              <Section title={t('candidate.cvPreview')}>
                {cvError ? (
                  <Callout tone="danger">{cvError}</Callout>
                ) : !cvUrl ? (
                  <div className="flex h-24 items-center justify-center rounded-lg border border-ink-200">
                    <Spinner className="h-5 w-5 text-ink-400" />
                  </div>
                ) : candidate.cv_mime_type === 'application/pdf' ? (
                  <iframe
                    title={t('candidate.cvPreview')}
                    src={cvUrl}
                    className="h-96 w-full rounded-lg border border-ink-200"
                  />
                ) : (
                  <p className="text-sm text-ink-500">{t('candidate.cvUnavailable')}</p>
                )}
                {cvUrl && (
                  <a
                    className="btn-secondary mt-2"
                    href={cvUrl}
                    target="_blank"
                    rel="noreferrer"
                    download={candidate.cv_filename ?? undefined}
                  >
                    {t('candidate.openCv')}
                  </a>
                )}
              </Section>

              {/* HR override */}
              <Section title={t('candidate.override')}>
                <div className="space-y-4 rounded-lg border border-ink-200 p-4">
                  <p className="text-xs text-ink-500">{t('candidate.overrideHint')}</p>

                  <div>
                    <span className="label">{t('candidate.hrStatusLabel')}</span>
                    <div className="flex flex-wrap gap-2">
                      {HR_STATUSES.map((status) => (
                        <button
                          key={status}
                          type="button"
                          onClick={() => {
                            setHrStatus(status)
                            setDirty(true)
                            setSaved(false)
                          }}
                          className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                            hrStatus === status
                              ? HR_STATUS_TONE[status]
                              : 'bg-white text-ink-600 ring-1 ring-ink-200 hover:bg-ink-50'
                          }`}
                        >
                          {t(`hrStatus.${status}`)}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div>
                    <label className="label" htmlFor="manual-score">
                      {t('candidate.manualScore')}
                    </label>
                    <div className="flex items-center gap-2">
                      <input
                        id="manual-score"
                        type="number"
                        min={0}
                        max={100}
                        className="input max-w-[120px]"
                        value={manualScore}
                        onChange={(event) => {
                          setManualScore(event.target.value)
                          setDirty(true)
                          setSaved(false)
                        }}
                      />
                      {manualScore !== '' && (
                        <button
                          type="button"
                          className="btn-ghost text-xs"
                          onClick={() => {
                            setManualScore('')
                            setDirty(true)
                            setSaved(false)
                          }}
                        >
                          {t('candidate.clearManualScore')}
                        </button>
                      )}
                      {candidate.ai_score != null && (
                        <ScoreBar score={candidate.ai_score} size="sm" showBar={false} />
                      )}
                    </div>
                    <p className="hint">{t('candidate.manualScoreHint')}</p>
                  </div>

                  <div>
                    <label className="label" htmlFor="hr-notes">
                      {t('candidate.notes')}
                    </label>
                    <textarea
                      id="hr-notes"
                      className="input min-h-[80px] resize-y"
                      placeholder={t('candidate.notesPlaceholder')}
                      value={notes}
                      onChange={(event) => {
                        setNotes(event.target.value)
                        setDirty(true)
                        setSaved(false)
                      }}
                    />
                  </div>

                  <div className="flex items-center gap-3">
                    <button
                      type="button"
                      className="btn-primary"
                      disabled={!dirty || save.isPending}
                      onClick={() => save.mutate()}
                    >
                      {save.isPending && <Spinner />}
                      {t('candidate.saveDecision')}
                    </button>
                    {saved && (
                      <span className="text-xs font-medium text-emerald-700">
                        ✓ {t('candidate.saved')}
                      </span>
                    )}
                  </div>
                </div>
              </Section>

              {/* dangerous / secondary actions */}
              <div className="flex flex-wrap gap-2 border-t border-ink-200 pt-4">
                <button
                  type="button"
                  className="btn-secondary"
                  disabled={reanalyze.isPending}
                  onClick={() => reanalyze.mutate(false)}
                >
                  {reanalyze.isPending && <Spinner />}
                  {t('candidate.reanalyze')}
                </button>
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => setShowFullDocWarning(true)}
                >
                  {t('candidate.reanalyzeFull')}
                </button>
                <button
                  type="button"
                  className="btn-danger ml-auto"
                  onClick={() => setShowDeleteConfirm(true)}
                >
                  {t('candidate.delete')}
                </button>
              </div>
            </>
          )}
        </div>
      </aside>

      {/* The full-document path bypasses redaction — say so plainly first. */}
      <Modal
        open={showFullDocWarning}
        onClose={() => setShowFullDocWarning(false)}
        title={t('privacy.fullDocWarningTitle')}
        tone="danger"
        footer={
          <>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => setShowFullDocWarning(false)}
            >
              {t('app.cancel')}
            </button>
            <button
              type="button"
              className="btn-primary bg-red-700 hover:bg-red-800"
              disabled={reanalyze.isPending}
              onClick={() => reanalyze.mutate(true)}
            >
              {reanalyze.isPending && <Spinner />}
              {t('privacy.fullDocConfirm')}
            </button>
          </>
        }
      >
        <p>{t('privacy.fullDocWarningBody', { provider })}</p>
        <p className="mt-2 text-ink-500">{t('privacy.fullDocWarningWhen')}</p>
      </Modal>

      <Modal
        open={showDeleteConfirm}
        onClose={() => setShowDeleteConfirm(false)}
        title={t('candidate.delete')}
        tone="danger"
        footer={
          <>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => setShowDeleteConfirm(false)}
            >
              {t('app.cancel')}
            </button>
            <button
              type="button"
              className="btn-primary bg-red-700 hover:bg-red-800"
              disabled={remove.isPending}
              onClick={() => remove.mutate()}
            >
              {remove.isPending && <Spinner />}
              {t('app.delete')}
            </button>
          </>
        }
      >
        <p>{t('candidate.confirmDelete')}</p>
      </Modal>
    </>
  )
}
