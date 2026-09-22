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

### Accounts and roles

Two roles. **RECRUITER** does all the recruitment work. **ADMIN** does that plus changing the
firm's settings — default threshold, demographic redaction, self-registration, the application
mailbox.

**An account created through self-registration is always RECRUITER, never ADMIN.** The signup page
is reachable over the network; anyone who finds it must not be able to grant themselves control of
the firm's settings. The consequence is that signing up and then finding Paramètres read-only is
the system working as intended, not a bug.

Promotion therefore happens from the machine the app runs on, which is the guarantee itself:

```powershell
cd backend
.\.venv\Scripts\python.exe comptes.py                            # list accounts and roles
.\.venv\Scripts\python.exe comptes.py promouvoir alice@kapi.tg   # make an ADMIN
.\.venv\Scripts\python.exe comptes.py retrograder bob@kapi.tg
.\.venv\Scripts\python.exe comptes.py desactiver bob@kapi.tg     # revoke access, keep the record
```

The tool refuses to remove the last active administrator: nobody could then change the settings,
and there is no way back from inside the app. Log out and back in after a promotion — the screen
reads the role from the session.

The seeded `SEED_ADMIN_EMAIL` account is an ADMIN, so there is always one to start from.

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
are recorded in the audit log. A manual score also decides whether the file clears the threshold —
a mark entered by hand that does not change the file's fate is not a mark, it is decoration.

*Dépouiller le dossier* can be **run again**. A second pass replaces what the first one proposed,
and only that: anything the candidate declared on the form, or that a reviewer typed or confirmed,
stops the run and says so. Without this, a file read badly once stayed that way — the only way out
was to delete it and upload it again.

**The email address is read out of the CV**, along with the phone number, by the same local regex
pass that removes them before anything is sent. They were being detected, masked, then discarded:
a file dropped in bulk stayed unreachable, and the *E-mail* column of the table delivered to the
client stayed empty. A blank field is filled even on a reviewed file — confirming a career says
nothing about the absence of an address — but a value a candidate declared or a reviewer typed is
never replaced. The address is **required** wherever a person types a candidate in; a bulk drop
still arrives with nothing and gets it from the CV.

Dates of birth are read in figures (`03/09/1984`, `22-11-1979`) **and in words** (`8 février 1975`,
`15 July 1988`) — the latter being how most CVs here write them. Until that was fixed the date was
detected, never converted, and left empty; since a missing value never eliminates anyone, **every
age condition on every poste was silently inert**.

### The candidate declares their own file

The public form asks for date of birth, nationality, degrees and experience — deliberately
redundant with the CV attached beside it. The CV has to be *read* before it yields anything, and
until it has been, three things are true of a freshly submitted file:

- **Eliminatory conditions do not apply.** Age is only judged when a date of birth is known, and
  nationality when one is recorded. A poste open to candidates of 45 at most eliminated nobody on
  arrival — the condition reached only the files someone had found time to process. Two candidates
  the same age could meet different fates depending on the queue.
- **The mark is wrong.** Formation, experience and specific experience are 27 of the 30 points. With
  no degree and no experience on record, a new file scored 3 — not because the candidate was weak,
  but because nobody had read them yet.
- **Everything hangs on the model.** An exhausted quota or an unreadable scan left the file empty.

What the candidate types is `DECLARE` — the same provenance as their name, and the one that counts
without review. The CV still governs and is still attached; assisted extraction now *corroborates*
rather than being the only road in. Declaring stays optional: a candidate in a hurry drops a CV and
leaves.

Because declared data is human data, running *Dépouiller le dossier* on such a file **does nothing
and says so** — the model does not overwrite what the candidate wrote, so there is no risk of the
same degree being counted twice. The message asks the reviewer to compare against the CV and add by
hand anything it carries in addition.

The eliminatory conditions are now **shown on the application page** before anyone submits. The form
asks for exactly the data they are judged on, and letting someone assemble a full file only to be
cut on a criterion they never saw would be careless.

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
produced by a single call, so the totals in two exported files cannot drift apart.

*Exporter* asks **which document** first, because they do not go to the same people:

