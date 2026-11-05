---
name: lire-dossiers
description: Read a TriCV lecture.json batch here in Claude Code and write the result.json to import. Use when the user asks to read exported dossiers, process lecture.json, or produce a result.json.
---

# Lire un lot de dossiers

The user exports `lecture.json` from a poste (**Plus › Exporter pour lecture externe**) and puts it in
`lectures/`, which git ignores. You read it and write `lectures/result.json`, which the user imports
with **Plus › Importer un result.json**.

Only do this when the user asks, for the file they name. The text is redacted but it is still a
candidate's career: it reaches Anthropic by being read here. Say so once if they have not said the
batch is fictional. Never copy dossier text into code, tests, commits or chat.

## Steps

1. Read the file. Check `format` is `tricv-lecture/1`. Follow its `consigne`: it is the same
   instruction every reader gets. Each dossier's `texte` holds its pieces, announced by type.
2. For each dossier, extract what is written, nothing else. A work certificate confirms a CV job
   rather than adding one; a job wished for in a letter was never held; `[NOM]`-style markers are
   never values.
3. Write this, copying `candidature_id` and `empreinte` exactly:

```json
{
  "format": "tricv-lecture/1",
  "lecteur": "claude-code",
  "dossiers": [
    {
      "candidature_id": "",
      "empreinte": "",
      "diplomes": [{"intitule": "", "niveau": 5, "domaine": "", "domaine_dossier": "", "etablissement": "", "annee": 2014}],
      "experiences": [{"poste": "", "employeur": "", "debut": "2015-01", "fin": null, "domaines": [""], "pays": ""}],
      "langues": [""],
      "certifications": [""],
      "remarques": ""
    }
  ]
}
```

4. `remarques` tells a recruiter what to look at: a gap, a date that disagrees between two pieces, a
   piece that seems unrelated. Never an opinion on the person. **No scores**: the platform computes
   them, and ignores any it finds.
5. Tell the user how many dossiers you read and where the file is. Report only counts.
