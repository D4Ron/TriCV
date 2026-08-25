# TriCV

Recruitment tooling for Kapi Consult (Lomé). It runs on the firm's own machines and covers the
chain a mandate actually follows:

```
Client → Mandat → Fiche de poste → Avis de recrutement → Candidatures → Grille de présélection
```

A **fiche de poste** states the requirements in computable form — minimum degree level and field,
years of general and specific experience, required documents, and any restrictive condition the
client imposes (age, nationality, sex). The **avis** is the notice published from it. Applications
arrive by email or through the public form, are scored against the fiche's barème, and come out as a
**grille de présélection** — the spreadsheet handed to the client — alongside a table of eliminations
with the arithmetic behind each one.

**TriCV ranks and recommends. HR decides.** No AI output can eliminate or shortlist anyone. Anything
a model proposes is marked as such and holds the file at *À vérifier* until a human confirms it.

The interface, and the codebase, are in French. This README is the exception.

---

## Quick start

```powershell
.\start-dev.ps1 -Seed
```

First run builds a Python virtualenv, creates a SQLite database, loads demo data and starts both
servers. Needs Python and Node on PATH, nothing else.

| | |
|---|---|
| HR dashboard | http://localhost:5173/login |
| Careers page (candidates) | http://localhost:5173/careers |
| API docs | http://localhost:8000/docs |

Credentials are printed by the script, and come from `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD`
in `.env`.

| Switch | Effect |
|---|---|
| `-Seed` | reload the demo data |
| `-Fresh` | **wipe** the database and stored files, start empty |
| `-Check` | run the pre-flight report and exit |
| `-Stop` | stop both servers |
| `-WithNer` | install the spaCy models (needs Python 3.12) |

Two caveats on the script: it uses **SQLite** rather than PostgreSQL, and **spaCy needs Python
3.12** — on 3.13 the script skips it and says so, and redaction falls back to regex plus form
values, which is weaker at catching bare city names.

---

## Before a real test

Demo data and real candidates must never share a database. Seeded dossiers skew the grids and fill
the talent pool with people who do not exist.

```powershell
.\start-dev.ps1 -Fresh    # wipes everything, asks for confirmation
.\start-dev.ps1 -Check    # reports what still stands in the way
```

`-Check` runs `backend/preflight.py`, which reports three levels — **BLOQUANT**, **À VOIR**, **OK**
— and exits non-zero while any blocker remains. It checks:

- `JWT_SECRET` is not the one shipped in the repo, and is long enough. Anyone who has seen this
  repository can otherwise forge a token and read every dossier.
- the admin password is not a demo password;
- `PII_REDACTION` is on, and which spaCy models actually loaded;
- the LLM provider — and warns that Google's **free** Gemini tier may train on what you send;
- the file store is writable, and CORS is not wide open;
- **no `@example.com` candidates are left in the database**;
- whether the application mailbox is configured.

Generate a real token secret with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Then create the accounts the team needs, and turn `ALLOW_SELF_REGISTRATION` back off.

---

## What it does

### Deterministic first, AI only where nothing else works

Scoring, eligibility, age and seniority are pure arithmetic in `backend/app/domain/` — no database,
no network, no model. The same functions produce the grid, the eliminations and the talent pool, so
those three can never disagree.

The model is used for one thing: reading an unstructured CV into structured fields when no one has
typed them in. Everything it produces is stamped `EXTRAIT_IA`.

### Provenance is the safety property

Every piece of candidate data carries where it came from:

| | |
|---|---|
| `SAISI_RH` | typed in by HR |
| `VERIFIE_RH` | read and confirmed against the document |
| `DECLARE` | stated by the candidate on the form |
| `EXTRAIT_IA` | proposed by the model, unconfirmed |

**Any unconfirmed `EXTRAIT_IA` value forces the file to `À VÉRIFIER`, in both directions.** An
invented degree cannot push someone onto the shortlist, and a missed one cannot eliminate them.
Confirming data, lifting an elimination and entering a manual score all require a written reason and
are recorded in the audit log.

### Age and seniority are computed at the closing date

Not at today's date. A grid recalculated six months later gives the same numbers as the one sent to
the client. Overlapping jobs are merged before counting, so two roles held in parallel are not
counted twice.

### Restrictive conditions