| | |
|---|---|
| Grille de présélection | the scored ranking — what the client receives |
| Tableau d'élimination | the rejected files, grouped by reason, with expected/found — what you produce to a candidate who contests |
| Détail des entretiens | the jury's marks and observations — the material for the report |
| Synthèse | headcounts and the spread of reasons, on one page |
| Dossier complet | all four in one workbook, for internal work |

A single button used to produce the four-sheet workbook, which made sending the ranking to a client
also send them the elimination table and the jury's observations. Each sheet is built by the same
code either way, so a table exported on its own is word for word the one in the full workbook.

*Modifier la fiche* edits the requirements after creation — degree level, accepted fields, general
experience, the specific-experience requirements, the age condition and what training is worth
beyond the diploma. **Saving re-scores every application on the poste**: leaving the grid on the old
requirements would show reasons that no longer match the fiche, and it is the grid the client reads.

*Écrire aux candidats* picks a scope first — everyone who applied, the preselected, the recevables
below the threshold, the rejected, the ones still to verify. The list comes from the server, not
from what the grid happens to have loaded, so an acknowledgement does not skip applications that
arrived since the last refresh. Applications with no email address are counted and reported rather
than failing one by one.

**To write to one person**, open their file and use *Écrire* in the drawer header. Same window,
same preview, same send path — the common gesture is individual (chase a missing document, invite
to interview, answer a follow-up) and it previously existed only as a bulk send from the grid,
which meant going through a list to reach someone already on screen. The button says who it will
write to, and is disabled with an explanation when the file has no address.

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

### Reports

**The generated report has the structure of the report the firm actually delivers.** Not one
inspired by it — its own, taken from `Rapport des entretiens - WAPP 2025`: titles, order, heading
levels, table columns and closing note. `backend/tests/test_conformite_document.py` holds that
structure as literal expected values, so a drift fails a test instead of being noticed by a client.

```
(page de garde)     logo et marque du cabinet, objet du mandat en capitales,
                    titre, commanditaire, référence, mois — et au pied les
                    coordonnées du cabinet avec la mention « Confidentiel »
(sommaire)          paginé

Introduction
I.   Démarche
II.  Objectifs de la mission
III. Méthodologie
     3.1. Présélection                      → grille de présélection
     3.2. Critères éliminatoires et Condition de Présélection
IV.  Résultats de la présélection           → effectifs par poste
     4.1. Liste des candidats présélectionnés → candidatures préqualifiées
V.   Entretiens structurés
     5.1. Adoption du guide d'interview et la grille de notation → grille de notation
     5.2. Validation du jury de sélection et conduite des interviews
     5.3. Résultats des entretiens structurés → classement + NB d'annexe
```

**The front matter is part of the document, not decoration.** A file that opens on *Introduction*
is not the one the client expects. `backend/app/services/exports/frontispice.py` holds what the four
formats share — the firm's coordinates, the mark, the numbering rule, the summary entries — and each
format draws it with its own means: a real `TOC` field for Word, a `text:table-of-content` for
LibreOffice, a table of contents computed in two passes for the PDF, a plain list for text. Word and
LibreOffice repaginate their summary on open; the PDF's page numbers are computed here, which is why
it builds twice.

Three notes on the numbering. It is **Roman for sections, decimal beneath them**, and *Introduction*
carries none — the rule read off the delivered document. It is computed on the sections **actually
rendered**, so a section left empty does not consume a number and leave a hole where II should be.
And the **preview shows the numbered sections but not the cover or the summary**: there is nothing to
proofread on those two pages — their content comes from the mandate and from the titles, not from the
writing — and showing them only pushes the sentence you just typed further down the screen.

**The brand pieces are the firm's own, taken from the documents it delivers** — not redrawn.
`backend/app/services/exports/assets/` holds three files lifted out of `Rapport des entretiens -
WAPP 2025`:

| | |
|---|---|
| `entete_kapi.jpg` | the letterhead, full page. It *is* the first page of the firm's reports — mark, rules, coordinates and the *Confidentiel* mention are already on it, so the cover composes none of them and only lays the objet, title and month on top |
| `logo_kapi.png` | the logo with its wordmark, for where the letterhead does not reach |
| `bandeau_kapi.png` | the *Nous développons vos métiers* band that runs along the foot of every page |

