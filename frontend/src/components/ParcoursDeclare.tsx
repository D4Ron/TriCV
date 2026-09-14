import { NIVEAUX_DIPLOME, type ParcoursDeclare } from '@/lib/api'
import { Field } from '@/components/ui'

/**
 * Ce que le candidat dit de lui-même, en plus de joindre son CV.
 *
 * C'est volontairement redondant avec le CV. Tant que celui-ci n'a pas été
 * dépouillé puis relu par quelqu'un, rien de son contenu n'existe en base :
 * la note porte sur trois points au lieu de trente, et les conditions d'âge ou
 * de nationalité — pourtant éliminatoires — ne s'appliquent à personne. Le
 * candidat, lui, connaît ses diplômes. Le lui demander coûte quelques minutes
 * et rend son dossier notable le jour même.
 *
 * Rien n'est obligatoire ici. Un candidat pressé dépose son CV et s'en va ;
 * l'écran dit ce que la saisie lui apporte, il ne la lui impose pas.
 */

const VIDE_DIPLOME = { intitule: '', niveau: 3, domaine: '', etablissement: '', annee: '' }
const VIDE_EXPERIENCE = {
  poste: '',
  employeur: '',
  debut: '',
  fin: '',
  encours: false,
  domaines: '',
  pays: '',
}

export type SaisieDiplome = typeof VIDE_DIPLOME
export type SaisieExperience = typeof VIDE_EXPERIENCE

export interface SaisieParcours {
  diplomes: SaisieDiplome[]
  experiences: SaisieExperience[]
  langues: string
  certifications: string
  formations: string
}

export const PARCOURS_VIDE: SaisieParcours = {
  diplomes: [],
  experiences: [],
  langues: '',
  certifications: '',
  formations: '',
}

/** Un mois saisi (AAAA-MM) devient une date : le jour n'apporte rien ici. */
function versDate(mois: string): string | null {
  if (!mois.trim()) return null
  return /^\d{4}-\d{2}$/.test(mois) ? `${mois}-01` : mois
}

function liste(brut: string): string[] {
  return brut
    .split(',')
    .map((m) => m.trim())
    .filter(Boolean)
}

/** La saisie de l'écran, dans la forme que l'API attend. */
export function versParcours(saisie: SaisieParcours): ParcoursDeclare {
  return {
    diplomes: saisie.diplomes
      .filter((d) => d.intitule.trim() && d.domaine.trim())
      .map((d) => ({
        intitule: d.intitule.trim(),
        niveau: Number(d.niveau),
        domaine: d.domaine.trim(),
        etablissement: d.etablissement.trim() || undefined,
        annee: d.annee ? Number(d.annee) : null,
      })),
    experiences: saisie.experiences
      .filter((e) => e.poste.trim() && e.employeur.trim() && e.debut.trim())
      .map((e) => ({
        poste: e.poste.trim(),
        employeur: e.employeur.trim(),
        debut: versDate(e.debut)!,
        fin: e.encours ? null : versDate(e.fin),
        domaines: liste(e.domaines),
        pays: e.pays.trim() || undefined,
      })),
    langues: liste(saisie.langues),
    certifications: liste(saisie.certifications),
    formations_complementaires: liste(saisie.formations),
  }
}

/** Y a-t-il quelque chose à envoyer ? Un parcours vide ne part pas. */
export function parcoursRempli(saisie: SaisieParcours): boolean {
  const p = versParcours(saisie)
  return (
    p.diplomes.length > 0 ||
    p.experiences.length > 0 ||
    p.langues.length > 0 ||
    p.certifications.length > 0 ||
    p.formations_complementaires.length > 0
  )
}

function BoutonRetirer({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      className="btn-ghost px-2 py-1 text-xs text-ink-500"
      onClick={onClick}
    >
      Retirer
    </button>
  )
}