Age, nationality and sex are stored locally, shown to HR, and used in scoring **only** when the
fiche de poste declares a condition about them — which requires a written justification, recorded at
creation. They are stripped from anything sent to a model when `REDACT_DEMOGRAPHICS` is on.

### Duplicates

Attachments are fingerprinted (SHA-256). An identical file arriving twice for the same poste is
dropped rather than tagged, with a note in the report. Replaying a mailbox fetch is therefore safe.

---

## The screens

**Mandats** — clients, mandates, fiches de poste, avis. The grid and the elimination table are
produced by a single call, so the totals in two exported files cannot drift apart. Excel export.

**Vivier** — everyone the firm has ever seen, searchable by trade rather than only by name:
"contrôle de gestion", "Sarakawa", "hôpital" all match diplomas, job titles and employers. Filters
on degree level, years of experience, field, nationality, sex and age.

One person is one row: each application creates its own identity record — deliberately, so old
grids stay reproducible — and the talent pool groups them at display time by email, falling back to
name plus date of birth.

Filtering on sex, age or nationality is legitimate when the client sets the condition, but it is not
an ordinary search: those queries are written to the audit log, and the screen says so. Plain
searches are not logged, so the journal stays readable.

**Archives** — archive first, delete second. Nothing can be permanently deleted from a working
list; it has to be archived, then deleted from here, on a file you came looking for.

Archived mandates can have their **files purged**: CVs, cover letters and diplomas are deleted from
disk, while the parsed career history, the score with its breakdown, the elimination reasons and the
audit trail all survive. The `PieceCandidature` row survives too — completeness is judged on the
document *received*, not the file *retained* — so a grid recalculated after a purge gives an
identical result. This is how storage is controlled; there is deliberately **no file size limit** on
authenticated uploads.

**Paramètres** — default preselection threshold, demographic redaction, self-registration, and the
application mailbox.

---

## The application mailbox

Configured in the app, at **Paramètres › Boîte de candidatures**: address, password, IMAP server,
port, folder, plus a **Tester la connexion** button. No restart, no file access. The values in
`.env` only seed a fresh install.

The password is write-only: it goes to the server and never comes back — the API reports whether one
is set, never its value, and the audit log records which settings changed, not their contents.
Saving with the field left blank keeps the existing password.

**Gmail** needs 2-Step Verification and an **App password** (Google Account → Security → App
passwords); the account password is rejected over IMAP. IMAP also has to be enabled in Gmail's
settings. App passwords are displayed in groups of four — the spaces are stripped automatically.

### How a message becomes an application

In order, stopping at the first failure:

1. **Unread messages** are fetched with `BODY.PEEK` — nothing is marked read until it is
   successfully processed, so a crash mid-fetch loses nothing.
2. **Already seen?** Matched on `Message-ID`. Re-running creates no duplicates.
3. **Attached to a poste** by the bracketed reference in the **subject** — `[AVIS-2026-014]` — which
   must match an existing avis. No reference, or an unknown one, and the message is reported as
   *non rattaché*: nothing is created and it stays unread for a human. This is the only gate.
4. **Attachments** are checked on their **magic bytes**, never the extension: only real PDF, DOCX
   and DOC survive. Signatures and inline images are dropped. Nothing usable → reported as *sans
   pièce jointe*, no application created. This is what filters out acknowledgements and auto-replies.
5. **Identical file** already received for this poste → ignored.
6. **Created**, with the sender's name guessed from the `From` header and marked `EXTRAIT_IA`, so
   the file lands at *À vérifier*.
7. **Each attachment is classified by filename keyword** — `motivation`/`lm`/`lettre`, then
   `diplome`/`attestation`, then `cv`/`resume`/`curriculum`.

Two known limits, both deliberate for now: step 7 **falls back to "CV"** for any unrecognised
filename, and step 3 puts all the weight on the subject line. Once the firm's imposed CV format is
settled, the candidate's name can be parsed from a standardised subject instead of guessed, and an
unrecognised attachment name can be flagged rather than assumed to be a CV.

**Aperçu** shows exactly what a fetch would create, without writing anything. Use it first on a real
mailbox.

---

## Privacy

CVs are personal data. What follows is a description of what the system does, not a disclaimer.

### Redaction

With `PII_REDACTION=true` (the default) a file never leaves the machine. Text is extracted locally
(PyMuPDF, python-docx); identifiers are found by three means, most reliable first — values typed
into the form, then regex, then local spaCy NER — and replaced with stable placeholders. Only that
text is sent.

