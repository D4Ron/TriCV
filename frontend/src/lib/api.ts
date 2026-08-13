import { useAuthStore } from '@/store/auth'
import type {
  AuditEntry,
  CandidateDetail,
  CriterionDraft,
  DeploymentSettings,
  HrStatus,
  Language,
  PaginatedCandidates,
  PublicRole,
  PublicSession,
  RecruitmentSession,
  SessionListItem,
  SessionStats,
  UploadResponse,
  User,
} from '@/types'

export const API_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000'
const BASE = `${API_URL}/api/v1`

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

/** FastAPI returns `detail` as a string, or as a list of validation errors. */
function readDetail(body: unknown, fallback: string): string {
  if (typeof body === 'object' && body !== null && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail
        .map((item) =>
          typeof item === 'object' && item !== null && 'msg' in item
            ? String((item as { msg: unknown }).msg)
            : String(item),
        )
        .join(' · ')
    }
  }
  return fallback
}

interface RequestOptions {
  method?: string
  body?: unknown
  formData?: FormData
  auth?: boolean
  signal?: AbortSignal
}

let refreshInFlight: Promise<boolean> | null = null

/** One refresh at a time — a burst of 401s must not fan out into N refreshes. */
async function refreshOnce(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = useAuthStore
      .getState()
      .refresh()
      .finally(() => {
        refreshInFlight = null
      })
  }
  return refreshInFlight
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, formData, auth = true, signal } = options

  const send = async (): Promise<Response> => {
    const headers: Record<string, string> = {}
    if (body !== undefined) headers['Content-Type'] = 'application/json'
    if (auth) {
      const token = useAuthStore.getState().accessToken
      if (token) headers.Authorization = `Bearer ${token}`
    }
    return fetch(`${BASE}${path}`, {
      method,
      headers,
      body: formData ?? (body !== undefined ? JSON.stringify(body) : undefined),
      signal,
    })
  }

  let response = await send()

  if (response.status === 401 && auth && useAuthStore.getState().refreshToken) {
    if (await refreshOnce()) {
      response = await send()
    } else {
      useAuthStore.getState().logout()
    }
  }

  if (!response.ok) {
    let payload: unknown = null
    try {
      payload = await response.json()
    } catch {
      /* a non-JSON error body is fine — fall back to the status text */
    }
    throw new ApiError(response.status, readDetail(payload, response.statusText))
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

// --- auth -------------------------------------------------------------------

export const authApi = {
  login: (email: string, password: string) =>
    request<{ access_token: string; refresh_token: string; expires_in: number }>('/auth/login', {
      method: 'POST',
      body: { email, password },
      auth: false,
    }),
  refresh: (refreshToken: string) =>
    request<{ access_token: string; refresh_token: string; expires_in: number }>('/auth/refresh', {
      method: 'POST',
      body: { refresh_token: refreshToken },
      auth: false,
    }),
  me: () => request<User>('/auth/me'),
}

// --- sessions ---------------------------------------------------------------

export interface SessionPayload {
  title: string
  position: string
  description?: string | null
  department?: string | null
  language: Language
  status?: string
  score_threshold: number
  accepts_public_applications: boolean
  retention_days?: number | null
  criteria?: Array<{
    name: string
    description: string | null
    weight: number
    is_must_have: boolean
    display_order: number
  }>
}

export const sessionsApi = {
  list: (params: { status?: string; search?: string } = {}) => {
    const query = new URLSearchParams()
    if (params.status) query.set('status', params.status)
    if (params.search) query.set('search', params.search)
    const suffix = query.toString()
    return request<SessionListItem[]>(`/sessions${suffix ? `?${suffix}` : ''}`)
  },
  get: (id: string) => request<RecruitmentSession>(`/sessions/${id}`),
  create: (payload: SessionPayload) =>
    request<RecruitmentSession>('/sessions', { method: 'POST', body: payload }),
  update: (id: string, payload: Partial<SessionPayload>) =>
    request<RecruitmentSession>(`/sessions/${id}`, { method: 'PATCH', body: payload }),
  duplicate: (id: string, title?: string) =>
    request<RecruitmentSession>(`/sessions/${id}/duplicate`, {
      method: 'POST',
      body: { title: title ?? null },
    }),
  open: (id: string) => request<RecruitmentSession>(`/sessions/${id}/open`, { method: 'POST' }),
  close: (id: string) => request<RecruitmentSession>(`/sessions/${id}/close`, { method: 'POST' }),
  archive: (id: string) =>
    request<RecruitmentSession>(`/sessions/${id}/archive`, { method: 'POST' }),
  structureFiche: (rawText: string, language: Language) =>
    request<{ criteria: CriterionDraft[] }>('/sessions/structure-fiche', {
      method: 'POST',
      body: { raw_text: rawText, language },
    }),
  stats: (id: string) => request<SessionStats>(`/sessions/${id}/stats`),
  audit: (id: string) => request<AuditEntry[]>(`/sessions/${id}/audit`),
}

// --- candidates -------------------------------------------------------------

export interface CandidateQuery {
  status?: string
  hr_status?: string
  recommendation?: string
  min_score?: number
  search?: string
  sort?: string
  page?: number
  page_size?: number
}

export const candidatesApi = {
  list: (sessionId: string, query: CandidateQuery = {}) => {
    const params = new URLSearchParams()
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') params.set(key, String(value))
    })
    const suffix = params.toString()
    return request<PaginatedCandidates>(
      `/sessions/${sessionId}/candidates${suffix ? `?${suffix}` : ''}`,
    )
  },
  get: (id: string) => request<CandidateDetail>(`/candidates/${id}`),
  upload: (sessionId: string, files: File[], meta?: { full_name?: string; email?: string }) => {
    const formData = new FormData()
    files.forEach((file) => formData.append('files', file))
    if (meta?.full_name) formData.append('full_name', meta.full_name)
    if (meta?.email) formData.append('email', meta.email)
    return request<UploadResponse>(`/sessions/${sessionId}/candidates`, {
      method: 'POST',
      formData,
    })
  },
  update: (
    id: string,
    payload: {
      hr_status?: HrStatus
      hr_notes?: string
      manual_score?: number
      clear_manual_score?: boolean
    },
  ) => request<CandidateDetail>(`/candidates/${id}`, { method: 'PATCH', body: payload }),
  bulkStatus: (sessionId: string, candidateIds: string[], hrStatus: HrStatus) =>
    request<{ updated: number }>(`/sessions/${sessionId}/candidates/bulk`, {
      method: 'POST',
      body: { candidate_ids: candidateIds, hr_status: hrStatus },
    }),
  reanalyze: (id: string, fullDocument = false) =>
    request<{ status: string }>(`/candidates/${id}/reanalyze`, {
      method: 'POST',
      body: { full_document: fullDocument },
    }),
  redactionPreview: (id: string) =>
    request<{
      redaction_applied: boolean
      mode: string | null
      counts: Record<string, number>
      summary_en: string
      summary_fr: string
      payload_sent: string | null
      demographics_visible_to_hr: Record<string, string> | null
    }>(`/candidates/${id}/redaction-preview`),
  remove: (id: string) => request<void>(`/candidates/${id}`, { method: 'DELETE' }),
  /**
   * The CV endpoint requires a bearer token, and neither <iframe src> nor a
   * plain <a href> can send one — they render the raw 401 body instead. So
   * fetch it with the token and hand back an object URL. The caller owns it
   * and must revoke it.
   */
  cvObjectUrl: async (id: string): Promise<string> => {
    const response = await fetch(`${BASE}/candidates/${id}/cv`, {
      headers: { Authorization: `Bearer ${useAuthStore.getState().accessToken ?? ''}` },
    })
    if (!response.ok) {
      throw new ApiError(response.status, `Could not load the CV (HTTP ${response.status})`)
    }
    return URL.createObjectURL(await response.blob())
  },
}