export default function SaisieParcoursDeclare({
  valeur,
  onChange,
  erreurs = {},
}: {
  valeur: SaisieParcours
  onChange: (suivant: SaisieParcours) => void
  erreurs?: Record<string, string>
}) {
  const majDiplome = (index: number, champ: keyof SaisieDiplome, v: string) =>
    onChange({
      ...valeur,
      diplomes: valeur.diplomes.map((d, i) => (i === index ? { ...d, [champ]: v } : d)),
    })

  const majExperience = (
    index: number,
    champ: keyof SaisieExperience,
    v: string | boolean,
  ) =>
    onChange({
      ...valeur,
      experiences: valeur.experiences.map((e, i) =>
        i === index ? { ...e, [champ]: v } : e,
      ),
    })

  return (
    <div className="space-y-5 border-t border-ink-100 pt-4">
      <div>
        <p className="text-sm font-medium text-ink-800">Votre parcours</p>
        <p className="mt-1 text-xs text-ink-500">
          Ces informations figurent sans doute déjà dans votre CV. Les saisir ici permet
          d&apos;examiner votre dossier sans attendre, et évite qu&apos;un élément passe
          inaperçu à la lecture. Rien n&apos;est obligatoire.
        </p>
      </div>

      {/* --- diplômes --- */}
      <div className="space-y-3">
        <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">
          Diplômes
        </p>
        {valeur.diplomes.map((diplome, index) => (
          <div key={index} className="rounded-lg border border-ink-200 p-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Intitulé" error={erreurs[`diplome-${index}`]}>
                <input
                  className="input"
                  value={diplome.intitule}
                  placeholder="Master en sciences comptables"
                  onChange={(e) => majDiplome(index, 'intitule', e.target.value)}
                />
              </Field>
              <Field label="Niveau">
                <select
                  className="input"
                  value={diplome.niveau}
                  aria-label={`Niveau du diplôme ${index + 1}`}
                  onChange={(e) => majDiplome(index, 'niveau', e.target.value)}
                >
                  {NIVEAUX_DIPLOME.map((n) => (
                    <option key={n.valeur} value={n.valeur}>
                      {n.libelle}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Domaine">
                <input
                  className="input"
                  value={diplome.domaine}
                  placeholder="comptabilité, gestion, droit…"
                  onChange={(e) => majDiplome(index, 'domaine', e.target.value)}
                />
              </Field>
              <Field label="Établissement">
                <input
                  className="input"
                  value={diplome.etablissement}
                  placeholder="Université de Lomé"
                  onChange={(e) => majDiplome(index, 'etablissement', e.target.value)}
                />
              </Field>
              <Field label="Année d'obtention">
                <input
                  className="input"
                  type="number"
                  inputMode="numeric"
                  min={1940}
                  max={new Date().getFullYear()}
                  value={diplome.annee}
                  onChange={(e) => majDiplome(index, 'annee', e.target.value)}
                />
              </Field>
            </div>
            <div className="mt-2 flex justify-end">
              <BoutonRetirer
                onClick={() =>
                  onChange({
                    ...valeur,
                    diplomes: valeur.diplomes.filter((_, i) => i !== index),
                  })
                }
              />
            </div>
          </div>
        ))}
        <button
          type="button"
          className="btn-ghost px-3 py-1.5 text-xs"
          onClick={() =>
            onChange({ ...valeur, diplomes: [...valeur.diplomes, { ...VIDE_DIPLOME }] })
          }
        >
          + Ajouter un diplôme
        </button>
      </div>

      {/* --- expériences --- */}
      <div className="space-y-3">
        <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">
          Expériences professionnelles
        </p>
        {valeur.experiences.map((experience, index) => (
          <div key={index} className="rounded-lg border border-ink-200 p-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Poste occupé" error={erreurs[`experience-${index}`]}>
                <input
                  className="input"
                  value={experience.poste}
                  placeholder="Chef comptable"
                  onChange={(e) => majExperience(index, 'poste', e.target.value)}
                />
              </Field>
              <Field label="Employeur">
                <input
                  className="input"
                  value={experience.employeur}
                  placeholder="Groupe Atlantique"
                  onChange={(e) => majExperience(index, 'employeur', e.target.value)}
                />
              </Field>
              <Field label="Début (mois et année)">
                <input
                  className="input"
                  type="month"
                  value={experience.debut}
                  aria-label={`Début de l'expérience ${index + 1}`}
                  onChange={(e) => majExperience(index, 'debut', e.target.value)}
                />
              </Field>
              <Field label="Fin">
                <input
                  className="input"
                  type="month"
                  value={experience.fin}
                  disabled={experience.encours}
                  aria-label={`Fin de l'expérience ${index + 1}`}
                  onChange={(e) => majExperience(index, 'fin', e.target.value)}
                />
                <label className="mt-1.5 flex items-center gap-2 text-xs text-ink-600">
                  <input
                    type="checkbox"
                    className="h-3.5 w-3.5 rounded border-ink-300"
                    checked={experience.encours}
                    onChange={(e) => majExperience(index, 'encours', e.target.checked)}
                  />
                  Poste occupé actuellement
                </label>
              </Field>
              <Field label="Domaines">
                <input
                  className="input"
                  value={experience.domaines}
                  placeholder="comptabilité générale, audit interne"
                  onChange={(e) => majExperience(index, 'domaines', e.target.value)}
                />
              </Field>
              <Field label="Pays">
                <input
                  className="input"
                  value={experience.pays}
                  placeholder="Togo"
                  onChange={(e) => majExperience(index, 'pays', e.target.value)}
                />
              </Field>
            </div>
            <div className="mt-2 flex justify-end">
              <BoutonRetirer
                onClick={() =>
                  onChange({
                    ...valeur,
                    experiences: valeur.experiences.filter((_, i) => i !== index),
                  })
                }
              />
            </div>
          </div>
        ))}
        <button
          type="button"
          className="btn-ghost px-3 py-1.5 text-xs"
          onClick={() =>
            onChange({
              ...valeur,
              experiences: [...valeur.experiences, { ...VIDE_EXPERIENCE }],
            })
          }
        >
          + Ajouter une expérience
        </button>
      </div>

      {/* --- listes libres --- */}
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Langues">
          <input
            className="input"
            value={valeur.langues}
            placeholder="français, anglais"
            onChange={(e) => onChange({ ...valeur, langues: e.target.value })}
          />
        </Field>
        <Field label="Certifications">
          <input
            className="input"
            value={valeur.certifications}
            placeholder="IFRS, PMP"
            onChange={(e) => onChange({ ...valeur, certifications: e.target.value })}
          />
        </Field>
        <Field label="Formations complémentaires">
          <input
            className="input"
            value={valeur.formations}
            placeholder="séminaires, cycles courts"
            onChange={(e) => onChange({ ...valeur, formations: e.target.value })}
          />
        </Field>
      </div>
      <p className="text-xs text-ink-500">Séparez les éléments par des virgules.</p>
    </div>
  )
}