The logo had first been redrawn — a 3×3 grid of gradient squares traced from the website, written
pixel by pixel with `zlib`. The real logo is a 4×4 checkerboard carrying the words *Kapi Consult*, so
the report was going out under a mark the firm does not use. Approximating an identity is pointless
when the original is sitting in the reference document.

Two consequences worth knowing. The letterhead is a 210 dpi raster with the address baked in: if the
firm moves, that file is what gets replaced, not a constant — and the RCCM line is clipped at the
bottom edge *in the source asset itself*, so the delivered document shows it clipped too. And the
band carries a partner's mark (Profiles International); if that partnership ends, the file needs
replacing. `frontispice.pieces_presentes()` guards a checkout without them: the exports fall back to
a cover composed in text rather than failing.

Three things follow from the section structure, and each was a deliberate correction:

- **A table has no heading of its own.** It follows the sentence that announces it, inside the
  section that announces it. Giving each one its own intertitle invented headings — *Effectifs par
  poste* — that appear nowhere in the firm's document.
- **In ODF, `style:paragraph-properties` comes *before* `style:text-properties`.** They were written
  the other way round, and the cost is invisible in a way that matters: a reader applying the schema
  keeps what belongs to the text and drops what belongs to the paragraph. The cover page came out
  left-aligned and crammed to the top of the sheet, in the right font and the right colours, with
  every style present and each one half-applied.
  `test_l_odt_range_ses_proprietes_dans_l_ordre_du_schema_odf` holds the order.
- **The ODT's summary has no page numbers, and that is as good as it gets.** Verified in LibreOffice
  itself (`soffice --headless --convert-to pdf`): the index renders its titles and hierarchy
  correctly and stops there. ODF has no equivalent of Word's `updateFields` — an index paginates
  only once the reader runs *Tools › Update › Indexes*, and converting to PDF does not run it
  either. Correct titles without numbers beat invented numbers: we cannot know how LibreOffice will
  paginate. The DOCX and the PDF both carry real page numbers, and the ODT stays the secondary
  format some administrations ask for.
- **The ODT declares Calibri and its own paragraph spacing.** It declared neither, so LibreOffice
  rendered it in Liberation Serif with paragraphs run together, while the DOCX was Calibri at 8pt
  spacing — three formats of one report that only resembled each other from a distance. Carlito,
  the metric-compatible Calibri clone LibreOffice ships, is named as the fallback so the layout
  holds where Calibri is absent.
- **The DOCX is schema-conformant, which is not the same as "Word refused it".** `w:pBdr` and
  `w:updateFields` were being appended to the end of their parent instead of at their place in the
  OOXML sequence. This was first reported here as the cause of an unopenable report; that was an
  inference from ECMA-376, and it does not hold — Word 16 opens the document in either order, with
  auto-repair disabled. `test_le_docx_respecte_la_sequence_du_schema_ooxml` keeps the ordering
  because conformance stands on its own, not because it fixes a crash.
- **A table sits inside the prose, not at the end of its section.** A sentence announces it, the
  table follows, and a comment on the figures comes after — *Trente-trois (33) candidatures
  préqualifiées pour le poste de DAF, dont cinq (5) proposés pour la prochaine étape*. The drafting
  marks the spot with a `[TABLEAU]` line and the section keeps two blocks of prose, `contenu` and
  `contenu_apres`. Rendering everything first put that comment above the figures it comments on,
  right after the sentence promising *les résultats suivants*. A forgotten marker costs nothing:
  everything stays before the table, which is the older behaviour.
- **There is no conclusion.** The document ends on the results table and *NB : Le détail des notes
  obtenues par chaque candidat est annexé au présent rapport*. A conclusion added by default had to
  be deleted by hand before every send.
- **The grids are reproduced as tables**, which is a deliberate departure: the firm's document
  describes the preselection rubrics in prose. They sit in the exact section that discusses them.

Columns, word for word as delivered:

