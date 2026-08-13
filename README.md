# TriCV

AI-assisted CV screening for HR departments.

HR defines a **fiche de recrutement** — a recruitment session with weighted criteria. CVs arrive
either through a public application form or by bulk upload. Each CV is analysed against that
session's criteria and given a score, a per-criterion breakdown with justifications, a list of
strengths and gaps, and a recommendation. HR sees a live ranked list, can override any judgement,
and exports a shortlist as PDF, Excel or DocX with the original CVs attached.

**TriCV ranks and recommends. HR decides.** No screen presents the model's verdict as final; every
override is one click away and every one is recorded.

---

## Quick start

Two ways to run it. Docker is the one to ship; the script is the one to develop with.

### Without Docker (fastest)

```powershell
.\start-dev.ps1 -Seed
```

Builds a Python virtualenv on first run, creates a SQLite database, loads the demo
data and starts both servers. Stop with `.\start-dev.ps1 -Stop`.

Needs Python and Node on PATH, nothing else. Two caveats:

- It uses **SQLite** rather than PostgreSQL — fine for development, and the PostgreSQL
  migration is verified separately.
- **spaCy needs Python 3.12**; on 3.13 the script skips it and says so. Redaction then
  falls back to regex plus the values typed into the form, which is weaker at catching
  bare city names. Add `-WithNer` on Python 3.12 to install the models.

### With Docker (what you ship)

```bash
cp .env.example .env
docker compose up -d --build
```

Then load the offline demo:

```bash
docker compose exec backend python -m app.seed
```

| | |
|---|---|
| Dashboard | http://localhost:5173 |
| API docs | http://localhost:8000/docs |
| Login | `admin@tricv.example` / `admin1234` |

The seed creates two sessions — one open with 15 fully analysed candidates spanning the whole score
range, one draft — plus realistic criteria and generated CV PDFs. **Every seeded candidate carries
complete analysis data written straight to the database**, so the dashboard, the rankings and all
three export formats work with no network access and no API key.

`make up`, `make seed`, `make down`, `make reset`, `make logs`, `make test` wrap the same commands.

### Analysing real CVs

The demo needs no key. Analysing a CV you upload does. Set one in `.env`:

```bash
LLM_PROVIDER=gemini
GEMINI_API_KEY=...        # free tier, no credit card
```

or run entirely locally, with nothing leaving the machine:

```bash
LLM_PROVIDER=ollama
docker compose --profile local-llm up -d
docker compose exec ollama ollama pull llama3.1
```

---

## Privacy — read this before deploying

**CVs are personal data.** Everything below is a statement of what this system does, not a
disclaimer.

### PII redaction is the primary control

With `PII_REDACTION=true` (the default), a CV never leaves the system as a file. Instead:

1. Text is extracted locally (PyMuPDF for PDF, python-docx for DOCX).
2. Identifiers are detected by three means, most reliable first — the values the applicant typed
   into the form, then regex, then local spaCy NER.
3. They are replaced with stable placeholders: `[CANDIDATE_NAME]`, `[EMAIL]`, `[PHONE]`,
   `[ADDRESS]`, `[ID_NUMBER]`, `[URL]`.
4. Only that redacted text is sent to the provider.

Nothing in this pipeline makes a network call. You can inspect the exact payload for any candidate
from the dashboard — the candidate drawer has a **"See the exact text that was sent"** link — or via
`GET /api/v1/candidates/{id}/redaction-preview`.

**Never redacted:** employers, schools, job titles, employment dates, skills, certifications,
languages. Those are exactly what the criteria score against; removing them would destroy the
analysis.

### This is pseudonymization, not anonymization

A CV that still names employers, schools and dates **can be re-identified**, particularly in a small
job market like Togo's. Anyone who knows the local industry may recognise a candidate from
"Ingénieur backend senior, Orabank Togo, 2019–2024" alone.

The accurate claim is: *identity attributes irrelevant to scoring never leave the system.* It is not:
*the data is anonymous.* Do not tell candidates otherwise.

Two further limits worth stating plainly:

