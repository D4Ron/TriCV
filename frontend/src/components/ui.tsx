import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { SCORE_BG, SCORE_TEXT, formatScore, scoreTone } from '@/lib/format'

export function Spinner({ className = 'h-4 w-4' }: { className?: string }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" className="opacity-20" />
      <path
        d="M22 12a10 10 0 0 0-10-10"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  )
}

export function PageLoader() {
  const { t } = useTranslation()
  return (
    <div className="flex items-center justify-center gap-3 py-24 text-ink-500">
      <Spinner className="h-5 w-5" />
      <span className="text-sm">{t('app.loading')}</span>
    </div>
  )
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useTranslation()
  const message = error instanceof Error ? error.message : t('app.error')
  return (
    <div className="card p-8 text-center">
      <p className="text-sm font-medium text-ink-900">{t('app.error')}</p>
      <p className="mt-1 text-sm text-ink-500">{message}</p>
      {onRetry && (
        <button type="button" className="btn-secondary mt-4" onClick={onRetry}>
          {t('app.retry')}
        </button>
      )}
    </div>
  )
}

export function EmptyState({
  title,
  hint,
  action,
  icon,
}: {
  title: string
  hint?: string
  action?: ReactNode
  icon?: ReactNode
}) {
  return (
    <div className="card flex flex-col items-center px-8 py-14 text-center">
      {icon && <div className="mb-4 text-ink-300">{icon}</div>}
      <p className="text-sm font-medium text-ink-900">{title}</p>
      {hint && <p className="mt-1 max-w-sm text-sm text-ink-500">{hint}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

export function Badge({
  children,
  tone = 'bg-ink-100 text-ink-700',
  title,
}: {
  children: ReactNode
  tone?: string
  title?: string
}) {
  return (
    <span className={`badge ${tone}`} title={title}>
      {children}
    </span>
  )
}

/** Score with a proportional bar. The number stays readable on its own. */
export function ScoreBar({
  score,
  showBar = true,
  size = 'md',
}: {
  score: number | null | undefined
  showBar?: boolean
  size?: 'sm' | 'md'
}) {
  const tone = scoreTone(score)
  return (
    <div className="flex items-center gap-2">
      <span
        className={`font-semibold tabular-nums ${SCORE_TEXT[tone]} ${
          size === 'sm' ? 'text-sm' : 'text-base'
        }`}
      >
        {formatScore(score)}
      </span>
      {showBar && (
        <span className="h-1.5 w-16 overflow-hidden rounded-full bg-ink-100" aria-hidden="true">
          <span
            className={`block h-full rounded-full ${SCORE_BG[tone]}`}
            style={{ width: `${Math.max(0, Math.min(100, score ?? 0))}%` }}
          />
        </span>
      )}
    </div>
  )
}

export function Field({
  label,
  hint,
  error,
  children,
  htmlFor,
}: {
  label: string
  hint?: string
  error?: string
  children: ReactNode
  htmlFor?: string
}) {
  return (
    <div>
      <label className="label" htmlFor={htmlFor}>
        {label}
      </label>
      {children}
      {error ? (
        <p className="mt-1 text-xs text-red-600">{error}</p>
      ) : (
        hint && <p className="hint">{hint}</p>
      )}
    </div>
  )
}

export function Toggle({
  checked,
  onChange,
  label,
  hint,
  disabled,
}: {
  checked: boolean
  onChange: (value: boolean) => void
  label: string
  hint?: string
  disabled?: boolean
}) {
  return (
    <label className={`flex items-start gap-3 ${disabled ? 'opacity-60' : 'cursor-pointer'}`}>
      <input
        type="checkbox"
        className="mt-0.5 h-4 w-4 rounded border-ink-300 text-ink-900 focus:ring-brand-500"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span>
        <span className="block text-sm text-ink-800">{label}</span>
        {hint && <span className="mt-0.5 block text-xs text-ink-500">{hint}</span>}
      </span>
    </label>
  )
}

export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  tone = 'neutral',
}: {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  footer?: ReactNode
  tone?: 'neutral' | 'danger'
}) {
  const { t } = useTranslation()
  if (!open) return null
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/40 p-4"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-xl bg-white shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 border-b border-ink-200 px-5 py-4">
          <h2
            className={`text-base font-semibold ${
              tone === 'danger' ? 'text-red-700' : 'text-ink-900'
            }`}
          >
            {title}
          </h2>
          <button
            type="button"
            className="btn-ghost -my-1 px-2 py-1 text-lg leading-none"
            onClick={onClose}
            aria-label={t('app.close')}
          >
            ×
          </button>
        </div>
        {/* Un profil complet ou un aperçu de boîte dépasse l'écran : c'est le
            contenu qui défile, pas la fenêtre, sinon l'en-tête et les boutons
            sortent du champ. */}
        <div className="max-h-[75vh] overflow-y-auto px-5 py-4 text-sm text-ink-700">
          {children}
        </div>
        {footer && (
          <div className="flex justify-end gap-2 border-t border-ink-200 px-5 py-3">{footer}</div>
        )}
      </div>
    </div>
  )
}

export function Callout({
  tone = 'info',
  title,
  children,
}: {
  tone?: 'info' | 'warning' | 'danger' | 'success'
  title?: string
  children: ReactNode
}) {
  const tones = {
    info: 'border-brand-200 bg-brand-50 text-brand-900',
    warning: 'border-amber-200 bg-amber-50 text-amber-900',
    danger: 'border-red-200 bg-red-50 text-red-900',
    success: 'border-emerald-200 bg-emerald-50 text-emerald-900',
  }
  return (
    <div className={`rounded-lg border px-4 py-3 text-sm ${tones[tone]}`}>
      {title && <p className="font-semibold">{title}</p>}
      <div className={title ? 'mt-1' : ''}>{children}</div>
    </div>
  )
}

export function CopyField({ value, label }: { value: string; label?: string }) {
  const { t } = useTranslation()
  return (
    <div className="flex gap-2">
      <input className="input font-mono text-xs" readOnly value={value} aria-label={label} />
      <button
        type="button"
        className="btn-secondary shrink-0"
        onClick={() => {
          void navigator.clipboard.writeText(value)
        }}
      >
        {t('app.copy')}
      </button>
    </div>
  )
}