| | |
|---|---|
| effectifs | Postes, Nombre de dossiers analysés, Effectif Préqualifié, Nombre de candidats éliminés, + TOTAL |
| grille de notation | numbered `I` / `1.1` / `1.2` when the grid has rubriques, each with its subtotal |
| candidatures préqualifiées | Nom & Prénoms, Age, Diplôme, Pays, **Présélection Note/100**, Rang, Téléphone, E-mail |
| résultats des entretiens | Nom & Prénoms, PAYS, Moyenne/100, Rang |

These are **real tables** in the DOCX, PDF and ODT — not columns aligned with spaces. Space
alignment holds only in a fixed-width font, and those exports render in Calibri and Helvetica,
where every column drifted a little further than the last. Plain text keeps the aligned form,
which is the one place it is the right tool.

Two details that are easy to get wrong. *Présélection Note/100* is the preselection mark expressed
as a percentage — a file at 27/30 reads **90** — not its weighted contribution to the total, which
is 27.
And the rank is counted **among the preselected**, so the table runs 1er, 2e, 3e without gaps;
ranking over all files received produced a preselected table numbered 1er, 2e, 4e, where the missing
ranks were candidates the table does not show.

The firm does not deliver one report but three, at three different moments, and they do not carry
the same sections. **The type is chosen first**, and it decides what is produced:

| | |
|---|---|
| *Rapport de présélection* | after the sift, before the interviews — stops at the ranking of files |
| *Rapport des entretiens* | after the panel — carries the final ranking |
| *Rapport final de recrutement* | the whole mission, from the published avis to the final ranking |

A client who imposes their own outline uploads it as a *modèle*, and that outline replaces the
sections entirely — which is what a template is for, so it takes precedence over the type.

Figures are frozen when the report is generated, so the document is re-exportable identically in six
months whatever happens to the files afterwards. Prose is *proposed*, then read: a report cannot be
validated until every section has been through human hands.

**Aperçu du document**, beside *Rédiger*, shows the report as it will be exported — same header,
same order, same rule that an empty section is not rendered — including corrections not yet saved.
Judging the whole document previously meant exporting a Word file, opening it, coming back to
correct, and exporting again.

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

**Measured, `qwen3:8b` on the extraction corpus (15 September 2026):** degrees 13/14, experience
17/18, against 14/14 · 18/18 for both `gemini-2.5-flash` and `ministral-14b-latest`. The two misses
are the same fault and neither is an invention — it takes the first date it sees rather than the
right one (*Depuis mars 2018* read as `2018-01`; *2006 - 2008 : Master … (BAC+5)* dated 2006). The
Master's **level** — the only part the barème scores — was correct. What it costs in practice is two
extra months of general experience and a wrong year on a degree, both of which HR confirms before
they count, since an unconfirmed `EXTRAIT_IA` forces `À VÉRIFIER`.

So the reading is fine. What rules it out as a daily driver is the clock: **52 s per dossier**
single-threaded, over two hours for a 150-dossier mandate. That is not a hardware problem — `ollama
ps` reports the model **100% on GPU** on a laptop RTX 4070. It is the model: `qwen3` *reasons*
before answering, emitting a `<think>` block the app then throws away (see `app/llm/prose.py`), and
that reasoning is paid for on every dossier.

Keep it for the two cases it is the only answer to — both quotas exhausted mid-mandate, or a client
who will not let dossiers leave their walls. If a local model is ever to do more than that, try one
that does not think out loud (`llama3.1:8b`, `mistral:7b`) and measure it with
`tools.evaluer_extraction` before adopting it: speed is worthless if the reading degrades.

Whatever the provider, it never sees a name, an e-mail, a phone number or a date of birth: those
are found and removed locally before the text is sent. What travels is a career history.

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
| `LLM_PROVIDER` | `gemini` | `gemini` · `anthropic` · `ollama` · `openai` (see below) |
| `LLM_BASE_URL` | — | With `openai`: the provider's endpoint — Groq, Mistral, OpenRouter, vLLM |
| `LLM_API_KEY` | — | With `openai`: that provider's key |
| `STORAGE_BACKEND` | `local` | `s3` for any S3-compatible endpoint |
| `CORS_ORIGINS` | localhost | Every origin the app is reached from |
| `ALLOW_SELF_REGISTRATION` | `false` | Account creation from the login page |

