import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { settingsApi } from '@/lib/api'
import { Callout, ErrorState, PageLoader } from '@/components/ui'

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-6 border-b border-ink-100 py-2.5 last:border-0">
      <dt className="text-sm text-ink-500">{label}</dt>
      <dd className="text-sm font-medium text-ink-900">{value}</dd>
    </div>
  )
}

export default function SettingsPage() {
  const { t } = useTranslation()
  const query = useQuery({ queryKey: ['settings'], queryFn: settingsApi.get })

  if (query.isLoading) return <PageLoader />
  if (query.isError || !query.data) {
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} />
  }

  const settings = query.data

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-ink-900">{t('settings.title')}</h1>
        <p className="mt-1 text-sm text-ink-500">{t('settings.subtitle')}</p>
      </div>

      {/* The privacy posture is the point of this page — put it first. */}
      <Callout tone={settings.pii_redaction ? 'success' : 'warning'} title={t('settings.redaction')}>
        {settings.pii_redaction ? t('settings.redactionOn') : t('settings.redactionOff')}
      </Callout>

      <Callout
        tone={settings.redact_demographics ? 'success' : 'danger'}
        title={
          settings.redact_demographics
            ? t('settings.demographics')
            : `${t('settings.warning')} — ${t('settings.demographics')}`
        }
      >
        {settings.redact_demographics
          ? t('settings.demographicsOn')
          : t('settings.demographicsOff')}
      </Callout>

      <dl className="card px-5 py-3">
        <Row label={t('settings.provider')} value={settings.llm_provider} />
        <Row label={t('settings.model')} value={settings.llm_model} />
        <Row label={t('settings.storage')} value={settings.storage_backend} />
        <Row label={t('settings.maxUpload')} value={`${settings.max_upload_mb} MB`} />
        <Row
          label={t('settings.nerModels')}
          value={
            settings.spacy_models_loaded.length > 0
              ? settings.spacy_models_loaded.join(', ')
              : t('settings.nerNone')
          }
        />
      </dl>
    </div>
  )
}
