import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { downloadExport } from '@/lib/api'
import { Callout, Modal, Spinner, Toggle } from '@/components/ui'

type Format = 'pdf' | 'xlsx' | 'docx'
type Scope = 'all' | 'shortlisted' | 'above_threshold'

const FORMAT_LABELS: Record<Format, string> = {
  pdf: 'PDF',
  xlsx: 'Excel (.xlsx)',
  docx: 'Word (.docx)',
}

export default function ExportDialog({
  open,
  onClose,
  sessionId,
  threshold,
}: {
  open: boolean
  onClose: () => void
  sessionId: string
  threshold: number
}) {
  const { t } = useTranslation()
  const [format, setFormat] = useState<Format>('pdf')
  const [scope, setScope] = useState<Scope>('all')
  const [includeCvs, setIncludeCvs] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function download() {
    setBusy(true)
    setError(null)
    try {
      await downloadExport(sessionId, format, scope, includeCvs)
      onClose()
    } catch {
      setError(t('export.failed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t('export.title')}
      footer={
        <>
          <button type="button" className="btn-secondary" onClick={onClose}>
            {t('app.cancel')}
          </button>
          <button type="button" className="btn-primary" disabled={busy} onClick={() => void download()}>
            {busy && <Spinner />}
            {busy ? t('export.working') : t('export.download')}
          </button>
        </>
      }
    >
      <div className="space-y-4">
        <div>
          <span className="label">{t('export.format')}</span>
          <div className="flex flex-wrap gap-2">
            {(Object.keys(FORMAT_LABELS) as Format[]).map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setFormat(value)}
                className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                  format === value
                    ? 'bg-ink-900 text-white'
                    : 'bg-white text-ink-600 ring-1 ring-ink-200 hover:bg-ink-50'
                }`}
              >
                {FORMAT_LABELS[value]}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="label" htmlFor="export-scope">
            {t('export.scope')}
          </label>
          <select
            id="export-scope"
            className="input"
            value={scope}
            onChange={(event) => setScope(event.target.value as Scope)}
          >
            <option value="all">{t('export.scopeAll')}</option>
            <option value="shortlisted">{t('export.scopeShortlisted')}</option>
            <option value="above_threshold">{t('export.scopeAboveThreshold', { threshold })}</option>
          </select>
        </div>

        <Toggle
          checked={includeCvs}
          onChange={setIncludeCvs}
          label={t('export.includeCvs')}
        />

        {error && <Callout tone="danger">{error}</Callout>}
      </div>
    </Modal>
  )
}
