import { useAuthStore } from '@/store/auth'
import type {
  AuditEntry,
  Avis,
  CandidaturesPage,
  Candidature,
  Client,
  Grille,
  Mandat,
  Poste,
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

import { API_BASE as BASE, API_URL } from '@/lib/config'

export { API_URL }

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
  signupConfig: () =>
    request<{ enabled: boolean; requires_code: boolean }>('/auth/signup-config', { auth: false }),
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

// --- chaîne de recrutement --------------------------------------------------

export interface SuppressionResultat {
  supprime: string
  mandats: number
  postes: number
  avis: number
  candidatures: number
  candidats_supprimes?: number
}

/** Fichiers effacés d'un mandat archivé. Les dossiers, eux, restent. */
export interface PurgeResultat {
  fichiers: number
  mo: number
  candidatures: number
}

export const recrutementApi = {
  clients: (recherche?: string, archives = false) => {
    const query = new URLSearchParams()
    if (recherche) query.set('recherche', recherche)
    if (archives) query.set('archives', 'true')
    const suffix = query.toString()
    return request<Client[]>(`/clients${suffix ? `?${suffix}` : ''}`)
  },
  creerClient: (payload: { nom: string; secteur?: string }) =>
    request<Client>('/clients', { method: 'POST', body: payload }),
  supprimerClient: (id: string, confirmer = false) =>
    request<SuppressionResultat>(`/clients/${id}?confirmer=${confirmer}`, { method: 'DELETE' }),
  supprimerMandat: (id: string, confirmer = false) =>
    request<SuppressionResultat>(`/mandats/${id}?confirmer=${confirmer}`, { method: 'DELETE' }),
  archiverMandat: (id: string) =>
    request<{ archive: boolean }>(`/mandats/${id}/archiver`, { method: 'POST' }),
  desarchiverMandat: (id: string) =>
    request<{ archive: boolean }>(`/mandats/${id}/desarchiver`, { method: 'POST' }),
  archiverClient: (id: string) =>
    request<{ archive: boolean }>(`/clients/${id}/archiver`, { method: 'POST' }),
  desarchiverClient: (id: string) =>
    request<{ archive: boolean }>(`/clients/${id}/desarchiver`, { method: 'POST' }),

  /** Ce qu'une purge libérerait. Ne supprime rien. */
  estimerPurge: (id: string) => request<PurgeResultat>(`/mandats/${id}/purge`),
  /** Supprime les fichiers d'un mandat archivé ; les dossiers restent. */
  purgerMandat: (id: string) =>
    request<PurgeResultat>(`/mandats/${id}/purge`, { method: 'POST' }),

  mandats: (params: { statut?: string; client_id?: string; archives?: boolean } = {}) => {
    const query = new URLSearchParams()
    if (params.statut) query.set('statut', params.statut)
    if (params.client_id) query.set('client_id', params.client_id)
    if (params.archives) query.set('archives', 'true')
    const suffix = query.toString()
    return request<Mandat[]>(`/mandats${suffix ? `?${suffix}` : ''}`)
  },
  mandat: (id: string) => request<Mandat>(`/mandats/${id}`),
  creerMandat: (payload: { client_id: string; intitule: string; type_attribution?: string }) =>
    request<Mandat>('/mandats', { method: 'POST', body: payload }),
  modifierMandat: (id: string, payload: Record<string, unknown>) =>
    request<Mandat>(`/mandats/${id}`, { method: 'PATCH', body: payload }),

  postes: (mandatId: string) => request<Poste[]>(`/mandats/${mandatId}/postes`),
  poste: (id: string) => request<Poste>(`/postes/${id}`),
  creerPoste: (mandatId: string, payload: Record<string, unknown>) =>
    request<Poste>(`/mandats/${mandatId}/postes`, { method: 'POST', body: payload }),
  modifierPoste: (id: string, payload: Record<string, unknown>) =>
    request<Poste>(`/postes/${id}`, { method: 'PATCH', body: payload }),
  changerSeuil: (id: string, seuil: number, justification: string) =>
    request<Poste>(`/postes/${id}/seuil`, { method: 'POST', body: { seuil, justification } }),
  evaluerPoste: (id: string) =>
    request<{ candidatures_evaluees: number }>(`/postes/${id}/evaluer`, { method: 'POST' }),
  grille: (id: string) => request<Grille>(`/postes/${id}/grille`),
  /** Le fichier est protégé par le jeton : on le récupère puis on le remet
   *  au navigateur, un lien direct renverrait un 401. */
  telechargerGrille: async (id: string): Promise<void> => {
    const response = await fetch(`${BASE}/postes/${id}/grille.xlsx`, {
      headers: { Authorization: `Bearer ${useAuthStore.getState().accessToken ?? ''}` },
    })
    if (!response.ok) throw new ApiError(response.status, "L'export a échoué")

    const disposition = response.headers.get('content-disposition') ?? ''
    const nom = /filename="?([^";]+)"?/.exec(disposition)?.[1] ?? 'grille-preselection.xlsx'
    const url = URL.createObjectURL(await response.blob())
    const lien = document.createElement('a')
    lien.href = url
    lien.download = nom
    document.body.appendChild(lien)
    lien.click()
    lien.remove()
    URL.revokeObjectURL(url)
  },

  avis: (posteId: string) => request<Avis[]>(`/postes/${posteId}/avis`),
  creerAvis: (posteId: string, payload: Record<string, unknown>) =>
    request<Avis>(`/postes/${posteId}/avis`, { method: 'POST', body: payload }),
  publierAvis: (id: string) => request<Avis>(`/avis/${id}/publier`, { method: 'POST' }),
  cloturerAvis: (id: string) => request<Avis>(`/avis/${id}/cloturer`, { method: 'POST' }),

  candidatures: (posteId: string, params: Record<string, string | number> = {}) => {
    const query = new URLSearchParams()
    Object.entries(params).forEach(([cle, valeur]) => {
      if (valeur !== undefined && valeur !== '') query.set(cle, String(valeur))
    })
    const suffix = query.toString()
    return request<CandidaturesPage>(
      `/postes/${posteId}/candidatures${suffix ? `?${suffix}` : ''}`,
    )
  },
  candidature: (id: string) => request<Candidature>(`/candidatures/${id}`),
  /** Dépôt en lot : un fichier = une candidature, à relire ensuite. */
  depotMultiple: (posteId: string, fichiers: File[], depouiller: boolean) => {
    const formData = new FormData()
    fichiers.forEach((f) => formData.append('fichiers', f))
    formData.append('type_piece', 'CV')
    formData.append('depouiller_aussitot', String(depouiller))
    return request<{
      deposes: number
      refuses: number
      doublons_ignores: number
      doublons: number
      resultats: Array<{
        fichier: string
        accepte: boolean
        erreur?: string
        doublon_de?: string
        candidature_id?: string
        doublons?: Array<{ candidature_id: string; nom: string; motif: string }>
      }>
    }>(`/postes/${posteId}/candidatures/depot-multiple`, { method: 'POST', formData })
  },
  creerCandidature: (posteId: string, payload: Record<string, unknown>) =>
    request<Candidature>(`/postes/${posteId}/candidatures`, { method: 'POST', body: payload }),
  depouiller: (id: string) =>
    request<{
      diplomes: number
      experiences: number
      langues: number
      certifications: number
      pieces_lues: number
      avertissements: string[]
    }>(`/candidatures/${id}/depouiller`, { method: 'POST' }),
  verifier: (id: string, payload: Record<string, boolean>) =>
    request<Candidature>(`/candidatures/${id}/verifier`, { method: 'POST', body: payload }),
  leverMotif: (id: string, motif: string, justification: string) =>
    request<unknown>(`/candidatures/${id}/eliminations/${motif}/lever`, {
      method: 'POST',
      body: { motif: justification },
    }),
  noteManuelle: (id: string, note: number | null, motif: string) =>
    request<Candidature>(`/candidatures/${id}/note`, { method: 'PATCH', body: { note, motif } }),
  joindrePiece: (id: string, typePiece: string, fichier: File) => {
    const formData = new FormData()
    formData.append('type_piece', typePiece)
    formData.append('fichier', fichier)
    return request<Candidature>(`/candidatures/${id}/pieces`, { method: 'POST', formData })
  },
  retirerPiece: (id: string, pieceId: string) =>
    request<Candidature>(`/candidatures/${id}/pieces/${pieceId}`, { method: 'DELETE' }),
  /** Même contrainte que les CV : le jeton ne passe pas dans une balise src. */
  pieceObjectUrl: async (id: string, pieceId: string): Promise<string> => {
    const response = await fetch(`${BASE}/candidatures/${id}/pieces/${pieceId}`, {
      headers: { Authorization: `Bearer ${useAuthStore.getState().accessToken ?? ''}` },
    })
    if (!response.ok) throw new ApiError(response.status, `Pièce indisponible (${response.status})`)
    return URL.createObjectURL(await response.blob())
  },

  etatCourriel: () =>
    request<{ actif: boolean; boite: string | null; dossier: string | null }>('/courriel/etat'),
  testerCourriel: () =>
    request<{ boite: string; dossier: string; messages: number; non_lus: number }>(
      '/courriel/tester',
      { method: 'POST' },
    ),
  apercuCourriel: () =>
    request<{
      messages: number
      details: Array<{
        action: string
        expediteur: string
        nom_devine: string
        sujet: string
        recu_le: string
        references: string[]
        poste: string | null
        pieces: Array<{ nom: string; octets: number; type: string; retenue: boolean }>
      }>
    }>('/courriel/apercu', { method: 'POST' }),
  releverCourriel: () =>
    request<{
      crees: number
      ignores: number
      non_rattaches: string[]
      sans_piece: string[]
    }>('/courriel/relever', { method: 'POST' }),
}

