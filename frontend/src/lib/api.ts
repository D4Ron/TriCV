import { useAuthStore } from '@/store/auth'
import type {
  AuditEntry,
  Avis,
  Entretien,
  CandidaturesPage,
  Candidature,
  Client,
  Grille,
  GrilleEntretien,
  LigneBaremeEntretien,
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
import { NIVEAUX } from '@/lib/niveaux'

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

/**
 * Un dossier tel que le serveur propose de le découper.
 *
 * `depuis_arborescence` distingue un classement fait par quelqu'un — des
 * sous-dossiers — d'une lecture des noms de fichiers. La confiance à lui
 * accorder n'est pas la même, et l'écran le dit.
 */
export interface DossierPropose {
  cle: string
  libelle: string
  depuis_arborescence: boolean
  pieces: Array<{ nom: string; type_piece: string | null; index: number }>
}

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

/**
 * Les documents tableur d'un poste.
 *
 * Ils ne s'adressent pas aux mêmes personnes : le classement part au client,
 * le tableau d'élimination se produit à un candidat qui conteste, les
 * entretiens servent à écrire le rapport. Le classeur complet les réunit —
 * pratique en interne, trop bavard pour un envoi.
 */
export type TypeGrille =
  | 'PRESELECTION'
  | 'ELIMINATION'
  | 'ENTRETIENS'
  | 'SYNTHESE'
  | 'COMPLET'

export const TYPES_GRILLE: Array<{
  cle: TypeGrille
  libelle: string
  pour: string
}> = [
  {
    cle: 'PRESELECTION',
    libelle: 'Grille de présélection',
    pour: 'Le classement noté, dossier par dossier. C’est le document remis au client.',
  },
  {
    cle: 'ELIMINATION',
    libelle: "Tableau d'élimination",
    pour: 'Les dossiers écartés, groupés par motif, avec attendu et constaté. Se produit à un candidat qui conteste.',
  },
  {
    cle: 'ENTRETIENS',
    libelle: 'Détail des entretiens',
    pour: 'Les notes du jury critère par critère et ses observations. La matière du rapport.',
  },
  {
    cle: 'SYNTHESE',
    libelle: 'Synthèse',
    pour: 'Les effectifs et la répartition des motifs, en une page.',
  },
  {
    cle: 'COMPLET',
    libelle: 'Dossier complet',
    pour: 'Les quatre documents en un seul classeur, pour le travail interne.',
  },
]

/** À qui écrire. Les portées sont définies par le serveur. */
export type PorteeEnvoi =
  | 'tous'
  | 'preselectionnes'
  | 'elimines'
  | 'a_verifier'
  | 'sous_le_seuil'

export const PORTEES_ENVOI: Array<{ cle: PorteeEnvoi; libelle: string; aide: string }> = [
  {
    cle: 'tous',
    libelle: 'Tous les candidats',
    aide: "Tout dossier reçu sur ce poste, quelle qu'en soit l'issue — un accusé de réception, par exemple.",
  },
  {
    cle: 'preselectionnes',
    libelle: 'Les préqualifiés',
    aide: 'Ceux qui franchissent le seuil de présélection.',
  },
  {
    cle: 'sous_le_seuil',
    libelle: 'Les recevables sous le seuil',
    aide: "Éligibles mais non retenus : ni écartés, ni proposés.",
  },
  {
    cle: 'elimines',
    libelle: 'Les dossiers écartés',
    aide: 'Ceux dont un motif d’élimination est actif — une lettre de refus.',
  },
  {
    cle: 'a_verifier',
    libelle: 'Les dossiers à vérifier',
    aide: 'Souvent pour réclamer une pièce manquante.',
  },
]

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
  /**
   * Ce que la formation rapporte au-delà du diplôme.
   *
   * Ces points se prennent dans les 7 de la formation académique : le total du
   * barème ne bouge pas. Endpoint étroit à dessein — reconstruire les trente
   * points côté navigateur serait s'offrir l'occasion de les reconstruire faux.
   */
  definirExtrasFormation: (
    id: string,
    payload: {
      points_par_certification: number
      certifications_max: number
      points_formation_complementaire: number
    },
  ) => request<Poste>(`/postes/${id}/bareme/formation`, { method: 'PUT', body: payload }),
  changerSeuil: (id: string, seuil: number, justification: string) =>
    request<Poste>(`/postes/${id}/seuil`, { method: 'POST', body: { seuil, justification } }),
  evaluerPoste: (id: string) =>
    request<{ candidatures_evaluees: number }>(`/postes/${id}/evaluer`, { method: 'POST' }),
  grille: (id: string) => request<Grille>(`/postes/${id}/grille`),
  /**
   * Les dossiers auxquels écrire, par portée.
   *
   * La liste vient du serveur et non de la grille affichée : « tous » doit
   * couvrir toutes les candidatures reçues, y compris celles arrivées depuis
   * le dernier rafraîchissement de l'écran.
   */
  destinataires: (id: string, portee: PorteeEnvoi) =>
    request<{
      portee: PorteeEnvoi
      candidature_ids: string[]
      total: number
      sans_adresse: number
    }>(`/postes/${id}/destinataires?portee=${portee}`),
  /** Le fichier est protégé par le jeton : on le récupère puis on le remet
   *  au navigateur, un lien direct renverrait un 401. */
  telechargerGrille: async (id: string, type: TypeGrille = 'COMPLET'): Promise<void> => {
    const response = await fetch(
      `${BASE}/postes/${id}/grille.xlsx?type_grille=${type}`,
      {
        headers: { Authorization: `Bearer ${useAuthStore.getState().accessToken ?? ''}` },
      },
    )
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
  /** Réservé aux brouillons : un avis publié se clôture, il ne s'efface pas. */
  supprimerAvis: (id: string) => request<void>(`/avis/${id}`, { method: 'DELETE' }),
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
  /**
   * Le découpage proposé pour un lot, avant tout envoi.
   *
   * Seuls les noms circulent : montrer le regroupement avant de téléverser
   * cent fichiers évite une longue attente pour un aperçu.
   */
  apercuDepot: (posteId: string, noms: string[], chemins: string[] = []) => {
    const formData = new FormData()
    noms.forEach((n) => formData.append('noms', n))
    chemins.forEach((c) => formData.append('chemins', c))
    return request<{ dossiers: DossierPropose[] }>(
      `/postes/${posteId}/candidatures/depot-multiple/apercu`,
      { method: 'POST', formData },
    )
  },

  /**
   * Dépôt en lot.
   *
   * Un candidat envoie rarement un seul fichier. `groupes[i]` dit à quel
   * dossier appartient `fichiers[i]` — c'est le découpage que l'écran a montré
   * et qu'on a corrigé. Sans lui, le serveur le déduit du chemin d'origine puis
   * du nom du fichier.
   */
  depotMultiple: (
    posteId: string,
    fichiers: File[],
    depouiller: boolean,
    options: { groupes?: string[]; types?: Array<string | null>; chemins?: string[] } = {},
  ) => {
    const formData = new FormData()
    fichiers.forEach((f) => formData.append('fichiers', f))
    formData.append('type_piece', 'CV')
    formData.append('depouiller_aussitot', String(depouiller))
    options.groupes?.forEach((g) => formData.append('groupes', g))
    options.types?.forEach((x) => formData.append('types_pieces', x ?? ''))
    options.chemins?.forEach((c) => formData.append('chemins', c))
    return request<{
      deposes: number
      pieces: number
      refuses: number
      doublons_ignores: number
      doublons: number
      resultats: Array<{
        fichier: string
        accepte: boolean
        erreur?: string
        doublon_de?: string
        candidature_id?: string
        pieces?: number
        doublons?: Array<{ candidature_id: string; nom: string; motif: string }>
      }>
    }>(`/postes/${posteId}/candidatures/depot-multiple`, { method: 'POST', formData })
  },

  /** Rattache plusieurs fichiers d'un coup à un dossier déjà ouvert. */
  joindrePieces: (id: string, fichiers: File[], types: Array<string | null> = []) => {
    const formData = new FormData()
    fichiers.forEach((f) => formData.append('fichiers', f))
    types.forEach((x) => formData.append('types_pieces', x ?? ''))
    return request<Candidature>(`/candidatures/${id}/pieces/lot`, {
      method: 'POST',
      formData,
    })
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
      /** Propositions d'un dépouillement précédent remplacées par celui-ci. */
      remplacees: number
      /** L'adresse lue dans le dossier, quand elle change ce qu'on avait. */
      email_trouve: string | null
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
  /** Part humaine de la consistance : motivation et expression écrite. */
  apprecier: (id: string, note: number | null, motif: string) =>
    request<Candidature>(`/candidatures/${id}/appreciation`, {
      method: 'PATCH',
      body: { note, motif },
    }),

  /**
   * Entretien : les 70 points attribués par le jury.
   *
   * Une fiche par juré. Le cabinet fait siéger un panel — sept personnes sur
   * certains mandats — et retient la moyenne : enregistrer une fiche ne touche
   * jamais à celles des autres.
   */
  entretien: (id: string) => request<Entretien>(`/candidatures/${id}/entretien`),
  saisirEntretien: (
    id: string,
    payload: {
      jure: string
      lignes: Array<{ code: string; points: number | null; commentaire: string }>
      date_entretien?: string | null
      jury?: string
      observations?: string
    },
  ) => request<Entretien>(`/candidatures/${id}/entretien`, { method: 'PUT', body: payload }),
  /** Sans juré nommé, toutes les fiches du dossier sont effacées. */
  effacerEntretien: (id: string, jure?: string) =>
    request<Entretien>(
      `/candidatures/${id}/entretien${jure ? `?jure=${encodeURIComponent(jure)}` : ''}`,
      { method: 'DELETE' },
    ),
  /** La grille d'entretien, négociée avec le client poste par poste. */
  grilleEntretien: (posteId: string) => request<GrilleEntretien>(`/postes/${posteId}/grille-entretien`),
  definirGrilleEntretien: (posteId: string, criteres: LigneBaremeEntretien[] | null) =>
    request<GrilleEntretien>(`/postes/${posteId}/grille-entretien`, {
      method: 'PUT',
      body: { criteres },
    }),
  /** Reclasser un dossier à la main exige un motif écrit. */
  qualifier: (id: string, qualification: string | null, motif: string) =>
    request<Candidature>(`/candidatures/${id}/qualification`, {
      method: 'PATCH',
      body: { qualification, motif },
    }),
  joindrePiece: (id: string, typePiece: string, fichier: File, intituleLibre?: string) => {
    const formData = new FormData()
    formData.append('type_piece', typePiece)
    formData.append('fichier', fichier)
    if (intituleLibre) formData.append('intitule_libre', intituleLibre)
    return request<Candidature>(`/candidatures/${id}/pieces`, { method: 'POST', formData })
  },
  retirerPiece: (id: string, pieceId: string) =>
    request<Candidature>(`/candidatures/${id}/pieces/${pieceId}`, { method: 'DELETE' }),
  /**
   * Supprime un dossier entré par erreur.
   *
   * `confirmer` ne sert qu'au second appel : le premier revient en 409 si le
   * dossier porte un entretien, un courriel parti ou une présélection, et le
   * message dit lequel. L'interface le montre avant de redemander.
   */
  supprimerCandidature: (id: string, motif: string, confirmer = false) => {
    const query = new URLSearchParams({ motif })
    if (confirmer) query.set('confirmer', 'true')
    return request<{
      supprime: boolean
      pieces_supprimees: number
      profil_supprime: boolean
      courriels_conserves: number
    }>(`/candidatures/${id}?${query.toString()}`, { method: 'DELETE' })
  },
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
      /** Sans référence d'avis mais porteuses d'un CV : elles vont au vivier. */
      spontanees: number
      /** Réponses de promoteurs, versées au fil de leur mandat. */
      echanges_client: number
      non_rattaches: string[]
      sans_piece: string[]
    }>('/courriel/relever', { method: 'POST' }),

  /** Propose le texte d'un avis. N'écrit rien : c'est un brouillon à relire. */
  redigerAvis: (
    posteId: string,
    payload: { avis_id?: string | null; modele_id?: string | null; avec_assistance?: boolean } = {},
  ) =>
    request<{ texte: string; propose: boolean; avertissement: string | null }>(
      `/postes/${posteId}/avis/redaction`,
      { method: 'POST', body: payload },
    ),
  modifierAvis: (id: string, payload: Record<string, unknown>) =>
    request<Avis>(`/avis/${id}`, { method: 'PATCH', body: payload }),
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
    redact_demographics?: boolean
    allow_self_registration?: boolean
    candidatures_spontanees?: boolean
    courriel_actif?: boolean
    imap_host?: string
    imap_port?: number
    imap_user?: string
    /** Omis ou vide = inchangé. Le serveur ne renvoie jamais le secret. */
    imap_password?: string
    imap_folder?: string
    smtp_actif?: boolean
    smtp_host?: string
    smtp_port?: number
    smtp_user?: string
    smtp_password?: string
    smtp_tls?: boolean
    smtp_expediteur?: string
    url_publique?: string
  }) => request<DeploymentSettings>('/settings', { method: 'PATCH', body: payload }),
  /** Ouvre une session SMTP sans rien envoyer, pour valider la configuration. */
  testerEnvoi: () => request<{ ok: boolean; expediteur: string }>('/messagerie/test', { method: 'POST' }),
}

