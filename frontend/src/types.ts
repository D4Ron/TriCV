export type SessionStatus = 'DRAFT' | 'OPEN' | 'CLOSED' | 'ARCHIVED'
export type AnalysisStatus = 'PENDING' | 'PROCESSING' | 'ANALYZED' | 'FAILED'
export type Recommendation = 'STRONG_FIT' | 'FIT' | 'MAYBE' | 'NOT_FIT'
export type HrStatus = 'NEW' | 'SHORTLISTED' | 'MAYBE' | 'REJECTED'
export type CandidateSource = 'PUBLIC_FORM' | 'HR_UPLOAD'
export type Language = 'fr' | 'en'

export interface User {
  id: string
  email: string
  full_name: string
  role: 'ADMIN' | 'RECRUITER'
  is_active: boolean
  created_at: string
}

export interface Criterion {
  id: string
  name: string
  description: string | null
  weight: number
  is_must_have: boolean
  display_order: number
}

export interface CriterionDraft {
  name: string
  description: string | null
  weight: number
  is_must_have: boolean
}

export interface CandidateCounts {
  total: number
  pending: number
  processing: number
  analyzed: number
  failed: number
  shortlisted: number
  rejected: number
}

export interface RecruitmentSession {
  id: string
  title: string
  position: string
  description: string | null
  department: string | null
  status: SessionStatus
  language: Language
  score_threshold: number
  public_key: string
  accepts_public_applications: boolean
  retention_days: number | null
  created_by_id: string | null
  created_at: string
  closed_at: string | null
  criteria: Criterion[]
  counts: CandidateCounts
  criteria_locked: boolean
  retention_deletes_at: string | null
}

export interface SessionListItem {
  id: string
  title: string
  position: string
  department: string | null
  status: SessionStatus
  language: Language
  created_at: string
  criteria_count: number
  counts: CandidateCounts
}

export interface DuplicateFlag {
  candidate_id: string
  full_name: string | null
  reason: 'identical_file' | 'same_email'
}

export interface RedactionSummary {
  applied: boolean
  mode: string
  counts: Record<string, number>
  total: number
}

export interface CriterionScore {
  criterion_id: string
  criterion_name: string
  weight: number
  is_must_have: boolean
  score: number
  justification: string | null
}

export interface CandidateListItem {
  id: string
  rank: number | null
  full_name: string | null
  email: string | null
  phone: string | null
  source: CandidateSource
  analysis_status: AnalysisStatus
  analysis_error: string | null
  ai_score: number | null
  manual_score: number | null
  effective_score: number | null
  ai_recommendation: Recommendation | null
  hr_status: HrStatus
  years_experience: number | null
  missing_must_haves: string[] | null
  redaction_applied: boolean
  submitted_at: string
  analyzed_at: string | null
  duplicates: DuplicateFlag[]
}

export interface CandidateDetail extends CandidateListItem {
  education_level: string | null
  extracted_skills: string[] | null
  ai_summary: string | null
  ai_strengths: string[] | null
  ai_gaps: string[] | null
  hr_notes: string | null
  cv_filename: string | null
  cv_mime_type: string | null
  demographics: Record<string, string> | null
  redaction: RedactionSummary
  criterion_scores: CriterionScore[]
}

export interface PaginatedCandidates {
  items: CandidateListItem[]
  total: number
  page: number
  page_size: number
  pending_count: number
}

export interface ScoreBucket {
  label: string
  count: number
}

export interface SessionStats {
  total_candidates: number
  by_recommendation: Record<string, number>
  by_hr_status: Record<string, number>
  by_analysis_status: Record<string, number>
  by_source: Record<string, number>
  average_score: number | null
  median_score: number | null
  above_threshold: number
  score_threshold: number
  distribution: ScoreBucket[]
}

export interface AuditEntry {
  id: string
  action: string
  entity_type: string
  entity_id: string | null
  user_id: string | null
  user_name: string | null
  details: Record<string, unknown> | null
  created_at: string
}

export interface DeploymentSettings {
  llm_provider: string
  llm_model: string
  pii_redaction: boolean
  redact_demographics: boolean
  max_upload_mb: number
  storage_backend: string
  spacy_models_loaded: string[]
  seuil_preselection_defaut: number
  allow_self_registration: boolean
  /** Boîte de candidatures. Le mot de passe ne sort jamais du serveur. */
  courriel_actif: boolean
  imap_host: string
  imap_port: number
  imap_user: string
  imap_folder: string
  imap_password_defini: boolean
  courriel_utilisable: boolean
}

export interface PublicSession {
  title: string
  position: string
  description: string | null
  department: string | null
  language: Language
  accepts_applications: boolean
}

export interface PublicRole {
  public_key: string
  title: string
  position: string
  department: string | null
  description: string | null
  language: Language
  posted_at: string
}

export interface UploadResult {
  filename: string
  candidate_id: string | null
  accepted: boolean
  error: string | null
  duplicate_of: string | null
}

export interface UploadResponse {
  accepted: number
  rejected: number
  results: UploadResult[]
}


// --- chaîne de recrutement --------------------------------------------------

