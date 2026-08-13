import { useTranslation } from 'react-i18next'
import { API_URL } from '@/lib/api'
import { Callout, CopyField } from '@/components/ui'
import type { RecruitmentSession } from '@/types'

export default function SharePanel({ session }: { session: RecruitmentSession }) {
  const { t } = useTranslation()

  const applyUrl = `${window.location.origin}/apply/${session.public_key}`
  const widgetSnippet = [
    '<div id="tricv-widget"></div>',
    `<script src="${API_URL.replace(/\/$/, '')}/widget.js"`,
    `        data-session-key="${session.public_key}"`,
    `        data-lang="${session.language}"></script>`,
  ].join('\n')

  const accepting = session.accepts_public_applications && session.status === 'OPEN'

  return (
    <div className="card space-y-5 p-5">
      <h2 className="text-sm font-semibold text-ink-900">{t('share.title')}</h2>

      {!accepting && <Callout tone="warning">{t('share.closedWarning')}</Callout>}

      <div>
        <p className="label">{t('share.publicLink')}</p>
        <CopyField value={applyUrl} label={t('share.publicLink')} />
        <p className="hint">{t('share.publicLinkHint')}</p>
        <a
          className="btn-secondary mt-2"
          href={applyUrl}
          target="_blank"
          rel="noreferrer"
        >
          {t('share.preview')}
        </a>
      </div>

      <div>
        <p className="label">{t('share.widget')}</p>
        <pre className="overflow-x-auto rounded-lg border border-ink-200 bg-ink-50 p-3 text-[11px] leading-relaxed text-ink-700">
          {widgetSnippet}
        </pre>
        <div className="mt-2 flex justify-end">
          <button
            type="button"
            className="btn-secondary"
            onClick={() => void navigator.clipboard.writeText(widgetSnippet)}
          >
            {t('app.copy')}
          </button>
        </div>
        <p className="hint">{t('share.widgetHint')}</p>
      </div>
    </div>
  )
}