export interface AvisPublicItem {
  cle_publique: string
  intitule: string
  departement: string | null
  type_avis: string
  date_cloture: string | null
  publie_le: string | null
}

/**
 * Ce que le candidat déclare de son parcours, en plus de joindre son CV.
 *
 * Redondant avec le CV, volontairement : tant que le CV n'a pas été dépouillé
 * et relu, ces données n'existent pas en base — la note porte alors sur trois
 * points au lieu de trente, et les conditions d'âge ou de nationalité ne
 * s'appliquent à personne.
 */
export interface DiplomeDeclare {
  intitule: string
  /** Le N de BAC+N, choisi dans une liste : 0 = baccalauréat, 8 = doctorat. */
  niveau: number
  domaine: string
  etablissement?: string
  annee?: number | null
}

export interface ExperienceDeclaree {
  poste: string
  employeur: string
  /** AAAA-MM-JJ. Le formulaire saisit un mois, le jour vaut 1. */
  debut: string
  /** Absente = poste toujours occupé. */
  fin?: string | null
  domaines?: string[]
  pays?: string
}

export interface ParcoursDeclare {
  diplomes: DiplomeDeclare[]
  experiences: ExperienceDeclaree[]
  langues: string[]
  certifications: string[]
  formations_complementaires: string[]
}

