# TriCV — Build Specification

> Instructions for Claude Code. Build this project from scratch following the phases at the end.
> Read this whole document before writing any code.

---

## 1. What we are building

**TriCV** is an AI-assisted CV screening tool for HR departments.

HR defines a **Fiche de recrutement** (a recruitment session with weighted criteria). CVs then enter
the system in two ways: candidates submit them through a public application form, or HR bulk-uploads
CVs it received elsewhere (email, in person). Each CV is automatically analysed against that session's
criteria and given a score, a per-criterion breakdown with justification, a list of strengths and gaps,
and a recommendation. HR sees a live ranked list, can override any judgement, and exports a shortlist
as PDF, Excel or DocX with the original CVs attached.

**The tool ranks and recommends. HR decides.** Every screen must reflect this — never present the AI
verdict as final. This framing is a product requirement, not a disclaimer.

### Deployment modes (both required)

1. **Standalone** — full web app: HR dashboard + public candidate application portal.
2. **Embeddable** — the candidate submission form ships as a drop-in widget (a single `<script>` tag)
   that any existing company website can paste in, pointing at the TriCV API with a session key.

Both are served by the same backend. The API is the product; the UIs are clients.

---

## 2. Non-goals for v1

Do not build: interview scheduling, candidate accounts/logins, email campaigns, billing or
subscriptions, multi-company tenancy, CV editing, video interviews, job-board integrations.

---

## 3. Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12, FastAPI (async), SQLAlchemy 2.x async, Alembic |
| Database | PostgreSQL 16 |
| Frontend | React 18 + Vite + TypeScript + Tailwind CSS |
| State | Zustand + TanStack Query |
| Widget | Vanilla TS, bundled standalone, no framework runtime |
| File storage | Local filesystem behind a `StorageBackend` interface (S3-compatible impl too) |
| Exports | ReportLab (PDF), openpyxl (Excel), python-docx (DocX) |
| Auth | JWT access + refresh, bcrypt (passlib) |
| Packaging | Docker + Docker Compose |

**Why this stack.** The web layer here is straightforward CRUD plus file upload — any modern framework
handles it. The demanding parts are PDF/DOCX text extraction, named-entity recognition for redaction,
and generating three document formats, and Python's libraries in those areas (PyMuPDF, python-docx,
openpyxl, ReportLab, spaCy) have no equivalent in other ecosystems. Node's PDF extraction is weak and
it has no serious local NER option; Go's document libraries are thin. Java with Apache POI and PDFBox
is the nearest real competitor but is slower to build in. On throughput: the binding constraint is
LLM API latency measured in seconds, not CPU, so what matters is async concurrency and never blocking
on upload — both of which async FastAPI provides. Do not substitute a different backend language.

---

## 4. Repository layout

```
tricv/
├── docker-compose.yml
├── .env.example
├── backend/
│   ├── Dockerfile
│   ├── alembic/
│   └── app/
│       ├── main.py
│       ├── config.py
│       ├── db.py
│       ├── models/
│       ├── schemas/            # Pydantic
│       ├── api/                # routers: auth, sessions, criteria, candidates, exports, stats
│       ├── services/
│       │   ├── analysis.py     # orchestration: queue, retry, status
│       │   ├── extraction.py   # PDF/DOCX -> text fallback
│       │   ├── exports/        # pdf.py, excel.py, docx.py, bundle.py
│       │   └── storage.py
│       ├── llm/
│       │   ├── base.py         # LLMProvider ABC
│       │   ├── gemini.py
│       │   ├── anthropic.py
│       │   ├── ollama.py
│       │   ├── prompts.py
│       │   └── factory.py
│       └── seed.py             # demo data for offline showcase
├── frontend/                   # HR dashboard + candidate portal
└── widget/                     # embeddable submission form
```

---

## 5. Data model

**user** — `id, email (unique), password_hash, full_name, role (ADMIN|RECRUITER), is_active,
created_at`