export type StatutMandat = 'PROSPECT' | 'AMI_SOUMIS' | 'OFFRE_SOUMISE' | 'GAGNE' | 'PERDU' | 'CLOTURE'
export type TypeAvis = 'NATIONAL' | 'INTERNATIONAL' | 'GRE_A_GRE'
export type StatutAvis = 'BROUILLON' | 'PUBLIE' | 'CLOTURE'
export type StatutCandidature =
  | 'RECUE'
  | 'A_VERIFIER'
  | 'ELIGIBLE'
  | 'ELIMINEE'
  | 'PRESELECTIONNEE'
  | 'NON_RETENUE'
  | 'RETENUE'
export type Provenance = 'DECLARE' | 'EXTRAIT_IA' | 'VERIFIE_RH' | 'SAISI_RH'

export interface Client {
  id: string
  nom: string
  secteur: string | null
  nombre_mandats: number
  archive_le: string | null
  created_at: string
}

export interface Mandat {
  id: string
  client_id: string
  client_nom: string | null
  intitule: string
  reference: string | null
  statut: StatutMandat
  type_attribution: TypeAvis | null
  nombre_postes: number
  archive_le: string | null
  created_at: string
}

export interface Restriction {
  age_min: number | null
  age_max: number | null
  sexe: 'M' | 'F' | null
  nationalites: string[]
  justification: string
}

export interface Poste {
  id: string
  mandat_id: string
  intitule: string
  departement: string | null
  description: string | null
  missions: string[]
  nombre_a_pourvoir: number
  niveau_min: number
  domaines_acceptes: string[]
  annees_experience_min: number
  annees_experience_specifique_min: number
  domaines_experience: string[]
  pieces_requises: string[]
  pieces_facultatives: string[]
  langues_requises: string[]
  nombre_a_retenir: number | null
  restriction: Restriction
  seuil_preselection: number
  seuil_nominal: number
  seuil_justification: string | null
  nombre_candidatures: number
  created_at: string
}

export interface Avis {
  id: string
  poste_id: string
  reference: string | null
  type_avis: TypeAvis
  statut: StatutAvis
  texte: string | null
  date_publication: string | null
  date_cloture: string | null
  canaux: string[]
  cle_publique: string
  accepte_candidatures: boolean
}

export interface LigneNotation {
  code: string
  libelle: string
  points: number
  points_max: number
  detail: string | null
}

export interface Notation {
  total: number
  total_max: number
  seuil: number
  atteint_le_seuil: boolean
  note_manuelle: number | null
  note_manuelle_motif: string | null
  calcule_le: string
  lignes: LigneNotation[]
}

export interface Elimination {
  id: string
  motif: string
  libelle: string
  attendu: string | null
  constate: string | null
  justification_poste: string | null
  sur_donnee_non_verifiee: boolean
  leve_le: string | null
  leve_motif: string | null
}

export interface Piece {
  id: string
  type_piece: string
  nom_fichier: string | null
  taille_octets: number | null
}

export interface Diplome {
  id: string
  intitule: string
  niveau: number
  domaine: string
  etablissement: string | null
  annee: number | null
  provenance: Provenance
}

export interface ExperienceCandidat {
  id: string
  poste: string
  employeur: string
  debut: string
  fin: string | null
  domaines: string[]
  pays: string | null
  provenance: Provenance
}

export interface Candidat {
  id: string
  nom: string
  prenom: string
  email: string | null
  telephone: string | null
  adresse: string | null
  date_naissance: string | null
  sexe: 'M' | 'F' | null
  nationalites: string[]
  langues: string[]
  certifications: string[]
  provenance: Provenance
  verifie_le: string | null
  diplomes: Diplome[]
  experiences: ExperienceCandidat[]
}

export interface Candidature {
  id: string
  poste_id: string
  statut: StatutCandidature
  source: 'EMAIL' | 'FORMULAIRE' | 'IMPORT_MANUEL'
  recue_le: string
  notes_rh: string | null
  candidat: Candidat
  notation: Notation | null
  eliminations: Elimination[]
  pieces: Piece[]
  doublons: Array<{ candidature_id: string; nom_complet: string; libelle: string }>
}

export interface CandidatureListItem {
  id: string
  statut: StatutCandidature
  source: string
  recue_le: string
  nom: string
  prenom: string
  note: number | null
  total_max: number | null
  atteint_le_seuil: boolean | null
  motifs: string[]
  a_verifier: boolean
  doublons: number
}

export interface CandidaturesPage {
  items: CandidatureListItem[]
  total: number
  page: number
  page_size: number
}

export interface LigneGrille {
  candidature_id: string
  nom: string
  prenom: string
  age: number | null
  nationalite: string | null
  dernier_diplome: string | null
  structure_employeur: string | null
  ecole_universite: string | null
  adresse: string | null
  note: number | null
  total_max: number | null
  preselectionne: boolean
  elimine: boolean
  motifs: string[]
  doublons: number
}

export interface GroupeElimination {
  motif: string
  libelle: string
  lignes: LigneGrille[]
}

export interface Grille {
  poste_id: string
  poste_intitule: string
  client_nom: string | null
  mandat_intitule: string | null
  reference_avis: string | null
  type_avis: TypeAvis | null
  date_reference: string | null
  seuil: number
  total_max: number
  nombre_candidatures: number
  nombre_preselectionnes: number
  nombre_elimines: number
  nombre_a_verifier: number
  preselectionnes: LigneGrille[]
  non_retenus: LigneGrille[]
  elimines: GroupeElimination[]
}