/** L'échelle BAC+N du référentiel, telle que le candidat la choisit. */
/**
 * L'échelle des diplômes, pour le formulaire du candidat.
 *
 * Elle vit désormais dans `lib/niveaux` avec les autres : quatre écrans en
 * gardaient chacun leur copie, et les copies avaient fini par diverger.
 * Conservée ici sous son nom d'origine pour ne pas toucher aux appelants.
 */
export const NIVEAUX_DIPLOME: Array<{ valeur: number; libelle: string }> =
  NIVEAUX.map(({ valeur, detaille }) => ({ valeur, libelle: detaille }))

export interface AvisPublic extends AvisPublicItem {
  description: string | null
  missions: string[]
  profil: string[]
  /** Conditions éliminatoires, dites avant le dépôt. */
  conditions: string[]
  justification_conditions: string | null
  pieces_attendues: Array<{ code: string; libelle: string }>
  pieces_facultatives: Array<{ code: string; libelle: string }>
  /** « La CNI ou le passeport » : un choix à présenter comme tel, pas deux cases. */
  groupes_pieces: Array<{
    mode: 'TOUTES' | 'AU_MOINS_UNE'
    libelle: string
    pieces: Array<{ code: string; libelle: string }>
  }>
  formats_pieces: Record<string, string[]>
  pieces_libres_autorisees: boolean
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
      adresse?: string
      /** AAAA-MM-JJ. Décide de la condition d'âge, éliminatoire. */
      date_naissance?: string
      sexe?: string
      /** Séparées par des virgules. Décide de la condition de nationalité. */
      nationalites?: string
      parcours?: ParcoursDeclare
      pieces: Array<{ code: string; fichier: File; intitule?: string }>
    },
  ) => {
    const formData = new FormData()
    formData.append('nom', payload.nom)
    formData.append('prenom', payload.prenom)
    formData.append('email', payload.email)
    if (payload.telephone) formData.append('telephone', payload.telephone)
    if (payload.adresse) formData.append('adresse', payload.adresse)
    if (payload.date_naissance) formData.append('date_naissance', payload.date_naissance)
    if (payload.sexe) formData.append('sexe', payload.sexe)
    if (payload.nationalites) formData.append('nationalites', payload.nationalites)
    // Le parcours voyage en JSON dans le multipart : des listes imbriquées ne
    // se décrivent pas en champs plats sans inventer une convention de noms.
    if (payload.parcours) formData.append('parcours', JSON.stringify(payload.parcours))
    // Les trois listes sont appariées par position côté serveur.
    payload.pieces.forEach(({ code, fichier, intitule }) => {
      formData.append('types_pieces', code)
      formData.append('fichiers', fichier)
      formData.append('intitules_pieces', intitule ?? '')
    })
    return request<{ ok: boolean; message: string; candidature_id: string }>(
      `/public/avis/${cle}/candidater`,
      { method: 'POST', formData, auth: false },
    )
  },

  /**
   * Dépôt hors avis : « déposer votre CV ».
   *
   * Rattaché à aucun poste, donc jamais noté — il n'y a pas d'exigences à
   * confronter. Le profil rejoint le vivier, où une recherche le retrouvera le
   * jour où un mandat lui correspond.
   */
  candidatureSpontanee: (payload: {
    nom: string
    prenom: string
    email: string
    telephone?: string
    adresse?: string
    date_naissance?: string
    sexe?: string
    nationalites?: string
    parcours?: ParcoursDeclare
    domaine?: string
    message?: string
    pieces: Array<{ code: string; fichier: File; intitule?: string }>
  }) => {
    const formData = new FormData()
    formData.append('nom', payload.nom)
    formData.append('prenom', payload.prenom)
    formData.append('email', payload.email)
    if (payload.telephone) formData.append('telephone', payload.telephone)
    if (payload.adresse) formData.append('adresse', payload.adresse)
    if (payload.date_naissance) formData.append('date_naissance', payload.date_naissance)
    if (payload.sexe) formData.append('sexe', payload.sexe)
    if (payload.nationalites) formData.append('nationalites', payload.nationalites)
    if (payload.parcours) formData.append('parcours', JSON.stringify(payload.parcours))
    if (payload.domaine) formData.append('domaine', payload.domaine)
    if (payload.message) formData.append('message', payload.message)
    payload.pieces.forEach(({ code, fichier, intitule }) => {
      formData.append('types_pieces', code)
      formData.append('fichiers', fichier)
      formData.append('intitules_pieces', intitule ?? '')
    })
    return request<{ ok: boolean; message: string; candidature_id: string }>(
      '/public/candidature-spontanee',
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


/**
 * Récupère un fichier protégé par le jeton, puis le remet au navigateur.
 *
 * Ni `<a href>` ni `<iframe src>` ne portent d'en-tête d'autorisation : ils
 * afficheraient le corps du 401. Renvoie les en-têtes de la réponse, dont
 * certains portent un compte rendu que l'écran affiche sans rouvrir le fichier.
 */
async function telecharger(chemin: string, secours: string): Promise<Headers> {
  const response = await fetch(`${BASE}${chemin}`, {
    headers: { Authorization: `Bearer ${useAuthStore.getState().accessToken ?? ''}` },
  })
  if (!response.ok) {
    let payload: unknown = null
    try {
      payload = await response.json()
    } catch {
      /* corps non JSON : le statut suffit */
    }
    throw new ApiError(response.status, readDetail(payload, "Le téléchargement a échoué"))
  }
  const disposition = response.headers.get('content-disposition') ?? ''
  const nom = /filename="?([^";]+)"?/.exec(disposition)?.[1] ?? secours
  const url = URL.createObjectURL(await response.blob())
  const lien = document.createElement('a')
  lien.href = url
  lien.download = nom
  document.body.appendChild(lien)
  lien.click()
  lien.remove()
  URL.revokeObjectURL(url)
  return response.headers
}