There is no upload size limit to configure. Authenticated uploads are unlimited; the public form has
a fixed anti-abuse ceiling in code. Storage is controlled by purging archived mandates.

### Choosing a provider

The figure that decides this is **not** requests per day. TriCV sends up to 24,000 characters of
CV per *dépouillement* — roughly 7,000 tokens — so a free tier with a generous request count and a
small daily **token** ceiling runs out long before its request count does. Report sections are the
opposite: a few hundred tokens each, six to ten per report.

| Provider | Free tier | *Dépouillements* per day, realistically | Notes |
|---|---|---|---|
| **Mistral** (`openai`) | 1 req/s, 500K tokens/min, ~1B tokens/month | Thousands | A French model house — the best French of the free options. Needs phone verification |
| Gemini 2.5 Flash-Lite | 15 RPM, 1,000 RPD | ~1,000 | No daily token ceiling. Weakest of the three at reasoning |
| Gemini 2.5 Flash *(current)* | 10 RPM, 250 RPD | ~250 | No daily token ceiling |
| Groq `llama-3.3-70b` | 30 RPM, 1,000 RPD, **100K tokens/day** | **~13** | Fastest by far, and useless here: 14 CVs exhausts the day |
| Ollama, local | none | Unlimited | Nothing leaves the building — and ~52 s per dossier with `qwen3:8b` fully on GPU, so over two hours for 150. A fallback, not a daily driver |

Groq tops every "best free LLM API" list and is the worst fit for this application, for that one
reason. It is a fine choice for the *report* half of the work, which is token-light.

**Every free tier trains on what you send, unless you stop it.** Google's does and cannot be
turned off — only a paid key stops it. Mistral's free *Experiment* plan does too **by default**,
but it can be refused in the console (Admin › Privacy) without paying. That difference is most of
why Mistral is the recommendation: it is the only free tier where a real dossier can be sent
without the firm's data feeding someone's training set. Redaction still removes every identity
field first, so what would travel is a career history — but a career history is still a client's
material.

#### Switching to Mistral

1. Create an account at <https://console.mistral.ai>, verify a phone number, and generate an API
   key. (Yours to do — TriCV never handles credentials.)
2. **In the console, Admin › Privacy: refuse the use of API data for training.** Do this before
   the first real dossier, not after.
3. In `.env`:

       LLM_PROVIDER=openai
       LLM_BASE_URL=https://api.mistral.ai/v1
       LLM_MODEL=ministral-14b-latest
       LLM_API_KEY=<the key>
       LLM_MAX_CONCURRENCY=1

   **Not `mistral-small-latest`.** On the free Experiment plan the `small`,
   `medium` and `magistral` models are allocated **zero** requests a minute and
   return an immediate 429 — the key is fine, the model is not available. Only
   the `ministral` family is allocated: `3b` (750/min), `8b` (188/min), `14b`
   (30/min). `ministral-14b-latest` measured equal to `gemini-2.5-flash` on the
   extraction corpus.

   `LLM_MAX_CONCURRENCY=1` is not a detail: the free plan allows one request a second, and three
   in flight means two refusals and a wait. One at a time is faster.
4. Restart, then run the pre-flight — it now checks both of the points above:

       python backend/preflight.py

5. Confirm the prose path returns prose — and invents nothing (one call):

       cd backend && .venv/Scripts/python.exe tools/verifier_prose.py

   It checks the form (not JSON, not Markdown, not empty) **and the substance**: any proper noun
   in the answer that is absent from the data is reported as a probable invention. That second
   check matters more than it sounds. A small model asked to write the publication section filled
   the gap with *"diffusion via JobTogo, LinkedIn, Indeed"* from data naming no channel at all —
   a sentence the firm would have signed, and a candidate could have contested.

6. **Measure the extraction before trusting it** (six calls):

       cd backend && .venv/Scripts/python.exe -m tools.evaluer_extraction mistral

   Compare against the recorded `gemini-2.5-flash` baseline — 14/14 diplomas, 18/18 experiences
   on the same corpus. A provider that costs less and reads worse is not a saving: extraction
   accuracy is what the whole preselection rests on. If it scores lower, stay on Gemini.

