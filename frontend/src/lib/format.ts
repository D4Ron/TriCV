import type { Recommendation } from '@/types'

/** Score bands mirror app/services/scoring.py — keep them in step. */
export function scoreTone(score: number | null | undefined): 'strong' | 'good' | 'maybe' | 'no' {
  if (score == null) return 'no'
  if (score >= 80) return 'strong'
  if (score >= 60) return 'good'
  if (score >= 40) return 'maybe'
  return 'no'
}

export const SCORE_TEXT: Record<string, string> = {
  strong: 'text-fit-strong',
  good: 'text-fit-good',
  maybe: 'text-fit-maybe',
  no: 'text-fit-no',
}

export const SCORE_BG: Record<string, string> = {
  strong: 'bg-fit-strong',
  good: 'bg-fit-good',
  maybe: 'bg-fit-maybe',
  no: 'bg-fit-no',
}

export const RECOMMENDATION_TONE: Record<Recommendation, string> = {
  STRONG_FIT: 'bg-emerald-50 text-emerald-800 ring-1 ring-emerald-200',
  FIT: 'bg-sky-50 text-sky-800 ring-1 ring-sky-200',
  MAYBE: 'bg-amber-50 text-amber-800 ring-1 ring-amber-200',
  NOT_FIT: 'bg-red-50 text-red-800 ring-1 ring-red-200',
}

export const HR_STATUS_TONE: Record<string, string> = {
  NEW: 'bg-ink-100 text-ink-700',
  SHORTLISTED: 'bg-emerald-100 text-emerald-800',
  MAYBE: 'bg-amber-100 text-amber-800',
  REJECTED: 'bg-red-100 text-red-800',
}

export const SESSION_STATUS_TONE: Record<string, string> = {
  DRAFT: 'bg-ink-100 text-ink-700',
  OPEN: 'bg-emerald-100 text-emerald-800',
  CLOSED: 'bg-amber-100 text-amber-800',
  ARCHIVED: 'bg-ink-200 text-ink-600',
}

export function formatDate(value: string | null | undefined, locale: string): string {
  if (!value) return '—'
  // The API sends naive UTC timestamps; mark them as UTC before formatting.
  const iso = value.endsWith('Z') || value.includes('+') ? value : `${value}Z`
  return new Intl.DateTimeFormat(locale, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  }).format(new Date(iso))
}

export function formatDateTime(value: string | null | undefined, locale: string): string {
  if (!value) return '—'
  const iso = value.endsWith('Z') || value.includes('+') ? value : `${value}Z`
  return new Intl.DateTimeFormat(locale, {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(iso))
}

export function formatScore(score: number | null | undefined): string {
  return score == null ? '—' : Math.round(score).toString()
}

export function initials(name: string | null | undefined): string {
  if (!name) return '?'
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('')
}