// --- collaboration : courriels aux candidats, espace du promoteur -----------

export interface ModeleCourriel {
  code: string
  libelle: string
  description: string
  sujet: string
  corps: string
  variables: string[]
  /** À qui le modèle s'adresse : un candidat, ou le commanditaire. */
  destinataire: 'CANDIDAT' | 'CLIENT'
}

export interface MessagePrepare {
  candidature_id: string
  destinataire: string
  nom: string
  sujet: string
  corps: string
  /** Variables du modèle restées sans valeur : à compléter avant d'envoyer. */
  variables_manquantes: string[]
}

export interface MessageEnvoye {
  id: string
  destinataire: string
  sujet: string
  corps: string
  modele: string | null
  statut: 'ENVOYE' | 'ECHEC'
  erreur: string | null
  envoye_le: string
}

export interface AccesClient {
  id: string
  mandat_id: string
  email: string
  nom: string
  fonction: string | null
  active_le: string | null
  dernier_acces_le: string | null
  revoque_le: string | null
  motif_revocation: string | null
  /** Rendu une seule fois, à l'ouverture. Il n'est jamais relu ensuite. */
  lien_activation?: string | null
  courriel_envoye?: boolean | null
  avertissement?: string | null
}

export interface EtapeMandat {
  id?: string
  ordre?: number
  libelle: string
  etat: 'A_VENIR' | 'EN_COURS' | 'TERMINEE'
  date_prevue: string | null
  date_reelle: string | null
  visible_client: boolean
}