The same three variables point at Groq, OpenRouter, Together, or a vLLM server on the firm's own
machine; only `LLM_BASE_URL` and `LLM_MODEL` change. See [`.env.example`](.env.example).

#### Splitting the two jobs

`LLM_PROSE_PROVIDER=gemini` sends **report and avis text** to one provider while **dossier
extraction** stays with another. The two jobs are not alike:

| | extraction | prose |
|---|---|---|
| volume | one call per dossier — 150 on a big mandate | ~7 per report |
| what exhausts a quota | this | never this |
| where an error shows | on screen, at *Confirmer les données* | in a document already sent to the client |
| a wrong answer | a wrong score, visible when re-reading the parcours | a sentence the firm has signed |

So the generous-quota provider takes the volume, and the one that invents least writes the prose.
Measured on the seven written sections of one report: `ministral-14b-latest` invented in **1 of 7**
(it filled in grid rubrics that were missing from the data); `gemini-2.5-flash` in 0 of 7, though
it returned an entirely **empty** section once, which is its own failure mode. Neither is reliable
unread — which is why every section still arrives marked *proposée* and blocks validation until a
human has been through it.

##### What a model invents, and what stops it

Three inventions were observed in real reports, and each was fixed at its cause rather than by
asking the model to try harder:

| observed | cause | fix |
|---|---|---|
| *les candidats devaient être de nationalité togolaise* — on a post with no nationality condition | the consigne said to enumerate nationality, age and experience; the context never carried them | the context now states **every** condition, absent ones included: *AUCUNE condition de nationalité n'a été posée*. A stated fact gets copied; a silence gets filled |
| a ten-row table of `[Nom 1]`…`[Nom 10]` with invented interview scores, above the empty table the code had just produced | the section was asked to comment a ranking that did not exist yet | the prompt forbids writing tables at all (the code inserts them), and `prose.nettoyer` strips any Markdown table row that survives |
| *aucun n'atteignait les critères implicites de cohérence* | a surprising figure — ten eligible dossiers, none preselected — invites an explanation | the prompt forbids invoking any *implicit*, *expected* or *coherence* criterion, and says a surprising figure is reported without being justified |
| *les compétences techniques (25 points sur 50)* — the interview grid totals **70** | the grid was passed to the model rubric by rubric, with no total, so it added up — and got it wrong | the context now states each grid's total outright, and the prompt forbids computing anything: no sums, no averages, no percentages, and no denominator that is not written down |
| the qualification split and note range restated in *Objectifs de la mission*, a section about aims | each section is a separate call, so any two consignes that overlap produce the same figure twice | figures are owned by one section; the aims section is told in as many words that it says what the mission *sought*, never what it found |

The general rule behind all three: **a model fills a silence, so say the thing out loud**. The
system prompt used to end on *mieux vaut une section courte* — which kept the prose honest and also
kept it thin, at roughly the length of a set of meeting notes. It now asks the model to develop
what the data supports and to stop where the data stops: if a stage has not happened, it says so in
one sentence and writes nothing else. On the ten-CV bench that took a report from 884 to about 1 600
words while the two stages that never ran stayed at two sentences each.

The writer keeps the extraction chain behind it as fallback: losing the writer must not lose the
report.

#### Falling back to a second provider

`LLM_FALLBACK=gemini` makes the app try Gemini when the primary runs out of allowance. With two
free keys, that is the difference between a mandate stopping mid-way and finishing.

It switches **only on an exhausted quota** — and only after the usual four retries, so a
per-minute limit is waited out rather than escalated. A response that could not be read, or a
rejected key, is a fault to see and fix; contorting around it at another provider would hide a
misconfiguration for weeks.

A provider whose key is missing is dropped from the chain rather than being fatal. That is what
lets a switch be configured before its key exists: the chain falls through to whatever works, and
pasting the key promotes the new provider with no other change.

Two things to weigh before turning it on:

- **Two models do not read a CV the same way.** A mandate read half by one and half by the other
  produces a grid whose lines come from different readers — and a candidate contesting their
  elimination is entitled to know which read theirs. Every switch is logged at `WARNING`, naming
  both providers, so the question is at least answerable.