// --- vivier -----------------------------------------------------------------

/**
 * Les profils déjà connus du cabinet.
 *
 * Ce que la purge d'un mandat archivé conserve : identité, coordonnées,
 * diplômes, parcours, notes obtenues. Le fichier disparaît, la personne reste
 * trouvable.
 */
export interface VivierItem {
  id: string
  nom: string
  prenom: string
  email: string | null
  telephone: string | null
  sexe: 'M' | 'F' | null
  age: number | null
  nationalites: string[]
  provenance: string
  verifie: boolean
  niveau_max: number | null
  niveau_libelle: string | null
  diplome_principal: string | null
  domaine_principal: string | null
  annees_experience: number
  dernier_poste: string | null
  dernier_employeur: string | null
  nombre_candidatures: number
  derniere_candidature: string | null
  postes_vises: string[]
  pieces_conservees: number
  pieces_purgees: number
}

export interface ProfilVivier extends VivierItem {
  adresse: string | null
  date_naissance: string | null
  langues: string[]
  certifications: string[]
  diplomes: Array<{
    intitule: string
    niveau: number
    niveau_libelle: string | null
    domaine: string
    etablissement: string | null
    annee: number | null
    provenance: string
  }>
  experiences: Array<{
    poste: string
    employeur: string
    debut: string
    fin: string | null
    domaines: string[]
    pays: string | null
    provenance: string
  }>
  historique: Array<{
    candidature_id: string
    poste_id: string
    poste: string
    mandat: string
    client: string
    recue_le: string
    statut: string
    source: string
    note: number | null
    note_max: number | null
    atteint_le_seuil: boolean | null
    pieces_conservees: number
    pieces_purgees: number
    mandat_archive: boolean
  }>
}