export interface EchangeClient {
  id: string
  mandat_id: string
  poste_id: string | null
  auteur: 'CABINET' | 'CLIENT'
  auteur_nom: string
  type_echange: 'MESSAGE' | 'DEMANDE_MODIFICATION' | 'VALIDATION'
  objet: string | null
  corps: string
  envoye_le: string
  lu_le: string | null
  traite_le: string | null
}

/**
 * Écrire aux candidats, et tenir l'espace du promoteur.
 *
 * `apercu` rend les messages rédigés sans rien envoyer ; `envoyer` expédie le
 * texte qu'on lui donne. La séparation est délibérée : ce qui part est ce qui
 * a été montré, et un courriel ne se rattrape pas.
 */
export const collaborationApi = {
  modeles: (destinataire?: 'CANDIDAT' | 'CLIENT') =>
    request<ModeleCourriel[]>(
      `/messagerie/modeles${destinataire ? `?destinataire=${destinataire}` : ''}`,
    ),
  apercu: (modele: string, candidatureIds: string[], valeurs: Record<string, string> = {}) =>
    request<MessagePrepare[]>('/messagerie/apercu', {
      method: 'POST',
      body: { modele, candidature_ids: candidatureIds, valeurs },
    }),
  envoyer: (
    modele: string | null,
    messages: Array<{ candidature_id: string; destinataire: string; sujet: string; corps: string }>,
  ) =>
    request<{
      envoyes: number
      echecs: number
      details: Array<{ candidature_id: string; ok: boolean; erreur?: string }>
    }>('/messagerie/envoyer', { method: 'POST', body: { modele, messages } }),
  historique: (candidatureId: string) =>
    request<MessageEnvoye[]>(`/candidatures/${candidatureId}/messages`),

  acces: (mandatId: string) => request<AccesClient[]>(`/mandats/${mandatId}/acces`),
  ouvrirAcces: (
    mandatId: string,
    payload: { email: string; nom: string; fonction?: string; envoyer_courriel: boolean },
  ) => request<AccesClient>(`/mandats/${mandatId}/acces`, { method: 'POST', body: payload }),
  revoquerAcces: (accesId: string, motif = '') =>
    request<void>(`/acces-client/${accesId}?motif=${encodeURIComponent(motif)}`, {
      method: 'DELETE',
    }),

  chronogramme: (mandatId: string) => request<EtapeMandat[]>(`/mandats/${mandatId}/chronogramme`),
  ecrireChronogramme: (mandatId: string, etapes: EtapeMandat[]) =>
    request<EtapeMandat[]>(`/mandats/${mandatId}/chronogramme`, { method: 'PUT', body: etapes }),

  echanges: (mandatId: string) => request<EchangeClient[]>(`/mandats/${mandatId}/echanges`),
  ecrireAuClient: (
    mandatId: string,
    payload: { corps: string; objet?: string; poste_id?: string; type_echange?: string },
  ) => request<EchangeClient>(`/mandats/${mandatId}/echanges`, { method: 'POST', body: payload }),
  marquerTraite: (echangeId: string) =>
    request<EchangeClient>(`/echanges/${echangeId}/traiter`, { method: 'POST' }),
}