- **Free tiers do not share a privacy policy.** Mistral's can be set to refuse training; Google's
  free tier cannot. Falling back from the first to the second moves real career histories from a
  provider that forgets them to one that keeps them. The pre-flight says so explicitly. It is a
  decision to take once, knowingly — not a surprise on a Tuesday evening.

Each provider then needs its own model (`GEMINI_MODEL`, `OPENAI_MODEL`, …): `LLM_MODEL` names the
primary's, and `mistral-small-latest` means nothing to Google.

#### Running the model locally (Ollama)

This is the only configuration where a real candidate's CV never leaves the building. No key, no
quota, no third party, no training policy to read — the text goes to a process on the firm's own
machine. For a recruitment consultancy holding other people's dossiers, that is a different
category of answer from "a free tier that promises not to look".

The cost is hardware and speed.

**What it needs.** A 7–8B model quantised to 4 bits is about 5 GB on disk and wants roughly that
much VRAM to run at a useful pace. It runs without a graphics card — on CPU, on many cores — but
a dossier then takes minutes instead of seconds, which is fine for an overnight batch and
unpleasant while someone waits at the screen.

**Setup, in Docker:**

```bash
docker compose --profile local-llm up -d ollama
docker compose exec ollama ollama pull qwen3:8b
```

Then in `.env`:

```bash
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen3:8b
OLLAMA_BASE_URL=http://ollama:11434   # http://localhost:11434 outside Compose
```

To use an NVIDIA card, uncomment the `deploy:` block on the `ollama` service in
[`docker-compose.yml`](docker-compose.yml) — it needs the NVIDIA Container Toolkit (Docker Desktop
with WSL2 provides it on Windows). Leaving it enabled without a card stops the service from
starting, which is why it ships commented.

For local development outside Compose, installing Ollama natively is simpler and picks up the GPU
with no configuration: <https://ollama.com/download>, then `ollama pull qwen3:8b`.

**Measure it before trusting it**, exactly as for any other provider:

```bash
cd backend && .venv/Scripts/python.exe -m tools.evaluer_extraction ollama
```

Against the recorded baseline — 14/14 diplomas, 18/18 experiences for both `gemini-2.5-flash` and
`ministral-14b-latest`. A local model that reads worse is not privacy, it is a worse grid; if it
scores lower, try a larger one before accepting it. Nothing about "local" makes a wrong extraction
less wrong.

`PII_REDACTION` stays on regardless. Redaction is not only about the provider — it is what keeps
identity out of the scoring payload, so a name or an age cannot influence a score.

---

## The barème

The split is the firm's own, taken from their documents:

| Critère | Points |
|---|---|
| Consistance du dossier | 3 |
| Formation académique | 7 |
| Expérience générale | 5 |
| Expérience spécifique | **15** |
| **Présélection** | **30** |

Domains — of a degree, of an experience — are matched by **stem, not by string equality**. An avis
asking for `comptabilité` is satisfied by a degree in `sciences comptables` or `comptabilité et
finance`; one asking for `finance` is satisfied by `finance d'entreprise`. The match is directional
and stays strict on substance: every significant word of the *expected* domain must be found in the
declared one, so `droit` never meets `comptabilité`, and an avis demanding `finance d'entreprise` is
not satisfied by `finance` alone. What it absorbs is spelling; what it refuses is a different trade.
String equality — what it replaced — produced non-conformity reasons a human reader would have
thrown out, on files that were perfectly in order.

An avis often states more than one specific experience — "five years in procurement **and** three
in project management". Each is declared separately, checked separately, and the 15 points are
split between them in proportion to their weights; the criterion's total does not move. Merged into
a single set of fields, as they used to be, the two requirements became one: eight years of
procurement satisfied both, and someone who had never run a project cleared the bar.

Certifications and the *formation complémentaire* named by the avis are worth **zero by default** —
the firm's barème scores the diploma and nothing else. A client who wants them counted enables them
per poste, and the points come **out of the 7 already allocated to formation**, so the total stays
at 30. The match against the requested complementary training is a word comparison: the score line
always names what it matched, because a word comparison is something a reader must be able to
reject.