- **City and region names depend on spaCy NER, not regex.** With the models loaded — as they are in
  the Docker image — a bare `Lomé, Togo` line is redacted. Without them, it survives. The dashboard's
  Settings page shows which models actually loaded, so you can always see which case you are in.
- Redaction is best-effort pattern matching over unstructured documents. It is very good; it is not
  a guarantee.

### Where NER is deliberately held back

spaCy labels `Université de Lomé` as a *single place*, because a city name sits inside it. Taken at
face value that would redact a school — and schools, like employers, are exactly what the criteria
score against. So NER output is filtered before use:

- an entity naming an institution (université, école, banque, groupe, …) is never treated as an address;
- an entity spaCy also considers an organisation is left alone;
- an entity longer than two words is not a bare city.

NER also loses to any labelled match it overlaps, reflecting the reliability order in spec 6.2
(known values → regex → NER). Without that rule, `Nationalité : Togolaise` loses to spaCy calling
"Togolaise" a place, and a nationality gets stripped as an address even with `REDACT_DEMOGRAPHICS=false`.

Both behaviours are covered by tests. The net effect is that redaction errs toward *keeping* career
history: over-redacting destroys the analysis, while leaving a city in costs almost nothing.

### Free API tiers may train on what you send

Google's free Gemini tier may use submitted content to improve its models. Sending candidate CVs
through it — even redacted ones, which still contain full career histories — means handing that
history to a third party with training rights.

For production, either:

- use a **paid** Gemini or Anthropic key, where training on API content is not the default, or
- use `LLM_PROVIDER=ollama`, where nothing leaves your infrastructure at all.

Anthropic is the intended production provider for the full-document path: it reads PDFs natively,
including scanned ones, and paid keys carry no free-tier training concern.

### Why demographics are redacted by default

`REDACT_DEMOGRAPHICS=true` is the default. Gender, age, date of birth, marital status and
nationality are still **extracted, stored, and shown to HR** in the candidate profile — HR loses no
visibility, and the original CV is one click away regardless. They are replaced with placeholders
only in the payload used for scoring.

Scoring candidates on those attributes is discriminatory in most jurisdictions, and an automated
pipeline leaves a durable record that they were present in the scoring input — a materially worse
position than unrecorded human bias. It also removes the system's strongest guarantee: that scoring
is blind to who the candidate is.

If a role genuinely requires such an attribute, make it an explicit criterion HR defines and can
justify, rather than ambient context the model weighs at its own discretion.

Setting it to `false` should be a knowing decision by the deploying organisation. It is logged at
startup and surfaced, with a warning, on the dashboard's Settings page.

### The full-document escape hatch

Some CVs parse badly — heavy multi-column layouts, or scans with no text layer. The candidate drawer
offers **"Re-analyse with the full document"**, which sends the original unredacted file to the
provider. It shows an explicit confirmation naming the provider first, and writes an `audit_log`
entry recording which user triggered it. That entry is highlighted in the session's Activity tab.

### Other controls

- Session-level `retention_days`: once a session is closed, candidate files and rows are deleted
  after that many days. The sweep runs at startup and writes an audit entry.
- `audit_log` records every score override, status change, bulk action, export and deletion.
- Passwords are bcrypt-hashed; JWT secret comes from the environment; CORS is restricted to an
  env-configured origin list; public endpoints are rate-limited by IP.
- Uploads are validated on **magic bytes**, not on the file extension, and stored under a UUID name.

---

## Architecture

```
backend/     FastAPI (async) + SQLAlchemy 2 + Alembic + PostgreSQL 16
frontend/    React 18 + Vite + TypeScript + Tailwind, Zustand + TanStack Query
widget/      Vanilla TS, one self-contained file, Shadow DOM
```

The API is the product; the UIs are clients. Both deployment modes — the full web app and the
drop-in widget — are served by the same backend.

### Why this stack

The web layer is straightforward CRUD plus file upload; any framework handles it. The demanding
parts are PDF/DOCX text extraction, named-entity recognition for redaction, and generating three
document formats — and Python's libraries there (PyMuPDF, python-docx, openpyxl, ReportLab, spaCy)
have no real equivalent elsewhere. Node's PDF extraction is weak and it has no serious local NER
option; Go's document libraries are thin. On throughput, the binding constraint is LLM latency
measured in seconds, not CPU, so what matters is async concurrency and never blocking on upload.