// --- rapports et gabarits imposés -------------------------------------------

/** Le genre d'une ligne : ce qui la fait ressortir, ou la met en retrait. */
export type GenreLigne = 'normal' | 'rubrique' | 'detail' | 'total'

export interface TableauRapport {
  titre: string
  colonnes: Array<{ libelle: string; numerique: boolean }>
  lignes: Array<{ cellules: string[]; genre: GenreLigne }>
}

export interface SectionRapport {
  code: string
  titre: string
  contenu: string
  /**
   * Le commentaire des chiffres, qui se lit **sous** le tableau : le document
   * du cabinet annonce le tableau, l'insère, puis le commente. Absent quand la
   * section n'a rien à dire après son tableau — ou n'en a pas.
   */
  contenu_apres?: string | null
  /** PROPOSEE = pas encore relue. REDIGEE = écrite ou validée par un humain. */
  origine: 'PROPOSEE' | 'REDIGEE' | 'CALCULEE'
  /**
   * Les tableaux d'une section calculée, en structure. Vide sur une section
   * rédigée — et sur un rapport produit avant que la structure n'existe, qui
   * garde son texte aligné dans `contenu`.
   */
  tableaux?: TableauRapport[]
  /** 1 = section, 2 = sous-section. Le rapport remis est hiérarchisé. */
  niveau?: number
  /** Un titre sans texte à lui, qui porte des sous-sections. */
  porteur?: boolean
}

/** Ce que le cabinet remet, et à quel moment de la mission. */
export type TypeRapport = 'PRESELECTION' | 'ENTRETIENS' | 'FINAL'

export const TYPES_RAPPORT: Array<{ cle: TypeRapport; libelle: string; quand: string }> = [
  {
    cle: 'PRESELECTION',
    libelle: 'Rapport de présélection',
    quand: "Après le dépouillement, avant les entretiens. S'arrête au classement des dossiers.",
  },
  {
    cle: 'ENTRETIENS',
    libelle: 'Rapport des entretiens',
    quand: 'Après le passage devant le jury. Reprend le classement final.',
  },
  {
    cle: 'FINAL',
    libelle: 'Rapport final de recrutement',
    quand: "Le document complet, de la publication de l'avis au classement final.",
  },
]

export interface Rapport {
  id: string
  mandat_id: string
  poste_id: string | null
  modele_id: string | null
  titre: string
  type_rapport: TypeRapport
  statut: 'BROUILLON' | 'EN_RELECTURE' | 'VALIDE'
  sections: SectionRapport[]
  donnees: Record<string, unknown>
  valide_le: string | null
  partage_le: string | null
  created_at: string | null
}