// --- misc -------------------------------------------------------------------

export const settingsApi = {
  get: () => request<DeploymentSettings>('/settings'),
}

export const publicApi = {
  roles: () => request<PublicRole[]>('/public/roles', { auth: false }),
  session: (publicKey: string) =>
    request<PublicSession>(`/public/session/${publicKey}`, { auth: false }),
  apply: (publicKey: string, payload: { full_name: string; email: string; phone?: string; cv: File }) => {
    const formData = new FormData()
    formData.append('full_name', payload.full_name)
    formData.append('email', payload.email)
    if (payload.phone) formData.append('phone', payload.phone)
    formData.append('cv', payload.cv)
    return request<{ ok: boolean; message: string; candidate_id: string }>(
      `/public/apply/${publicKey}`,
      { method: 'POST', formData, auth: false },
    )
  },
}

/**
 * Exports stream from an authenticated endpoint, so the browser cannot simply
 * follow a link — fetch with the bearer token, then hand the blob to a click.
 */
export async function downloadExport(
  sessionId: string,
  format: 'pdf' | 'xlsx' | 'docx',
  scope: 'all' | 'shortlisted' | 'above_threshold',
  includeCvs: boolean,
): Promise<void> {
  const params = new URLSearchParams({
    format,
    scope,
    include_cvs: String(includeCvs),
  })
  const response = await fetch(`${BASE}/sessions/${sessionId}/export?${params}`, {
    headers: { Authorization: `Bearer ${useAuthStore.getState().accessToken ?? ''}` },
  })
  if (!response.ok) {
    throw new ApiError(response.status, 'Export failed')
  }

  const disposition = response.headers.get('content-disposition') ?? ''
  const match = /filename="?([^";]+)"?/.exec(disposition)
  const filename = match?.[1] ?? `tricv.${includeCvs ? 'zip' : format}`

  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}