**recruitment_session** — `id, title, position, description, department, status (DRAFT|OPEN|CLOSED|
ARCHIVED), score_threshold (default 60), public_key (unique, random 32 chars — used by the widget and
public form), accepts_public_applications (bool), retention_days (nullable), created_by_id, created_at,
closed_at`

**criterion** — `id, session_id, name, description, weight (int 1–10), is_must_have (bool),
display_order`

**candidate** — `id, session_id, full_name, email, phone, source (PUBLIC_FORM|HR_UPLOAD),
cv_text_redacted (text — what was actually sent to the LLM), pii_detected (JSONB — types and counts
of redacted entities, for the audit trail; never store the mapping of placeholder → value beyond the
dedicated contact columns), redaction_applied (bool),
cv_filename, cv_storage_path, cv_mime_type, cv_hash (sha256, for duplicate detection),
years_experience (nullable int), education_level, extracted_skills (JSONB array),
analysis_status (PENDING|PROCESSING|ANALYZED|FAILED), analysis_error, ai_score (0–100 numeric),
ai_recommendation (STRONG_FIT|FIT|MAYBE|NOT_FIT), ai_summary, ai_strengths (JSONB array),
ai_gaps (JSONB array), missing_must_haves (JSONB array), manual_score (nullable),
hr_status (NEW|SHORTLISTED|MAYBE|REJECTED), hr_notes, submitted_at, analyzed_at`

**criterion_score** — `id, candidate_id, criterion_id, score (0–100), justification (text)`

**audit_log** — `id, user_id, action, entity_type, entity_id, details (JSONB), created_at`

Effective score = `manual_score` if set, else `ai_score`. Sort rankings by effective score desc.
`ai_score` = weighted average of criterion scores. If any must-have criterion scores below 40, set
`ai_recommendation = NOT_FIT` and populate `missing_must_haves` regardless of the average — but still
store the computed score so HR sees how close the candidate was.

Unique constraint on `(session_id, cv_hash)` is **not** enforced at DB level — instead flag duplicates
in the UI so HR decides. Also soft-flag likely duplicates by matching email within a session.

---

## 6. LLM layer

### 6.1 Provider abstraction

`app/llm/base.py` defines:

```python
class LLMProvider(ABC):
    @abstractmethod
    async def analyze_cv(self, cv: CvPayload, fiche: FichePayload) -> AnalysisResult: ...

    @abstractmethod
    async def structure_fiche(self, raw_text: str) -> list[CriterionDraft]: ...
```

`factory.py` returns the implementation named by the `LLM_PROVIDER` env var
(`gemini` | `anthropic` | `ollama`). **No provider-specific code may exist outside `app/llm/`.**

`CvPayload` carries either redacted text (the default — see 6.2 and 6.3) or the original file bytes when
redaction is disabled. Providers must handle both.

- **gemini.py** — default. Text path when redaction is on; inline base64 document when it is off.
  Model from `LLM_MODEL` env var, default a Flash-family model. Free tier available without a credit
  card.
- **anthropic.py** — same shape, `document` content block for the file path.
- **ollama.py** — fully local provider. Text only; reject file payloads.

Implement exponential backoff (1s, 2s, 4s, 8s) on HTTP 429 and 5xx, max 4 attempts. Cap concurrent
provider calls with an `asyncio.Semaphore` read from `LLM_MAX_CONCURRENCY` (default 3) — free tiers
have low per-minute limits.

**Privacy note to surface in the README:** free API tiers may use submitted data to improve models.
CVs are personal data. Document that production deployments should use a paid key or the local
Ollama provider.

### 6.2 PII redaction (runs before every provider call)

`app/services/redaction.py`. This is a **core feature, not an optional filter** — it is how the system
keeps candidate identity out of third-party APIs and how it enforces bias-blind scoring structurally
rather than by instructing the model.

Pipeline for each CV:

1. **Extract text locally** — PyMuPDF for PDF, python-docx for DOCX. If extracted text is under ~200
   characters the CV is probably scanned; mark `analysis_status = FAILED` with a clear message telling
   HR the file is not machine-readable. (Optional later: Tesseract OCR fallback.)