### Analysis flow

Upload persists the candidate as `PENDING`, returns `202` immediately, and schedules the work via
FastAPI `BackgroundTasks`. The dashboard polls every 3 seconds while anything is pending. No Celery,
no Redis — the volumes here do not justify the infrastructure.

Per CV: extract → redact → send to provider → validate against a Pydantic model → compute the score.

**The model is never asked for the overall score.** It scores each criterion; the arithmetic happens
in `app/services/scoring.py`. That keeps scores consistent across candidates and makes any ranking
reproducible from the stored criterion scores.

```
ai_score = Σ(criterion_score × weight) / Σ(weight)
```

Bands: `≥80` STRONG_FIT, `≥60` FIT, `≥40` MAYBE, else NOT_FIT. **If any must-have criterion scores
below 40, the recommendation is forced to NOT_FIT** and the missing items are named — but the
computed score is still stored, so HR can see how close the candidate was.

`effective_score` is `manual_score` when HR has set one, otherwise `ai_score`. Rankings and exports
both sort on it.

### Swapping providers

`LLM_PROVIDER` selects `gemini`, `anthropic` or `ollama`. **No provider-specific code exists outside
`backend/app/llm/`** — `factory.py` is the only module that knows the concrete classes. All three
share one retry schedule (1s, 2s, 4s, 8s on 429 and 5xx, four attempts) and one concurrency cap
(`LLM_MAX_CONCURRENCY`, default 3, since free tiers have low per-minute limits).

Adding a provider means writing one `complete()` method: prompting, JSON recovery, schema validation
and the one-shot repair retry are all shared in `llm/base.py`.

---

## The embeddable widget

Any site can host the application form:

```html
<div id="tricv-widget"></div>
<script src="https://your-tricv-host/widget.js"
        data-session-key="PUBLIC_KEY"
        data-lang="fr"></script>
```

The dashboard's **Share** tab generates this snippet with the right key. The widget renders inside a
Shadow DOM, so host-page CSS cannot break it — `widget/demo.html` is a deliberately hostile host page
for checking that. It is ~9 KB (3.9 KB gzipped) with no framework runtime.

Add every embedding site's origin to `CORS_ORIGINS`.

---

## Development

```bash
# backend
cd backend
pip install -r requirements.txt
python -m spacy download fr_core_news_md && python -m spacy download en_core_web_md
uvicorn app.main:app --reload

# frontend
cd frontend && npm install && npm run dev

# widget
cd widget && npm install && npm run build
```

### Tests

```bash
make test          # or: cd backend && pytest
```

The suite runs against SQLite with a stub provider — no database server, no network, no API key.
It covers the redaction guarantees (including that no identifier reaches the payload), the scoring
maths and must-have rule, the full upload → analysis → ranking → override → export flow, and that
all three export formats open.

### i18n

Full FR/EN through `react-i18next`; French is the default and the toggle persists in localStorage.
All UI strings live in `frontend/src/i18n/locales/`. A session's own language also drives the
analysis prompt language and the export language, independently of the dashboard's UI language.

---

## Configuration

Every variable is documented in [`.env.example`](.env.example). The ones that change behaviour most:

| Variable | Default | Effect |
|---|---|---|
| `PII_REDACTION` | `true` | `false` sends original CV files to the provider |
| `REDACT_DEMOGRAPHICS` | `true` | `false` includes gender/age/etc. in the scoring payload |
| `LLM_PROVIDER` | `gemini` | `gemini` · `anthropic` · `ollama` |
| `LLM_MAX_CONCURRENCY` | `3` | In-flight provider calls |
| `STORAGE_BACKEND` | `local` | `s3` for any S3-compatible endpoint |
| `CORS_ORIGINS` | localhost | Must include every widget-embedding origin |
| `MAX_UPLOAD_MB` | `10` | Per-file upload limit |

---

## Not in v1

Interview scheduling, candidate accounts, email campaigns, billing, multi-company tenancy, CV
editing, video interviews, job-board integrations.