export interface RapportItem {
  id: string
  titre: string
  type_rapport: TypeRapport
  statut: 'BROUILLON' | 'EN_RELECTURE' | 'VALIDE'
  poste_id: string | null
  valide_le: string | null
  partage_le: string | null
  created_at: string | null
}

export interface ModeleDocument {
  id: string
  client_id: string | null
  mandat_id: string | null
  libelle: string
  usage: 'AVIS' | 'RAPPORT' | 'CV' | 'COURRIEL'
  nom_fichier: string | null
  actif: boolean
  structure: {
    sections?: Array<{
      code: string
      titre: string
      consigne: string
      calculee?: boolean
      correspondance_proposee?: string | null
    }>
    titres_releves?: string[]
  } | null
  notes: string | null
  created_at: string | null
}

export const rapportsApi = {
  lister: (mandatId: string) => request<RapportItem[]>(`/mandats/${mandatId}/rapports`),
  /** Jette un brouillon. Un rapport validé est refusé : il se retire du partage. */
  supprimer: (rapportId: string) =>
    request<void>(`/rapports/${rapportId}`, { method: 'DELETE' }),
  generer: (
    mandatId: string,
    payload: {
      poste_id?: string | null
      titre?: string | null
      modele_id?: string | null
      type_rapport?: TypeRapport
      avec_assistance: boolean
    },
  ) => request<Rapport>(`/mandats/${mandatId}/rapports`, { method: 'POST', body: payload }),
  lire: (id: string) => request<Rapport>(`/rapports/${id}`),
  modifier: (
    id: string,
    payload: { titre?: string; sections?: Array<{ code: string; titre: string; contenu: string }> },
  ) => request<Rapport>(`/rapports/${id}`, { method: 'PUT', body: payload }),
  valider: (id: string) => request<Rapport>(`/rapports/${id}/valider`, { method: 'POST' }),
  partager: (id: string, partager = true) =>
    request<Rapport>(`/rapports/${id}/partager?partager=${partager}`, { method: 'POST' }),
  /** Le fichier est protégé par le jeton : un lien direct renverrait un 401. */
  exporter: async (id: string, format: 'docx' | 'pdf' | 'odt' | 'txt'): Promise<void> => {
    const response = await fetch(`${BASE}/rapports/${id}/export?format=${format}`, {
      headers: { Authorization: `Bearer ${useAuthStore.getState().accessToken ?? ''}` },
    })
    if (!response.ok) throw new ApiError(response.status, "L'export a échoué")
    const disposition = response.headers.get('content-disposition') ?? ''
    const nom = /filename="?([^";]+)"?/.exec(disposition)?.[1] ?? `rapport.${format}`
    const url = URL.createObjectURL(await response.blob())
    const lien = document.createElement('a')
    lien.href = url
    lien.download = nom
    document.body.appendChild(lien)
    lien.click()
    lien.remove()
    URL.revokeObjectURL(url)
  },

  /**
   * Le CV d'un candidat, remis en forme depuis les données du dossier.
   *
   * Refusé (409) tant que le parcours n'a pas été relu : un CV à en-tête du
   * cabinet tiré d'une extraction non confirmée donnerait à une supposition
   * l'autorité d'une pièce. `accepterNonVerifie` lève le refus, et la mention
   * apparaît alors sur le document.
   */
  cvMaison: async (
    candidatureId: string,
    options: {
      format?: 'docx' | 'pdf' | 'txt'
      modeleId?: string | null
      avecCoordonnees?: boolean
      accepterNonVerifie?: boolean
    } = {},
  ): Promise<void> => {
    const params = new URLSearchParams({ format: options.format ?? 'docx' })
    if (options.modeleId) params.set('modele_id', options.modeleId)
    if (options.avecCoordonnees === false) params.set('avec_coordonnees', 'false')
    if (options.accepterNonVerifie) params.set('accepter_non_verifie', 'true')
    await telecharger(`/candidatures/${candidatureId}/cv-maison?${params}`, 'cv.docx')
  },

  /** Les CV d'un poste sous une présentation unique, en une archive. */
  cvsMaison: async (
    posteId: string,
    options: {
      format?: 'docx' | 'pdf' | 'txt'
      modeleId?: string | null
      avecCoordonnees?: boolean
      accepterNonVerifie?: boolean
      portee?: 'proposes' | 'tous'
    } = {},
  ): Promise<{ inclus: number; ecartes: number }> => {
    const params = new URLSearchParams({
      format: options.format ?? 'docx',
      portee: options.portee ?? 'proposes',
    })
    if (options.modeleId) params.set('modele_id', options.modeleId)
    if (options.avecCoordonnees === false) params.set('avec_coordonnees', 'false')
    if (options.accepterNonVerifie) params.set('accepter_non_verifie', 'true')
    const entetes = await telecharger(`/postes/${posteId}/cvs-maison.zip?${params}`, 'cv.zip')
    return {
      inclus: Number(entetes.get('X-TriCV-Inclus') ?? 0),
      ecartes: Number(entetes.get('X-TriCV-Ecartes') ?? 0),
    }
  },

  modeles: (params: { client_id?: string; mandat_id?: string; usage?: string } = {}) => {
    const query = new URLSearchParams()
    Object.entries(params).forEach(([cle, valeur]) => {
      if (valeur) query.set(cle, valeur)
    })
    const suffix = query.toString()
    return request<ModeleDocument[]>(`/modeles-documents${suffix ? `?${suffix}` : ''}`)
  },
  deposerModele: (payload: {
    libelle: string
    usage: string
    client_id?: string
    mandat_id?: string
    notes?: string
    fichier: File
  }) => {
    const formData = new FormData()
    formData.append('libelle', payload.libelle)
    formData.append('usage', payload.usage)
    if (payload.client_id) formData.append('client_id', payload.client_id)
    if (payload.mandat_id) formData.append('mandat_id', payload.mandat_id)
    if (payload.notes) formData.append('notes', payload.notes)
    formData.append('fichier', payload.fichier)
    return request<ModeleDocument>('/modeles-documents', { method: 'POST', formData })
  },
  corrigerModele: (
    id: string,
    payload: { structure: Record<string, unknown>; libelle?: string; notes?: string; actif?: boolean },
  ) => request<ModeleDocument>(`/modeles-documents/${id}`, { method: 'PUT', body: payload }),
  supprimerModele: (id: string) =>
    request<void>(`/modeles-documents/${id}`, { method: 'DELETE' }),
}

