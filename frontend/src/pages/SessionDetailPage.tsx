import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { candidatesApi, sessionsApi, settingsApi } from '@/lib/api'
import { SESSION_STATUS_TONE, formatDate } from '@/lib/format'
import { Badge, Callout, EmptyState, ErrorState, Modal, PageLoader, Spinner } from '@/components/ui'
import StatsStrip from '@/components/StatsStrip'
import UploadDropzone from '@/components/UploadDropzone'
import RankingTable from '@/components/RankingTable'
import CandidateDrawer from '@/components/CandidateDrawer'
import ExportDialog from '@/components/ExportDialog'
import SharePanel from '@/components/SharePanel'
import AuditPanel from '@/components/AuditPanel'
import type { HrStatus, Recommendation } from '@/types'

const PAGE_SIZE = 50
const POLL_MS = 3000

type Tab = 'ranking' | 'share' | 'audit'

export default function SessionDetailPage() {
  const { sessionId = '' } = useParams()
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()

  const [tab, setTab] = useState<Tab>('ranking')
  const [search, setSearch] = useState('')
  const [recommendation, setRecommendation] = useState('')
  const [hrStatus, setHrStatus] = useState('')
  const [minScore, setMinScore] = useState('')
  const [sort, setSort] = useState('-score')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [activeId, setActiveId] = useState<string | null>(null)
  const [showExport, setShowExport] = useState(false)
  const [confirm, setConfirm] = useState<null | 'close' | 'archive'>(null)

  const session = useQuery({
    queryKey: ['session', sessionId],
    queryFn: () => sessionsApi.get(sessionId),
  })

  const settings = useQuery({ queryKey: ['settings'], queryFn: settingsApi.get })

  const filters = { search, recommendation, hr_status: hrStatus, min_score: minScore, sort, page }

  const candidates = useQuery({
    queryKey: ['candidates', sessionId, filters],
    queryFn: () =>
      candidatesApi.list(sessionId, {
        search: search || undefined,
        recommendation: recommendation || undefined,
        hr_status: hrStatus || undefined,
        min_score: minScore ? Number(minScore) : undefined,
        sort,
        page,
        page_size: PAGE_SIZE,
      }),
    // Poll every 3s while anything is still queued or being analysed.
    refetchInterval: (result) =>
      (result.state.data?.pending_count ?? 0) > 0 ? POLL_MS : false,
  })

  const stats = useQuery({
    queryKey: ['stats', sessionId],
    queryFn: () => sessionsApi.stats(sessionId),
    refetchInterval: (candidates.data?.pending_count ?? 0) > 0 ? POLL_MS : false,
  })

  const bulk = useMutation({
    mutationFn: (status: HrStatus) =>
      candidatesApi.bulkStatus(sessionId, Array.from(selected), status),
    onSuccess: () => {
      setSelected(new Set())
      void queryClient.invalidateQueries({ queryKey: ['candidates', sessionId] })
      void queryClient.invalidateQueries({ queryKey: ['stats', sessionId] })
      void queryClient.invalidateQueries({ queryKey: ['audit', sessionId] })
    },
  })

  const transition = useMutation({
    mutationFn: (action: 'open' | 'close' | 'archive') => sessionsApi[action](sessionId),
    onSuccess: () => {
      setConfirm(null)
      void queryClient.invalidateQueries({ queryKey: ['session', sessionId] })
      void queryClient.invalidateQueries({ queryKey: ['sessions'] })
    },
  })

  const items = candidates.data?.items ?? []
  const totalPages = Math.max(1, Math.ceil((candidates.data?.total ?? 0) / PAGE_SIZE))
  const filtered = Boolean(search || recommendation || hrStatus || minScore)

  const hasCriteria = (session.data?.criteria.length ?? 0) > 0
  const pendingCount = candidates.data?.pending_count ?? 0

  const clearFilters = useMemo(
    () => () => {
      setSearch('')
      setRecommendation('')
      setHrStatus('')
      setMinScore('')
      setPage(1)
    },
    [],
  )

  if (session.isLoading) return <PageLoader />
  if (session.isError || !session.data) {
    return <ErrorState error={session.error} onRetry={() => void session.refetch()} />
  }

  const data = session.data

  return (
    <div className="space-y-6">
      {/* header */}
      <div>
        <Link to="/sessions" className="btn-ghost -ml-2 mb-2">
          ← {t('detail.backToSessions')}
        </Link>

        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-xl font-semibold tracking-tight text-ink-900">{data.title}</h1>
              <Badge tone={SESSION_STATUS_TONE[data.status]}>{t(`status.${data.status}`)}</Badge>
            </div>
            <p className="mt-1 text-sm text-ink-500">
              {data.position}
              {data.department ? ` · ${data.department}` : ''} ·{' '}
              {t('sessions.criteriaCount', { count: data.criteria.length })}
            </p>
          </div>

          <div className="flex flex-wrap gap-2">
            <Link to={`/sessions/${sessionId}/edit`} className="btn-secondary">
              {t('detail.edit')}
            </Link>
            {data.status === 'DRAFT' && (
              <button
                type="button"
                className="btn-primary"
                disabled={!hasCriteria || transition.isPending}
                onClick={() => transition.mutate('open')}
              >
                {transition.isPending && <Spinner />}
                {t('detail.open')}
              </button>
            )}
            {data.status === 'OPEN' && (
              <button type="button" className="btn-secondary" onClick={() => setConfirm('close')}>
                {t('detail.close')}
              </button>
            )}
            {data.status !== 'ARCHIVED' && (
              <button type="button" className="btn-secondary" onClick={() => setConfirm('archive')}>
                {t('detail.archive')}
              </button>
            )}
            <button
              type="button"
              className="btn-primary"
              disabled={data.counts.total === 0}
              onClick={() => setShowExport(true)}
            >
              {t('export.title')}
            </button>
          </div>
        </div>
      </div>

      {/* tabs */}
      <div className="flex gap-1 border-b border-ink-200">
        {(['ranking', 'share', 'audit'] as Tab[]).map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => setTab(value)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
              tab === value
                ? 'border-ink-900 text-ink-900'
                : 'border-transparent text-ink-500 hover:text-ink-800'
            }`}
          >
            {value === 'ranking' ? t('ranking.title') : value === 'share' ? t('share.title') : t('detail.audit')}
          </button>
        ))}
      </div>

      {/* Retention deletes candidate files and rows. Never let that be a surprise. */}
      {data.retention_deletes_at && data.counts.total > 0 && (
        <Callout
          tone={new Date(`${data.retention_deletes_at}Z`) <= new Date() ? 'danger' : 'warning'}
          title={t('retention.title')}
        >
          {new Date(`${data.retention_deletes_at}Z`) <= new Date()
            ? t('retention.due', { count: data.counts.total })
            : t('retention.scheduled', {
                count: data.counts.total,
                date: formatDate(data.retention_deletes_at, i18n.resolvedLanguage ?? 'fr'),
              })}
        </Callout>
      )}

      {tab === 'share' && <SharePanel session={data} />}
      {tab === 'audit' && <AuditPanel sessionId={sessionId} />}

      {tab === 'ranking' && (
        <div className="space-y-5">
          {stats.data && stats.data.total_candidates > 0 && <StatsStrip stats={stats.data} />}

          <UploadDropzone
            sessionId={sessionId}
            maxUploadMb={settings.data?.max_upload_mb ?? 10}
            disabled={!hasCriteria}
            disabledReason={t('upload.noCriteria')}
          />

          {pendingCount > 0 && (
            <Callout tone="info">
              <span className="flex items-center gap-2">
                <Spinner />
                {t('ranking.analysing', { count: pendingCount })}
              </span>
            </Callout>
          )}

          {/* filters */}
          <div className="flex flex-wrap gap-2">
            <input
              className="input max-w-[220px]"
              placeholder={t('ranking.searchPlaceholder')}
              value={search}
              onChange={(event) => {
                setSearch(event.target.value)
                setPage(1)
              }}
            />
            <select
              className="input max-w-[190px]"
              value={recommendation}
              onChange={(event) => {
                setRecommendation(event.target.value)
                setPage(1)
              }}
            >
              <option value="">{t('ranking.allRecommendations')}</option>
              {(['STRONG_FIT', 'FIT', 'MAYBE', 'NOT_FIT'] as Recommendation[]).map((value) => (
                <option key={value} value={value}>
                  {t(`recommendation.${value}`)}
                </option>
              ))}
            </select>
            <select
              className="input max-w-[180px]"
              value={hrStatus}
              onChange={(event) => {
                setHrStatus(event.target.value)
                setPage(1)
              }}
            >
              <option value="">{t('ranking.allStatuses')}</option>
              {(['NEW', 'SHORTLISTED', 'MAYBE', 'REJECTED'] as HrStatus[]).map((value) => (
                <option key={value} value={value}>
                  {t(`hrStatus.${value}`)}
                </option>
              ))}
            </select>
            <input
              type="number"
              min={0}
              max={100}
              className="input max-w-[140px]"
              placeholder={t('ranking.minScore')}
              value={minScore}
              onChange={(event) => {
                setMinScore(event.target.value)
                setPage(1)
              }}
            />
            <select
              className="input ml-auto max-w-[190px]"
              value={sort}
              onChange={(event) => setSort(event.target.value)}
            >
              <option value="-score">{t('ranking.sortScoreDesc')}</option>
              <option value="score">{t('ranking.sortScoreAsc')}</option>
              <option value="-date">{t('ranking.sortDateDesc')}</option>
              <option value="date">{t('ranking.sortDateAsc')}</option>
              <option value="name">{t('ranking.sortName')}</option>
            </select>
          </div>

          {/* bulk bar */}
          {selected.size > 0 && (
            <div className="flex flex-wrap items-center gap-3 rounded-lg border border-ink-300 bg-ink-900 px-4 py-2.5 text-white">
              <span className="text-sm font-medium">
                {t('ranking.selected', { count: selected.size })}
              </span>
              <button
                type="button"
                className="btn bg-white/10 px-3 py-1 text-sm text-white hover:bg-white/20"
                disabled={bulk.isPending}
                onClick={() => bulk.mutate('SHORTLISTED')}
              >
                {t('ranking.bulkShortlist')}
              </button>
              <button
                type="button"
                className="btn bg-white/10 px-3 py-1 text-sm text-white hover:bg-white/20"
                disabled={bulk.isPending}
                onClick={() => bulk.mutate('REJECTED')}
              >
                {t('ranking.bulkReject')}
              </button>
              <button
                type="button"
                className="ml-auto text-sm text-white/70 hover:text-white"
                onClick={() => setSelected(new Set())}
              >
                {t('ranking.bulkClear')}
              </button>
            </div>
          )}

          {candidates.isLoading ? (
            <PageLoader />
          ) : candidates.isError ? (
            <ErrorState error={candidates.error} onRetry={() => void candidates.refetch()} />
          ) : items.length === 0 ? (
            <EmptyState
              title={filtered ? t('ranking.emptyFiltered') : t('ranking.empty')}
              hint={filtered ? undefined : t('ranking.emptyHint')}
              action={
                filtered && (
                  <button type="button" className="btn-secondary" onClick={clearFilters}>
                    {t('ranking.clearFilters')}
                  </button>
                )
              }
            />
          ) : (
            <>
              <RankingTable
                items={items}
                selected={selected}
                activeId={activeId}
                onOpen={setActiveId}
                onToggle={(id) =>
                  setSelected((current) => {
                    const next = new Set(current)
                    if (next.has(id)) next.delete(id)
                    else next.add(id)
                    return next
                  })
                }
                onToggleAll={() =>
                  setSelected((current) =>
                    items.every((item) => current.has(item.id))
                      ? new Set()
                      : new Set(items.map((item) => item.id)),
                  )
                }
              />

              {totalPages > 1 && (
                <div className="flex items-center justify-between">
                  <p className="text-xs text-ink-500">
                    {t('ranking.page', { page, pages: totalPages })}
                  </p>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      className="btn-secondary"
                      disabled={page <= 1}
                      onClick={() => setPage((current) => current - 1)}
                    >
                      {t('ranking.previous')}
                    </button>
                    <button
                      type="button"
                      className="btn-secondary"
                      disabled={page >= totalPages}
                      onClick={() => setPage((current) => current + 1)}
                    >
                      {t('ranking.next')}
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {activeId && (
        <CandidateDrawer
          candidateId={activeId}
          sessionId={sessionId}
          provider={settings.data?.llm_provider ?? 'the provider'}
          onClose={() => setActiveId(null)}
        />
      )}

      <ExportDialog
        open={showExport}
        onClose={() => setShowExport(false)}
        sessionId={sessionId}
        threshold={data.score_threshold}
      />

      <Modal
        open={confirm !== null}
        onClose={() => setConfirm(null)}
        title={confirm === 'close' ? t('detail.close') : t('detail.archive')}
        footer={
          <>
            <button type="button" className="btn-secondary" onClick={() => setConfirm(null)}>
              {t('app.cancel')}
            </button>
            <button
              type="button"
              className="btn-primary"
              disabled={transition.isPending}
              onClick={() => confirm && transition.mutate(confirm)}
            >
              {transition.isPending && <Spinner />}
              {t('app.confirm')}
            </button>
          </>
        }
      >
        <p>{confirm === 'close' ? t('detail.confirmClose') : t('detail.confirmArchive')}</p>
      </Modal>
    </div>
  )
}
