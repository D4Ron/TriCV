import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { sessionsApi, type SessionPayload } from '@/lib/api'
import { Callout, Field, PageLoader, Spinner, Toggle } from '@/components/ui'
import type { CriterionDraft, Language } from '@/types'

interface DraftCriterion {
  key: string
  name: string
  description: string
  weight: number
  is_must_have: boolean
}

let counter = 0
const nextKey = () => `c${++counter}`

function blankCriterion(): DraftCriterion {
  return { key: nextKey(), name: '', description: '', weight: 5, is_must_have: false }
}

export default function SessionBuilderPage() {
  const { sessionId } = useParams()
  const editing = Boolean(sessionId)
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const existing = useQuery({
    queryKey: ['session', sessionId],
    queryFn: () => sessionsApi.get(sessionId!),
    enabled: editing,
  })

  const [title, setTitle] = useState('')
  const [position, setPosition] = useState('')
  const [department, setDepartment] = useState('')
  const [description, setDescription] = useState('')
  const [language, setLanguage] = useState<Language>('fr')
  const [threshold, setThreshold] = useState(60)
  const [retentionDays, setRetentionDays] = useState<string>('')
  const [publicApplications, setPublicApplications] = useState(true)
  const [criteria, setCriteria] = useState<DraftCriterion[]>([blankCriterion()])
  const [errors, setErrors] = useState<Record<string, string>>({})

  const [rawText, setRawText] = useState('')
  const [drafts, setDrafts] = useState<CriterionDraft[] | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)

  const locked = existing.data?.criteria_locked ?? false

  useEffect(() => {
    const session = existing.data
    if (!session) return
    setTitle(session.title)
    setPosition(session.position)
    setDepartment(session.department ?? '')
    setDescription(session.description ?? '')
    setLanguage(session.language)
    setThreshold(session.score_threshold)
    setRetentionDays(session.retention_days ? String(session.retention_days) : '')
    setPublicApplications(session.accepts_public_applications)
    setCriteria(
      session.criteria.length
        ? session.criteria.map((criterion) => ({
            key: criterion.id,
            name: criterion.name,
            description: criterion.description ?? '',
            weight: criterion.weight,
            is_must_have: criterion.is_must_have,
          }))
        : [blankCriterion()],
    )
  }, [existing.data])

  // A default language for a brand new session follows the UI language.
  useEffect(() => {
    if (!editing) setLanguage((i18n.resolvedLanguage === 'en' ? 'en' : 'fr') as Language)
  }, [editing, i18n.resolvedLanguage])

  const structure = useMutation({
    mutationFn: () => sessionsApi.structureFiche(rawText, language),
    onSuccess: (data) => setDrafts(data.criteria),
  })

  const filledCriteria = useMemo(
    () => criteria.filter((criterion) => criterion.name.trim().length > 0),
    [criteria],
  )

  function buildPayload(status?: string): SessionPayload {
    return {
      title: title.trim(),
      position: position.trim(),
      description: description.trim() || null,
      department: department.trim() || null,
      language,
      score_threshold: threshold,
      accepts_public_applications: publicApplications,
      retention_days: retentionDays ? Number(retentionDays) : null,
      ...(status ? { status } : {}),
      ...(locked
        ? {}
        : {
            criteria: filledCriteria.map((criterion, index) => ({
              name: criterion.name.trim(),
              description: criterion.description.trim() || null,
              weight: criterion.weight,
              is_must_have: criterion.is_must_have,
              display_order: index,
            })),
          }),
    }
  }

  function validate(openNow: boolean): boolean {
    const found: Record<string, string> = {}
    if (!title.trim()) found.title = t('builder.validation.titleRequired')
    if (!position.trim()) found.position = t('builder.validation.positionRequired')
    if (!locked && openNow && filledCriteria.length === 0) {
      found.criteria = t('builder.validation.criteriaRequired')
    }
    if (!locked && criteria.some((criterion) => !criterion.name.trim() && criterion.description)) {
      found.criteria = t('builder.validation.criterionNameRequired')
    }
    setErrors(found)
    return Object.keys(found).length === 0
  }

  const save = useMutation({
    mutationFn: async (openNow: boolean) => {
      const payload = buildPayload(openNow ? 'OPEN' : undefined)
      return editing
        ? sessionsApi.update(sessionId!, payload)
        : sessionsApi.create({ ...payload, status: openNow ? 'OPEN' : 'DRAFT' })
    },
    onSuccess: (session) => {
      void queryClient.invalidateQueries({ queryKey: ['sessions'] })
      void queryClient.invalidateQueries({ queryKey: ['session', session.id] })
      navigate(`/sessions/${session.id}`)
    },
    onError: (error) => setSaveError(error instanceof Error ? error.message : t('app.error')),
  })

  function submit(openNow: boolean) {
    setSaveError(null)
    if (!validate(openNow)) return
    save.mutate(openNow)
  }

  function updateCriterion(key: string, patch: Partial<DraftCriterion>) {
    setCriteria((current) =>
      current.map((criterion) => (criterion.key === key ? { ...criterion, ...patch } : criterion)),
    )
  }

  function moveCriterion(index: number, delta: number) {
    setCriteria((current) => {
      const next = [...current]
      const target = index + delta
      if (target < 0 || target >= next.length) return current
      ;[next[index], next[target]] = [next[target], next[index]]
      return next
    })
  }

  function applyDrafts(replace: boolean) {
    if (!drafts) return
    const mapped: DraftCriterion[] = drafts.map((draft) => ({
      key: nextKey(),
      name: draft.name,
      description: draft.description ?? '',
      weight: draft.weight,
      is_must_have: draft.is_must_have,
    }))
    setCriteria((current) =>
      replace ? mapped : [...current.filter((criterion) => criterion.name.trim()), ...mapped],
    )
    setDrafts(null)
    setRawText('')
  }

  if (editing && existing.isLoading) return <PageLoader />

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <Link to={editing ? `/sessions/${sessionId}` : '/sessions'} className="btn-ghost -ml-2 mb-2">
          ← {editing ? t('app.back') : t('detail.backToSessions')}
        </Link>
        <h1 className="text-xl font-semibold tracking-tight text-ink-900">
          {editing ? t('builder.titleEdit') : t('builder.titleNew')}
        </h1>
      </div>

      {/* --- role details --- */}
      <section className="card space-y-4 p-6">
        <h2 className="text-sm font-semibold text-ink-900">{t('builder.details')}</h2>

        <Field label={t('builder.fieldTitle')} error={errors.title} htmlFor="title">
          <input
            id="title"
            className="input"
            placeholder={t('builder.fieldTitlePlaceholder')}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
        </Field>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t('builder.fieldPosition')} error={errors.position} htmlFor="position">
            <input
              id="position"
              className="input"
              placeholder={t('builder.fieldPositionPlaceholder')}
              value={position}
              onChange={(event) => setPosition(event.target.value)}
            />
          </Field>
          <Field label={t('builder.fieldDepartment')} htmlFor="department">
            <input
              id="department"
              className="input"
              placeholder={t('builder.fieldDepartmentPlaceholder')}
              value={department}
              onChange={(event) => setDepartment(event.target.value)}
            />
          </Field>
        </div>

        <Field
          label={t('builder.fieldDescription')}
          hint={t('builder.fieldDescriptionHint')}
          htmlFor="description"
        >
          <textarea
            id="description"
            className="input min-h-[96px] resize-y"
            placeholder={t('builder.fieldDescriptionPlaceholder')}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </Field>

        <div className="grid gap-4 sm:grid-cols-3">
          <Field
            label={t('builder.fieldLanguage')}
            hint={t('builder.fieldLanguageHint')}
            htmlFor="language"
          >
            <select
              id="language"
              className="input"
              value={language}
              onChange={(event) => setLanguage(event.target.value as Language)}
            >
              <option value="fr">Français</option>
              <option value="en">English</option>
            </select>
          </Field>
          <Field
            label={t('builder.fieldThreshold')}
            hint={t('builder.fieldThresholdHint')}
            htmlFor="threshold"
          >
            <input
              id="threshold"
              type="number"
              min={0}
              max={100}
              className="input"
              value={threshold}
              onChange={(event) => setThreshold(Number(event.target.value))}
            />
          </Field>
          <Field
            label={t('builder.fieldRetention')}
            hint={t('builder.fieldRetentionHint')}
            htmlFor="retention"
          >
            <input
              id="retention"
              type="number"
              min={1}
              max={3650}
              className="input"
              value={retentionDays}
              onChange={(event) => setRetentionDays(event.target.value)}
            />
          </Field>
        </div>

        <Toggle
          checked={publicApplications}
          onChange={setPublicApplications}
          label={t('builder.fieldPublicApplications')}
        />
      </section>

      {/* --- paste a job description --- */}
      {!locked && (
        <section className="card space-y-3 p-6">
          <div>
            <h2 className="text-sm font-semibold text-ink-900">{t('builder.paste')}</h2>
            <p className="mt-1 text-xs text-ink-500">{t('builder.pasteHint')}</p>
          </div>

          <textarea
            className="input min-h-[110px] resize-y"
            placeholder={t('builder.pastePlaceholder')}
            value={rawText}
            onChange={(event) => setRawText(event.target.value)}
          />

          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              className="btn-secondary"
              disabled={rawText.trim().length < 20 || structure.isPending}
              onClick={() => structure.mutate()}
            >
              {structure.isPending && <Spinner />}
              {structure.isPending ? t('builder.pasteWorking') : t('builder.pasteAction')}
            </button>
            {rawText.trim().length > 0 && rawText.trim().length < 20 && (
              <span className="text-xs text-ink-500">{t('builder.pasteTooShort')}</span>
            )}
          </div>

          {structure.isError && (
            <Callout tone="danger">
              {structure.error instanceof Error ? structure.error.message : t('app.error')}
            </Callout>
          )}

          {drafts && (
            <div className="rounded-lg border border-brand-200 bg-brand-50 p-4">
              <p className="text-sm font-semibold text-brand-900">{t('builder.pasteResultTitle')}</p>
              <p className="mt-1 text-xs text-brand-800">{t('builder.pasteResultHint')}</p>
              <ul className="mt-3 space-y-2">
                {drafts.map((draft, index) => (
                  <li key={index} className="rounded-md bg-white px-3 py-2 text-sm">
                    <div className="flex items-center justify-between gap-3">
                      <span className="font-medium text-ink-900">{draft.name}</span>
                      <span className="shrink-0 text-xs text-ink-500">
                        {t('builder.weight')} {draft.weight}/10
                        {draft.is_must_have ? ` · ${t('builder.mustHave')}` : ''}
                      </span>
                    </div>
                    {draft.description && (
                      <p className="mt-0.5 text-xs text-ink-500">{draft.description}</p>
                    )}
                  </li>
                ))}
              </ul>
              <div className="mt-3 flex flex-wrap gap-2">
                <button type="button" className="btn-primary" onClick={() => applyDrafts(false)}>
                  {t('builder.pasteApply')}
                </button>
                <button type="button" className="btn-secondary" onClick={() => applyDrafts(true)}>
                  {t('builder.pasteReplace')}
                </button>
                <button type="button" className="btn-ghost" onClick={() => setDrafts(null)}>
                  {t('builder.pasteDismiss')}
                </button>
              </div>
            </div>
          )}
        </section>
      )}

      {/* --- criteria editor --- */}
      <section className="card space-y-4 p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-sm font-semibold text-ink-900">{t('builder.criteria')}</h2>
            <p className="mt-1 text-xs text-ink-500">{t('builder.criteriaHint')}</p>
          </div>
          {!locked && (
            <button
              type="button"
              className="btn-secondary shrink-0"
              onClick={() => setCriteria((current) => [...current, blankCriterion()])}
            >
              + {t('builder.addCriterion')}
            </button>
          )}
        </div>

        {locked && (
          <Callout tone="warning" title={t('builder.locked')}>
            <p>{t('builder.lockedHint')}</p>
            <button
              type="button"
              className="btn-secondary mt-3"
              onClick={() => {
                void sessionsApi.duplicate(sessionId!).then((copy) => {
                  void queryClient.invalidateQueries({ queryKey: ['sessions'] })
                  navigate(`/sessions/${copy.id}/edit`)
                })
              }}
            >
              {t('builder.duplicate')}
            </button>
          </Callout>
        )}

        {errors.criteria && <p className="text-xs text-red-600">{errors.criteria}</p>}

        {criteria.length === 0 ? (
          <p className="py-6 text-center text-sm text-ink-500">
            {t('builder.noCriteria')} <span className="text-ink-400">{t('builder.noCriteriaHint')}</span>
          </p>
        ) : (
          <ul className="space-y-3">
            {criteria.map((criterion, index) => (
              <li key={criterion.key} className="rounded-lg border border-ink-200 p-4">
                <div className="flex items-start gap-3">
                  <span className="mt-2 w-5 shrink-0 text-center text-xs font-semibold text-ink-400">
                    {index + 1}
                  </span>

                  <div className="min-w-0 flex-1 space-y-3">
                    <input
                      className="input font-medium"
                      placeholder={t('builder.criterionNamePlaceholder')}
                      aria-label={t('builder.criterionName')}
                      disabled={locked}
                      value={criterion.name}
                      onChange={(event) =>
                        updateCriterion(criterion.key, { name: event.target.value })
                      }
                    />
                    <textarea
                      className="input min-h-[56px] resize-y text-sm"
                      placeholder={t('builder.criterionDescriptionPlaceholder')}
                      aria-label={t('builder.criterionDescription')}
                      disabled={locked}
                      value={criterion.description}
                      onChange={(event) =>
                        updateCriterion(criterion.key, { description: event.target.value })
                      }
                    />

                    <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
                      <label className="flex items-center gap-3">
                        <span className="text-xs font-medium text-ink-600">
                          {t('builder.weight')}
                        </span>
                        <input
                          type="range"
                          min={1}
                          max={10}
                          disabled={locked}
                          className="h-1 w-32 accent-ink-900"
                          value={criterion.weight}
                          onChange={(event) =>
                            updateCriterion(criterion.key, { weight: Number(event.target.value) })
                          }
                        />
                        <span className="w-8 text-xs font-semibold tabular-nums text-ink-900">
                          {criterion.weight}/10
                        </span>
                      </label>

                      <label className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          disabled={locked}
                          className="h-4 w-4 rounded border-ink-300 text-ink-900 focus:ring-brand-500"
                          checked={criterion.is_must_have}
                          onChange={(event) =>
                            updateCriterion(criterion.key, { is_must_have: event.target.checked })
                          }
                        />
                        <span className="text-xs font-medium text-ink-700">
                          {t('builder.mustHave')}
                        </span>
                      </label>
                    </div>
                  </div>

                  {!locked && (
                    <div className="flex shrink-0 flex-col gap-1">
                      <button
                        type="button"
                        className="btn-ghost px-2 py-0.5 text-xs"
                        aria-label={t('builder.moveUp')}
                        disabled={index === 0}
                        onClick={() => moveCriterion(index, -1)}
                      >
                        ↑
                      </button>
                      <button
                        type="button"
                        className="btn-ghost px-2 py-0.5 text-xs"
                        aria-label={t('builder.moveDown')}
                        disabled={index === criteria.length - 1}
                        onClick={() => moveCriterion(index, 1)}
                      >
                        ↓
                      </button>
                      <button
                        type="button"
                        className="btn-ghost px-2 py-0.5 text-xs text-red-600 hover:bg-red-50"
                        aria-label={t('builder.removeCriterion')}
                        onClick={() =>
                          setCriteria((current) =>
                            current.filter((item) => item.key !== criterion.key),
                          )
                        }
                      >
                        ×
                      </button>
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}

        {criteria.some((criterion) => criterion.is_must_have) && (
          <p className="text-xs text-ink-500">{t('builder.mustHaveHint')}</p>
        )}
      </section>

      {saveError && <Callout tone="danger">{saveError}</Callout>}

      <div className="flex flex-wrap justify-end gap-3 pb-8">
        <button
          type="button"
          className="btn-secondary"
          disabled={save.isPending}
          onClick={() => submit(false)}
        >
          {save.isPending && <Spinner />}
          {t('builder.save')}
        </button>
        <button
          type="button"
          className="btn-primary"
          disabled={save.isPending}
          onClick={() => submit(true)}
        >
          {save.isPending && <Spinner />}
          {t('builder.saveAndOpen')}
        </button>
      </div>
    </div>
  )
}