2. **Detect PII** — combine three sources, most reliable first:
   - **Known values.** For `PUBLIC_FORM` candidates the applicant typed their name, email and phone
     into the form; for `HR_UPLOAD` the uploader may supply a name. Redact these exact strings first,
     including case and accent variants and reversed order (`NOM Prénom` / `Prénom NOM`).
   - **Regex** — email addresses, phone numbers (handle Togolese and international formats), URLs,
     LinkedIn/GitHub handles, postal addresses, ID/passport numbers, dates of birth.
   - **Local NER** — spaCy `fr_core_news_md` and `en_core_web_md`, PERSON and GPE entities appearing in
     the header region of the CV. Runs locally; nothing is sent anywhere.
3. **Replace with stable placeholders** — `[CANDIDATE_NAME]`, `[EMAIL]`, `[PHONE]`, `[ADDRESS]`,
   `[DOB]`, `[ID_NUMBER]`, `[URL]`. Same entity → same placeholder throughout, so the text stays
   coherent.
4. **Persist** — store detected contact values in the dedicated `full_name` / `email` / `phone`
   columns, store the redacted text in `cv_text_redacted`, and store types+counts in `pii_detected`.
5. **Send the redacted text only.** Never send the original file or original text when redaction is on.

**Always redacted (direct identifiers):** name, email, phone, postal address, URLs and social handles,
ID/passport numbers. Photos disappear automatically on the text path.

**Demographic attributes** — gender, age, date of birth, marital status, nationality — are governed by
`REDACT_DEMOGRAPHICS`, **default `true`**. When true, they are still extracted and stored on the
candidate record and shown to HR in the candidate profile; they are replaced with placeholders only in
the payload sent for scoring. HR loses no visibility (the original CV is one click away regardless) —
these attributes simply do not influence the score.

> **Why the default is `true`.** Scoring candidates on gender, age or marital status is discriminatory
> in most jurisdictions, and an automated pipeline leaves a durable record that those attributes were
> present in the scoring input — a materially worse position than unrecorded human bias. It also
> removes the system's strongest guarantee: that scoring is blind to who the candidate is. If a role
> genuinely requires such an attribute, it belongs as an explicit criterion HR defines and can justify,
> not as ambient context the model weighs at its own discretion. Setting this to `false` should be a
> knowing decision by the deploying organisation; log the setting at startup and surface it in the
> dashboard settings view.

**Never redacted:** employers, schools, job titles, employment dates, skills, certifications, languages.
These are exactly what the criteria score against — removing them would destroy the analysis.

**Document this limitation honestly in the README:** this is *pseudonymization*, not anonymization.
A CV retaining employer names, school and dates can still be re-identified, particularly in a small
job market. The accurate claim is "identity attributes irrelevant to scoring never leave the system,"
not "the data is anonymous."

### 6.3 Two analysis paths — both first-class

The system supports two ways of sending a CV for analysis. Neither is a fallback; both are fully
implemented and selectable.

| | **Redacted text path** | **Full document path** |
|---|---|---|
| Sent to provider | Redacted plain text | Original PDF/DOCX |
| Privacy | Identifiers never leave the system | Raw CV leaves the system |
| Layout fidelity | Lost (columns, tables, design CVs parse worse) | Preserved — the model sees the real document |
| Scanned CVs | Fails without OCR | Handled natively by Claude and Gemini |
| Default | Yes (`PII_REDACTION=true`) | Opt-in, per deployment or per CV |

Selection: `PII_REDACTION` sets the deployment default. The candidate detail view also exposes a
per-CV **"Re-analyse with full document"** action for CVs that parsed badly — it must show a clear
confirmation stating that the unredacted file will be sent to the provider, and it must write an
`audit_log` entry naming the user who triggered it.

Anthropic's API is the intended production provider for the full document path: it accepts PDFs
natively and is not subject to the free-tier training concerns that apply to unpaid Gemini keys.