Those 30 points are **30 % of a total out of 100**. The structured interviews carry the other 70 —
techniques 30, relationnelles/managériales 20, leadership 12, langues 3, présentation 3,
connaissances générales 2. The grid shows both: a mark out of 30 read on its own gets mistaken for
a final result.

### Interviews

Recorded from the candidate drawer: the six criteria, a comment per criterion, the date, the jury's
composition and general observations. **Nothing here is computed or suggested** — these 70 points
are a judgement made in session, and the automated assistance has no part in them and no access to
them.

The whole grid is shown from the start, unscored criteria included, so a jury can see what is left
to do; a criterion with no mark is `null`, never zero. A mark outside its range is **refused**
rather than silently clamped — clamping would show the jury a mark it did not give. Until every
criterion is scored, the /100 is labelled **partiel**, on screen and in the exported file: a running
total mid-session is not a result. The grid used is frozen on the sheet, so changing how the 70
points are split later cannot rewrite an evaluation already delivered.

A file carrying an active elimination cannot be scored. Lift the reason first — interviewing someone
who was ruled out is a decision, and it leaves a trace.

The Excel export grows an **Entretiens** sheet once the stage has happened: per candidate, in
ranking order, every criterion with its mark and what the jury observed, the total, and the general
observations. That is the material for writing the recruitment report — which the app deliberately
does not write. The sheet is omitted entirely when no interview has been recorded, rather than
appearing empty.

Two consequences worth knowing:

- **Specific experience is half the total.** Fifteen points for having done *this* job against five
  for seniority in general. The scoring curves are deliberately gentle so the criterion keeps
  separating candidates across the whole plausible range instead of saturating just past the
  requirement — with a steep curve, fifteen and twenty-five years score identically and the fifteen
  points stop ranking anything.
- **Consistance du dossier is scored, not a completeness gate.** Completeness and chronological
  coherence are computed; the third point — motivation and written expression — is reserved for a
  human, entered from the candidate drawer with a written reason. Until someone reads the file the
  line says so and the point stays unclaimed: an unread file is not a bad file.

Selection is by **ranking**, matching the firm's process ("les cinq (05) premiers candidats ayant
obtenu les meilleures notes"). The threshold defaults to zero — no floor. Set `nombre_a_retenir` on
a poste and the grid marks the top N as **proposés**; the rest stay **préqualifiés** and remain on
the grid, because those are the ones you call back if a proposed candidate withdraws.

`note_de_conformite()` gives the score of a candidate who exactly meets every requirement — a floor
that can be defended, unlike a round number picked in advance.

Everything above the category maxima is configurable per poste, and a copy of the barème used is
stored with each score, so editing a poste never rewrites a grid already delivered.

---

## Known gaps

- **The internal curve of each criterion is a setting, not a document.** The four maxima
  (3/7/5/15) and the 30/70 split come from the firm's papers. How many points at exactly the
  required level, and how many per extra year, are defaults chosen to spread the field. Worth
  confirming against a grid they have filled in by hand.
- The imposed CV/email format is not yet encoded (see the mailbox section above).
- PostgreSQL is configured but the local script runs on SQLite.
- **The free tier caps how many dossiers a day can be read.** On the configured
  `gemini-2.5-flash` that is 250 requests a day across the whole installation — a *dépouillement*
  costs one, a report section costs one. A mandate with 150 applications fits, but two such
  mandates in a morning do not. See *Choosing a provider* above: Mistral's free tier is the better
  fit for French and for volume, and `LLM_PROVIDER=ollama` removes the ceiling entirely.
- Extraction accuracy is measured against a small hand-written corpus
  (`backend/tools/evaluer_extraction.py`), not against real files — which is deliberate, since a
  real application has no place in a repository, but it does mean the corpus only covers the layouts
  someone thought to write down. When a real CV is read badly, the fix is to add the equivalent
  invented CV to the corpus and measure.
- The match between the *formation complémentaire* an avis asks for and what a file contains is a
  word comparison, not an understanding of either. It proposes; the score line names what it matched
  so a reader can refuse it.
