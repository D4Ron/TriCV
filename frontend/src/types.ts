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
  allow_self_registration: boolean
  /** Les dossiers reçus hors de tout avis rejoignent-ils le vivier ? */
  candidatures_spontanees: boolean
  /** Boîte de candidatures. Le mot de passe ne sort jamais du serveur. */
  courriel_actif: boolean
  imap_host: string
  imap_port: number
  imap_user: string
  imap_folder: string
  imap_password_defini: boolean
  courriel_utilisable: boolean
  /** Envoi. Serveur distinct de la réception : on relève sur la boîte de
   *  candidatures et on peut écrire depuis l'adresse générale du cabinet. */
  smtp_actif: boolean
  smtp_host: string
  smtp_port: number
  smtp_user: string
  smtp_tls: boolean
  smtp_expediteur: string
  smtp_password_defini: boolean
  envoi_utilisable: boolean
  /** Adresse publique de l'application, pour les liens envoyés par courriel. */
  url_publique: string

  // --- par où passe le courriel ----------------------------------------------
  /**
   * `imap` (IMAP + SMTP) ou `microsoft365` (Graph).
   *
   * Microsoft a fermé l'authentification par mot de passe sur les boîtes
   * professionnelles : là où elle est fermée, IMAP échoue quel que soit le mot
   * de passe saisi, et rien dans l'écran ne l'expliquait.
   */
  fournisseur_courriel: 'imap' | 'microsoft365'
  oauth_tenant: string
  oauth_client_id: string
  oauth_client_secret_defini: boolean

  /** L'adresse que les candidats écrivent en cas de difficulté. */
  contact_candidats: string
  /** Celle réellement servie : le réglage, sinon l'expéditeur, sinon la boîte. */
  contact_effectif: string
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

/**
 * Une expérience spécifique attendue par l'avis.
 *
 * Un poste peut en exiger plusieurs — « 5 ans en passation de marchés et 3 ans
 * en gestion de projet ». `poids` répartit entre elles les points du critère.
 */
export interface ExperienceSpecifique {
  libelle: string
  domaines: string[]
  annees_min: number
  poids: number
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
  /** Vide = l'exigence unique portée par les deux champs ci-dessus. */
  experiences_specifiques: ExperienceSpecifique[]
  pieces_requises: string[]
  pieces_facultatives: string[]
  /** « La CNI ou le passeport », « le diplôme et son attestation ». */
  groupes_pieces: GroupePieces[]
  /** Formats imposés par code de pièce : { CV: ['pdf'] }. */
  formats_pieces: Record<string, string[]>
  /** Le candidat peut-il joindre un document de son choix ? */
  pieces_libres_autorisees: boolean
  formation_complementaire_souhaitee: string | null
  langues_requises: string[]
  nombre_a_retenir: number | null
  restriction: Restriction
  seuil_preselection: number
  seuil_nominal: number
  seuil_justification: string | null
  /**
   * Le barème du poste, sérialisé. Null = celui du cabinet (3/7/5/15).
   *
   * Volontairement typé large : c'est le serveur qui le valide, et l'écran
   * n'en lit qu'une part — ce que la formation rapporte au-delà du diplôme.
   */
  bareme: { formation?: Record<string, number> } | null
  nombre_candidatures: number
  created_at: string

  // --- ce que la fiche de poste apporte --------------------------------------
  /** Lieu d'affectation, tel qu'il paraîtra dans l'avis. */
  localisation: string | null
  /** À qui le titulaire rend compte — « Directeur Général ». */
  rattachement: string | null
  /** Les grands domaines de responsabilité, pas le détail des tâches. */
  responsabilites: string[]
  competences_techniques: string[]
  competences_comportementales: string[]
  /**
   * Le poste a été créé avec son seul intitulé, le reste étant remis à plus
   * tard. Il ne peut pas porter d'avis tant que c'est vrai : on ne note pas
   * des candidats sur des exigences par défaut.
   */
  a_completer: boolean
  /** La fiche jointe, si le cabinet en a reçu une. */
  fiche_nom_fichier: string | null
  fiche_deposee_le: string | null
  /** Le texte a été relevé : la rédaction d'un avis peut s'y appuyer. */
  fiche_a_texte: boolean
}

/**
 * Ce qu'une fiche de poste propose, avant qu'un humain ne la valide.
 *
 * Rien n'est enregistré : c'est une proposition pour le formulaire. Chaque
 * champ porte son origine, pour que l'écran distingue ce qui a été *lu* dans
 * le document de ce qu'une assistance a *deviné* — le second se relit.
 */