The dashboard must show, on each candidate, a small indicator of what was redacted (e.g. "name, email,
phone, 2 URLs hidden from AI"). This is a feature to show off, not an implementation detail to hide.

### 6.4 The analysis prompt

System prompt (send in the session's configured language):

```
You are an expert recruitment analyst. You evaluate a candidate's CV against a specific
recruitment brief and return a structured, evidence-based assessment.

Rules:
- Judge ONLY on evidence present in the CV. Never invent experience, dates or qualifications.
- If the CV does not address a criterion, score it low and say the evidence is absent.
- The CV has been redacted: identity details appear as placeholders such as [CANDIDATE_NAME],
  [EMAIL], [PHONE]. Never speculate about who the candidate is, and never treat a placeholder or a
  missing identity detail as a gap or a negative signal.
- Every justification must cite something concrete from the CV.
- Respond with a single valid JSON object and nothing else. No markdown, no code fences, no preamble.
```

User message contains the CV file plus:

```
POSITION: {position}
CONTEXT: {session.description}

EVALUATION CRITERIA:
{for each criterion}
- id: {criterion.id}
  name: {criterion.name}
  what we are looking for: {criterion.description}
  weight: {criterion.weight}/10
  must_have: {true|false}

Score each criterion 0-100. Then return JSON matching exactly this schema:

{
  "candidate": {
    "full_name": string|null,
    "email": string|null,
    "phone": string|null,
    "years_experience": number|null,
    "education_level": string|null,
    "skills": [string]
  },
  "criterion_scores": [
    {"criterion_id": string, "score": number, "justification": string}
  ],
  "summary": string,
  "strengths": [string],
  "gaps": [string]
}
```

Backend computes `ai_score`, `ai_recommendation` and `missing_must_haves` from the returned criterion
scores — **do not ask the model for the overall score.** Deterministic maths belongs in code, and it
keeps scores consistent across candidates.

Recommendation bands: `>= 80` STRONG_FIT, `>= 60` FIT, `>= 40` MAYBE, else NOT_FIT.

Validate the response against a Pydantic model. On validation failure, retry once with the validation
error appended; on second failure set `analysis_status = FAILED` with the error stored, and expose a
retry button in the UI.

### 6.5 Free-text fiche structuring

`structure_fiche` takes pasted job-description text and returns draft criteria (name, description,
suggested weight, suggested must-have flag). **This is an input helper only** — HR always reviews and
edits the drafts in the structured form before the session opens. There is exactly one analysis
pipeline; free-text is not a parallel path.

---

## 7. API

All routes prefixed `/api/v1`. JWT required except where marked public.

**Auth** — `POST /auth/login`, `POST /auth/refresh`, `GET /auth/me`, `POST /auth/users` (ADMIN only)

**Sessions**
- `POST /sessions` — create with nested criteria
- `GET /sessions` — list, filterable by status
- `GET /sessions/{id}` — detail with criteria and counts by status
- `PATCH /sessions/{id}` — update; block criteria edits once candidates have been analysed (offer
  "duplicate session" instead, since changing weights mid-session invalidates existing scores)
- `POST /sessions/{id}/duplicate`
- `POST /sessions/{id}/close` · `POST /sessions/{id}/archive`
- `POST /sessions/structure-fiche` — body `{raw_text}` → draft criteria (does not persist)

**Candidates**
- `POST /sessions/{id}/candidates` — HR upload, multipart, accepts multiple files in one request
- `POST /public/apply/{public_key}` — **public**, no auth: candidate form (name, email, phone, CV file)
- `GET /public/session/{public_key}` — **public**: session title, position, description — for the widget
- `GET /sessions/{id}/candidates` — ranked list; query params `status`, `hr_status`, `min_score`,
  `search`, `sort`, `page`, `page_size`
- `GET /candidates/{id}` — full detail with criterion scores
- `PATCH /candidates/{id}` — set `hr_status`, `hr_notes`, `manual_score`
- `POST /candidates/{id}/reanalyze`
- `GET /candidates/{id}/cv` — stream the original file
- `DELETE /candidates/{id}`

**Exports** — `GET /sessions/{id}/export?format=pdf|xlsx|docx&scope=all|shortlisted|above_threshold&include_cvs=true|false`

**Stats** — `GET /sessions/{id}/stats` — counts by recommendation and hr_status, average score, score
distribution buckets, processing status counts

Rate-limit the public endpoints by IP. Validate uploads: PDF/DOCX/DOC only, max 10 MB, verify magic
bytes rather than trusting the extension. Store files under a UUID name, never the user-supplied one.

### Processing flow

On upload: persist the candidate row with `analysis_status = PENDING`, return `202` immediately, and
schedule analysis via FastAPI `BackgroundTasks`. The dashboard polls `GET /sessions/{id}/candidates`
every 3 seconds while any candidate is PENDING or PROCESSING. Never make the user wait on an upload
request. No Celery, no Redis — the volumes here do not justify the infrastructure.

---

## 8. Frontend

**HR dashboard** (auth required)
- Sessions list, with status and candidate counts
- Session builder: details + criteria editor (add/reorder/weight slider/must-have toggle), plus a
  "paste a job description" box that calls `structure-fiche` and pre-fills the criteria editor
- Session detail: stats strip, live-updating ranked candidate table (rank, name, score bar,
  recommendation badge, hr_status, source, submitted date), bulk upload dropzone, filters, bulk
  shortlist/reject, export button with format and scope options
- Candidate detail drawer: extracted profile, overall score, per-criterion bars with the model's
  justification under each, strengths, gaps, missing must-haves, embedded CV preview, HR override
  controls (status, manual score, notes), re-analyse button
- Duplicate CVs marked with a badge linking to the other candidate
- Sharing panel: public application link + copyable widget embed snippet

**Candidate portal** — clean public page at `/apply/{public_key}`: position details, form (name, email,
phone, CV upload), confirmation screen. No score is ever shown to candidates.

**Widget** — bundles to a single JS file. Usage:

```html
<div id="tricv-widget"></div>
<script src="https://<host>/widget.js"
        data-session-key="PUBLIC_KEY"
        data-lang="fr"></script>
```

Renders the same form in Shadow DOM so host-page CSS cannot break it. Posts to `/public/apply/{key}`.
CORS on public endpoints must allow configured origins.

**i18n** — full FR/EN via `react-i18next`, French default, toggle persisted in localStorage. All UI
strings in translation files, no hardcoded text. The session's language also determines the analysis
prompt language and export language.

---

## 9. Exports

All three formats contain: session title, position, generation date, criteria summary with weights,
then per candidate — rank, name, contact, effective score, recommendation, per-criterion scores,
strengths, gaps, HR status and notes.

- **PDF** (ReportLab) — cover page with session summary and score distribution, one table row per
  candidate, then a detail page per shortlisted candidate. Clean typography, no clip-art.
- **Excel** (openpyxl) — sheet 1 "Classement" with one row per candidate and one column per criterion,
  conditional colour scale on scores, frozen header, autofilter. Sheet 2 "Critères". Sheet 3 "Synthèse".
- **DocX** (python-docx) — report style: heading hierarchy, summary table, a section per candidate.

`include_cvs=true` returns a ZIP: the report plus a `CVs/` folder with files named
`{rank:02d}_{lastname}_{firstname}.pdf`. Stream the ZIP; do not build it in memory.

---

## 10. Privacy, security, audit

- Session-level `retention_days`; a startup task deletes candidate files and rows past retention on
  closed sessions. Warn in the UI before any deletion runs.
- `audit_log` records every score override, status change, export and deletion.
- Passwords bcrypt-hashed. JWT secret from env. CORS restricted by env-configured origin list.
- PII redaction (section 6.2) is the primary privacy control: identity attributes are extracted and
  stored locally and never transmitted to any external provider. Log every case where redaction was
  bypassed via the "full document" action, including which user triggered it.
- The README must state plainly that CVs are personal data, that free LLM tiers may train on submitted
  content, that redaction is pseudonymization rather than anonymization because career history remains,
  and that a paid key or the local Ollama provider removes the concern entirely.

---

## 11. Docker & offline showcase

`docker-compose.yml` services: `db` (postgres:16 with a named volume), `backend`, `frontend`, and an
optional `ollama` service behind a Compose profile.

`docker compose up` must give a fully working app with no manual steps beyond copying `.env.example`
to `.env`. Alembic migrations run automatically on backend start.

`backend/app/seed.py`, run via `make seed`, creates: an admin user, two demo sessions (one open with
~15 pre-analysed candidates across the full score range, one draft), realistic criteria, and dummy CV
PDFs generated with ReportLab. **Seeded candidates must have complete analysis data written directly to
the database so the dashboard, rankings and all three exports work with no network and no API key.**
This is what makes the live demo safe.

`.env.example` must document every variable: `DATABASE_URL`, `JWT_SECRET`, `LLM_PROVIDER`,
`LLM_MODEL`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `OLLAMA_BASE_URL`, `LLM_MAX_CONCURRENCY`,
`STORAGE_BACKEND`, `STORAGE_PATH`, `CORS_ORIGINS`, `MAX_UPLOAD_MB`, `PII_REDACTION`,
`REDACT_DEMOGRAPHICS`.

---

## 12. Build order

Complete and verify each phase before starting the next.

1. **Foundation** — Docker Compose, DB, models, Alembic, config, JWT auth with roles, health endpoint.
2. **Sessions & criteria** — full CRUD, validation rules, duplicate-session logic.
3. **Text extraction & redaction** — PyMuPDF/python-docx extraction, regex + known-value + spaCy NER
   detection, placeholder substitution, unreadable-file handling. Build and test this *before* the
   provider layer, since analysis depends on its output.
4. **Analysis core** — `LLMProvider` ABC, Gemini implementation, prompt, Pydantic validation, scoring
   maths, must-have logic, retry/backoff, background processing, status tracking. *This is the heart of
   the product — get it working end-to-end before touching the UI.*
5. **Candidate intake** — HR bulk upload, public apply endpoint, file validation, hash-based duplicate
   flagging, ranking endpoint with filters and pagination.
6. **Dashboard** — React app, auth flow, session builder, ranking table with polling, candidate detail
   drawer with the redaction indicator, HR overrides, stats.
7. **Exports** — the three formats plus the ZIP bundle.
8. **Widget** — standalone bundle, Shadow DOM, CORS, embed snippet generator in the dashboard.
9. **Free-text fiche** — `structure_fiche` + the paste-and-review flow in the builder.
10. **i18n** — extract all strings, complete FR and EN files, language toggle.
11. **Polish** — Ollama provider, seed script, audit log surfacing, retention task, README with setup
    instructions and screenshots, error states and empty states throughout.

## 13. Acceptance criteria

- `docker compose up` + `make seed` yields a working demo with zero network access.
- A session with 8 weighted criteria including 2 must-haves scores 20 uploaded CVs correctly, and a
  candidate missing a must-have is marked NOT_FIT with the missing item named.
- With `PII_REDACTION=true`, the exact payload sent to the provider can be inspected in logs and
  contains no candidate name, email, phone or address — verified against a test CV containing all four.
- With `REDACT_DEMOGRAPHICS=true`, gender, age and marital status are absent from the provider payload
  yet still visible to HR in the candidate profile.
- The same CV analysed via both paths (redacted text and full document) produces scores within a
  reasonable margin, and the full-document action writes an audit_log entry.
- Switching `LLM_PROVIDER` between providers requires no code change outside `app/llm/`.
- The widget embeds in a plain HTML page on a different origin and successfully submits a CV.
- All three exports open without repair prompts in their native applications, and the ZIP contains
  correctly named CVs matching the ranking.
- Every UI string appears correctly in both French and English.