// --- espace du promoteur (côté client) --------------------------------------

export interface SuiviClient {
  mandat: string
  reference: string | null
  client: string
  etapes: Array<{ libelle: string; etat: string; date_prevue: string | null }>
  postes: Array<{
    intitule: string
    nombre_a_pourvoir: number
    avancement: string
    avis_publie_le: string | null
    date_cloture: string | null
  }>
  messages_non_lus: number
  rapports_disponibles: number
}

/**
 * L'espace du promoteur. Porte séparée de celle du cabinet, jusque dans le
 * jeton : celui-ci est de type « client » et n'ouvre aucune route interne.
 * Il est conservé hors du store d'authentification du personnel, pour la même
 * raison.
 */
export const espaceClientApi = {
  verifierLien: (jeton: string) =>
    request<{ nom: string; email: string; mandat: string; client: string }>(
      `/espace-client/activation/${jeton}`,
      { auth: false },
    ),
  activer: (jeton: string, motDePasse: string) =>
    request<{ token: string; nom: string; email: string; mandat: string; client: string }>(
      '/espace-client/activation',
      { method: 'POST', body: { jeton, mot_de_passe: motDePasse }, auth: false },
    ),
  connexion: (email: string, motDePasse: string) =>
    request<{ token: string; nom: string; email: string; mandat: string; client: string }>(
      '/espace-client/connexion',
      { method: 'POST', body: { email, mot_de_passe: motDePasse }, auth: false },
    ),
  suivi: (token: string) => requestAvecJeton<SuiviClient>('/espace-client/suivi', token),
  messages: (token: string) =>
    requestAvecJeton<
      Array<{
        id: string
        auteur: 'CABINET' | 'CLIENT'
        auteur_nom: string
        type_echange: string
        objet: string | null
        corps: string
        envoye_le: string
        traite_le: string | null
      }>
    >('/espace-client/messages', token),
  ecrire: (
    token: string,
    payload: { corps: string; objet?: string; demande_modification?: boolean },
  ) =>
    requestAvecJeton('/espace-client/messages', token, { method: 'POST', body: payload }),
  rapports: (token: string) =>
    requestAvecJeton<Array<{ id: string; titre: string; partage_le: string | null }>>(
      '/espace-client/rapports',
      token,
    ),
}

/**
 * Appel porteur d'un jeton client explicite.
 *
 * Le client n'utilise pas le store d'authentification du personnel : mêler les
 * deux ferait qu'une session cabinet ouverte dans le même navigateur
 * détournerait les requêtes de l'espace client, et réciproquement.
 */
async function requestAvecJeton<T>(
  path: string,
  token: string,
  options: { method?: string; body?: unknown } = {},
): Promise<T> {
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  const response = await fetch(`${BASE}${path}`, {
    method: options.method ?? 'GET',
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  })
  if (!response.ok) {
    let payload: unknown = null
    try {
      payload = await response.json()
    } catch {
      /* corps non JSON : le statut suffit */
    }
    throw new ApiError(response.status, readDetail(payload, response.statusText))
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}