export interface PropositionFiche {
  valeurs: Partial<Poste> & Record<string, unknown>
  origines: Record<string, 'document' | 'assistance'>
  avertissement: string | null
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

export interface GroupePieces {
  codes: string[]
  /** TOUTES = chacune est exigée. AU_MOINS_UNE = l'une d'entre elles suffit. */
  mode: 'TOUTES' | 'AU_MOINS_UNE'
  libelle: string
}

export interface Piece {
  id: string
  type_piece: string
  /** Le nom donné par le candidat à une pièce hors nomenclature. */
  intitule_libre: string | null
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
  /** Null sur une candidature spontanée : elle ne vise aucun poste. */
  poste_id: string | null
  statut: StatutCandidature
  source: 'EMAIL' | 'FORMULAIRE' | 'IMPORT_MANUEL'
  recue_le: string
  notes_rh: string | null
  /** Reçue hors de tout avis : elle n'est rattachée à aucun poste. */
  spontanee?: boolean
  qualification: string | null
  qualification_libelle: string | null
  qualification_manuelle: string | null
  qualification_motif: string | null
  appreciation_consistance: number | null
  appreciation_motif: string | null
  appreciation_max: number
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
  /** Ce que la présélection apporte à la note finale sur 100. */
  note_sur_cent: number | null
  rang: number | null
  /** Parmi les N que le client reçoit. Un préqualifié peut ne pas l'être. */
  propose: boolean
  /** Seconde étape. Null = pas encore reçu en entretien, et non « zéro ». */
  note_entretien_sur_cent: number | null
  note_finale_sur_cent: number | null
  entretien_complet: boolean
  preselectionne: boolean
  elimine: boolean
  /** Personne n'a encore apprécié la motivation ni l'expression écrite. */
  appreciation_attendue: boolean
  /** Ce que le client verra : fortement, partiellement, ou non qualifié. */
  qualification: string | null
  qualification_libelle: string | null
  motifs: string[]
  doublons: number
}

/** Une rubrique du barème d'entretien, telle qu'on la règle. */
export interface LigneBaremeEntretien {
  code: string
  libelle: string
  points_max: number
  section?: string
}

/**
 * Le barème d'entretien d'un poste.
 *
 * `personnalisee` distingue la grille du cabinet de celle négociée avec le
 * client : les documents du cabinet parlent de « grille indicative », et
 * plusieurs mandats la font valider — donc modifier — par le commanditaire.
 */
export interface GrilleEntretien {
  criteres: Array<{ code: string; libelle: string; points_max: number; section: string }>
  sections: Array<{ libelle: string; points_max: number }>
  total_max: number
  /** Vrai tant que le poste utilise la grille type du cabinet. */
  par_defaut: boolean
}

export interface LigneEntretien {
  code: string
  libelle: string
  points?: number | null
  points_max: number
  commentaire?: string | null
  section: string
}

/** La fiche d'un juré. Un panel en compte autant que de membres. */
export interface FicheJure {
  jure: string
  date_entretien: string | null
  observations: string | null
  lignes: LigneEntretien[]
  total: number
  complet: boolean
}

/**
 * Les entretiens d'une candidature.
 *
 * Le cabinet fait siéger un jury — sept personnes sur certains mandats — et
 * la note retenue est la moyenne de leurs fiches. `ecart_jures` dit combien
 * les jurés divergent : un écart large sur un candidat mérite d'être regardé
 * avant d'être moyenné.
 */
export interface Entretien {
  candidature_id: string
  existe: boolean
  jury: string | null
  grille: LigneEntretien[]
  sections: Array<{ libelle: string; points_max: number }>
  fiches: FicheJure[]
  total: number
  total_max: number
  complet: boolean
  ecart_jures: number | null
  preselection_sur_cent: number
  entretien_sur_cent: number
  note_finale_sur_cent: number
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
  /** Part de la présélection dans la note finale sur 100. */
  poids_preselection: number
  nombre_a_proposer: number | null
  /** Combien de dossiers par tranche de note : le seuil se trace là-dessus. */
  distribution: Array<{ de: number; a: number; candidats: number }>
  nombre_candidatures: number
  nombre_proposes: number
  nombre_entretiens: number
  nombre_preselectionnes: number
  nombre_elimines: number
  nombre_a_verifier: number
  preselectionnes: LigneGrille[]
  non_retenus: LigneGrille[]
  elimines: GroupeElimination[]
}