export interface CriteresVivier {
  recherche?: string
  niveau_min?: number
  domaine?: string
  annees_experience_min?: number
  sexe?: 'M' | 'F'
  age_min?: number
  age_max?: number
  nationalite?: string
  page?: number
  page_size?: number
}

export const vivierApi = {
  rechercher: (criteres: CriteresVivier = {}) => {
    const params = new URLSearchParams()
    Object.entries(criteres).forEach(([cle, valeur]) => {
      if (valeur !== undefined && valeur !== null && valeur !== '') {
        params.set(cle, String(valeur))
      }
    })
    const suffix = params.toString()
    return request<{ items: VivierItem[]; total: number; page: number; page_size: number }>(
      `/vivier${suffix ? `?${suffix}` : ''}`,
    )
  },
  profil: (id: string) => request<ProfilVivier>(`/vivier/${id}`),
}

// --- misc -------------------------------------------------------------------

export const settingsApi = {
  get: () => request<DeploymentSettings>('/settings'),
  modifier: (payload: {
    seuil_preselection_defaut?: number
    redact_demographics?: boolean
    allow_self_registration?: boolean
    courriel_actif?: boolean
    imap_host?: string
    imap_port?: number
    imap_user?: string
    /** Omis ou vide = inchangé. Le serveur ne renvoie jamais le secret. */
    imap_password?: string
    imap_folder?: string
  }) => request<DeploymentSettings>('/settings', { method: 'PATCH', body: payload }),
}

export interface AvisPublicItem {
  cle_publique: string
  intitule: string
  departement: string | null
  type_avis: string
  date_cloture: string | null
  publie_le: string | null
}

export interface AvisPublic extends AvisPublicItem {
  description: string | null
  missions: string[]
  profil: string[]
  pieces_attendues: Array<{ code: string; libelle: string }>
  pieces_facultatives: Array<{ code: string; libelle: string }>
  taille_max_mo: number
  formats_acceptes: string[]
  accepte_candidatures: boolean
}

/** Façade publique de la chaîne de recrutement : aucun jeton, aucun score. */
export const avisPublicApi = {
  ouverts: () => request<AvisPublicItem[]>('/public/avis', { auth: false }),
  detail: (cle: string) => request<AvisPublic>(`/public/avis/${cle}`, { auth: false }),
  candidater: (
    cle: string,
    payload: {
      nom: string
      prenom: string
      email: string
      telephone?: string
      pieces: Array<{ code: string; fichier: File }>
    },
  ) => {
    const formData = new FormData()
    formData.append('nom', payload.nom)
    formData.append('prenom', payload.prenom)
    formData.append('email', payload.email)
    if (payload.telephone) formData.append('telephone', payload.telephone)
    // Les deux listes sont appariées par position côté serveur.
    payload.pieces.forEach(({ code, fichier }) => {
      formData.append('types_pieces', code)
      formData.append('fichiers', fichier)
    })
    return request<{ ok: boolean; message: string; candidature_id: string }>(
      `/public/avis/${cle}/candidater`,
      { method: 'POST', formData, auth: false },
    )
  },
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