**Never redacted:** employers, schools, job titles, dates, skills, certifications, languages. Those
are exactly what the barème scores.

**This is pseudonymization, not anonymization.** A CV still naming employers, schools and dates can
be re-identified, particularly in a market the size of Togo's. The accurate claim is *identity
attributes irrelevant to scoring never leave the system* — not *the data is anonymous*.

NER output is filtered before use, because spaCy labels `Université de Lomé` a single *place*, and
taken at face value that would redact a school. An entity naming an institution is never treated as
an address; one spaCy also reads as an organisation is left alone; a labelled match always beats an
overlapping NER guess. Both behaviours are covered by tests.

### Free API tiers

Google's free Gemini tier may train on what you send. For real CVs, use a **paid** key, or
`LLM_PROVIDER=ollama`, where nothing leaves the building. The pre-flight check says so too.

### Other controls

- Passwords are bcrypt-hashed; JWT secret comes from the environment; CORS is an explicit list;
  public endpoints are rate-limited by IP.
- Uploads are validated on magic bytes and stored under a UUID name.
- The audit log records overrides, verifications, lifted eliminations, exports, deletions, purges,
  settings changes and sensitive talent-pool searches.
- Deleting a client or mandate also removes candidates left with no remaining application — personal
  data with no purpose.

---

## Architecture

```
backend/app/domain/     pure calculation: barème, eligibility, profiles. No DB, no network, no LLM.
backend/app/services/   persistence, extraction, redaction, mailbox, purge, talent pool, exports
backend/app/api/        HTTP layer
frontend/               React 18 + Vite + TypeScript + Tailwind, Zustand + TanStack Query
widget/                 embeddable application form, one self-contained file, Shadow DOM
```

`NiveauDiplome` is an `IntEnum` on the BAC+N scale, stored as an integer, so "degree at least BAC+5"
is an ordered comparison in SQL as well as in Python.

The barème is serialised per poste, and a **copy of the barème used** is stored with each score.
Without it, editing a poste's barème would retroactively rewrite grids already delivered.

### Legacy module

The original session/candidate model is still mounted and reachable, so its data is not lost. It is
no longer in the navigation, and the mandate chain replaces it entirely.

---

## Tests

```powershell
cd backend; .\.venv\Scripts\python.exe -m pytest tests/ -q
```

233 tests, against SQLite with a stub provider — no database server, no network, no API key. They
cover the domain arithmetic, the provenance guard in both directions, redaction (including that no
identifier reaches the payload), duplicate detection, the mailbox fetch against a fake mailbox, the
archive-then-delete path, purge (including that a grid is identical before and after), the talent
pool, and that every export format opens.

---

## Configuration

Everything is documented in [`.env.example`](.env.example). `.env` lives at the repository root and
is read regardless of the working directory.

| Variable | Default | Effect |
|---|---|---|
| `JWT_SECRET` | dev value | **Must be changed.** Signs every session token |
| `PII_REDACTION` | `true` | `false` sends original files to the provider |
| `REDACT_DEMOGRAPHICS` | `true` | `false` includes age/sex/nationality in the scoring payload |
| `LLM_PROVIDER` | `gemini` | `gemini` · `anthropic` · `ollama` |
| `STORAGE_BACKEND` | `local` | `s3` for any S3-compatible endpoint |
| `CORS_ORIGINS` | localhost | Every origin the app is reached from |
| `ALLOW_SELF_REGISTRATION` | `false` | Account creation from the login page |

There is no upload size limit to configure. Authenticated uploads are unlimited; the public form has
a fixed anti-abuse ceiling in code. Storage is controlled by purging archived mandates.

---

## Known gaps

- **The barème does not match the firm's real one.** The default split in
  `backend/app/domain/bareme.py` was written before the real documents arrived. Their actual grid is
  Consistance du dossier 3 / Formation 7 / Expérience générale 5 / Expérience spécifique 15 = **30**,
  and those 30 points are **30 % of a total out of 100**, the interviews carrying the other 70 %.
  Selection is **top-N** ("les cinq (05) premiers candidats"), not a threshold, with a distinction
  between *préqualifiés* and *proposés*. "Consistance du dossier" is scored, not just a completeness
  check. This needs its own pass before a grid is shown to a client.
- The imposed CV/email format is not yet encoded (see the mailbox section above).
- PostgreSQL is configured but the local script runs on SQLite.
