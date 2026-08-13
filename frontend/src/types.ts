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
