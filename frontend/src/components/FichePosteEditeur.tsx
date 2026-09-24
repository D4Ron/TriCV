import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { recrutementApi } from '@/lib/api'
import { Callout, Field, Modal, Spinner, Toggle } from '@/components/ui'
import type { ExperienceSpecifique, Poste } from '@/types'
import { NIVEAUX } from '@/lib/niveaux'

/**
 * Modifier la fiche de poste après sa création.
 *
 * Jusqu'ici, tout ce qui décide d'une élimination ou d'une note se saisissait
 * une fois, à la création, dans une fenêtre qu'on ne rouvrait jamais. Les
 * domaines d'expérience, les seuils, les conditions restrictives : l'API les
 * acceptait, aucun écran ne les proposait. Une fiche mal remplie se corrigeait
 * en refaisant le poste — et en perdant ses dossiers.
 *
 * Trois choses méritent leur commentaire ici :
 *
 * - **Les conditions d'âge, de sexe et de nationalité** portent sur des
 *   caractéristiques protégées. L'écran les traite comme le moteur : rien
 *   n'est posé sans justification écrite, et le texte saisi est recopié sur
 *   chaque élimination qu'il provoque. Ce n'est pas une formalité, c'est ce
 *   qu'on aura à montrer si la condition est contestée.
 * - **Les expériences spécifiques sont une liste.** Un avis qui demande cinq
 *   ans de passation de marchés *et* trois ans de gestion de projet énonce
 *   deux exigences ; les réunir en une seule laissait passer qui n'avait fait
 *   que la première.
 * - **Enregistrer réévalue tout le poste.** Changer une exigence sans rejouer
 *   les grilles afficherait des motifs qui ne correspondent plus à la fiche,
 *   et c'est la grille que le client relit.
 */


const enListe = (valeur: string) =>
  valeur
    .split(',')
    .map((x) => x.trim())
    .filter(Boolean)

const enTexte = (valeurs: string[]) => valeurs.join(', ')

function LigneExperience({
  valeur,
  onChange,
  onRetirer,
}: {
  valeur: ExperienceSpecifique
  onChange: (v: ExperienceSpecifique) => void
  onRetirer: () => void
}) {
  return (
    <div className="rounded-lg border border-ink-200 p-3">
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-[10rem] flex-1">
          <label className="label">Intitulé</label>
          <input
            className="input"
            value={valeur.libelle}
            placeholder="passation des marchés"
            onChange={(e) => onChange({ ...valeur, libelle: e.target.value })}
          />
        </div>
        <div className="w-24">
          <label className="label">Années</label>
          <input
            type="number"
            min={0}
            max={60}
            className="input"
            value={valeur.annees_min}
            onChange={(e) => onChange({ ...valeur, annees_min: Number(e.target.value) })}
          />
        </div>
        <div className="w-24">
          <label className="label">Poids</label>
          <input
            type="number"
            min={1}
            max={10}
            className="input"
            value={valeur.poids}
            onChange={(e) => onChange({ ...valeur, poids: Number(e.target.value) || 1 })}
          />
        </div>
        <button type="button" className="btn-ghost px-2 py-1 text-xs" onClick={onRetirer}>
          Retirer
        </button>
      </div>
      <div className="mt-2">
        <Field
          label="Domaines reconnus"
          hint="Séparés par des virgules. Une expérience compte si l'un de ces domaines lui est rattaché."
        >
          <input
            className="input"
            value={enTexte(valeur.domaines)}
            placeholder="passation des marches, marches publics"
            onChange={(e) => onChange({ ...valeur, domaines: enListe(e.target.value) })}
          />
        </Field>
      </div>
    </div>
  )
}

export default function FichePosteEditeur({
  poste,
  onClose,
  onEnregistre,
}: {
  poste: Poste
  onClose: () => void
  onEnregistre: (compteRendu: string) => void
}) {
  const queryClient = useQueryClient()

  const [intitule, setIntitule] = useState(poste.intitule)
  const [niveau, setNiveau] = useState(poste.niveau_min)
  const [domainesAcceptes, setDomainesAcceptes] = useState(enTexte(poste.domaines_acceptes))
  const [experience, setExperience] = useState(poste.annees_experience_min)
  const [complementaire, setComplementaire] = useState(
    poste.formation_complementaire_souhaitee ?? '',
  )
  const [nombreARetenir, setNombreARetenir] = useState(poste.nombre_a_retenir ?? 0)

  // La liste part de ce qui est enregistré ; un poste à l'ancienne mode n'a
  // qu'une exigence, décrite par les deux champs scalaires.
  const [specifiques, setSpecifiques] = useState<ExperienceSpecifique[]>(
    poste.experiences_specifiques.length > 0
      ? poste.experiences_specifiques
      : [
          {
            libelle: '',
            domaines: poste.domaines_experience,
            annees_min: poste.annees_experience_specifique_min,
            poids: 1,
          },
        ],
  )

  // Ce que la formation rapporte au-delà du diplôme. Zéro par défaut : le
  // barème du cabinet note le diplôme, et rien d'autre.
  const extras = (poste.bareme?.formation ?? {}) as Record<string, number | undefined>
  const [pointsCertification, setPointsCertification] = useState(
    extras.points_par_certification ?? 0,
  )
  const [certificationsMax, setCertificationsMax] = useState(extras.certifications_max ?? 3)
  const [pointsComplementaire, setPointsComplementaire] = useState(
    extras.points_formation_complementaire ?? 0,
  )

  const [ageActif, setAgeActif] = useState(
    poste.restriction.age_min !== null || poste.restriction.age_max !== null,
  )
  const [ageMin, setAgeMin] = useState(poste.restriction.age_min ?? 0)
  const [ageMax, setAgeMax] = useState(poste.restriction.age_max ?? 0)
  const [justification, setJustification] = useState(poste.restriction.justification ?? '')

  const [erreur, setErreur] = useState<string | null>(null)

  const extrasChanges =
    pointsCertification !== (extras.points_par_certification ?? 0) ||
    certificationsMax !== (extras.certifications_max ?? 3) ||
    pointsComplementaire !== (extras.points_formation_complementaire ?? 0)

  const enregistrerFiche = () => {
    // Une seule exigence sans intitulé propre : on la range dans les champs
    // historiques plutôt que dans la liste. La fiche reste alors lisible par
    // tout ce qui n'a jamais entendu parler de la liste — l'avis publié, les
    // exports, les grilles déjà remises.
    const utiles = specifiques.filter((e) => e.libelle.trim() || e.domaines.length > 0)
    const simple = utiles.length <= 1
    const seule = utiles[0]

    return recrutementApi.modifierPoste(poste.id, {
      intitule: intitule.trim(),
      niveau_min: niveau,
      domaines_acceptes: enListe(domainesAcceptes),
      annees_experience_min: experience,
      annees_experience_specifique_min: simple ? (seule?.annees_min ?? 0) : 0,
      domaines_experience: simple ? (seule?.domaines ?? []) : [],
      experiences_specifiques: simple ? [] : utiles,
      formation_complementaire_souhaitee: complementaire.trim() || null,
      nombre_a_retenir: nombreARetenir > 0 ? nombreARetenir : null,
      restriction: {
        age_min: ageActif && ageMin > 0 ? ageMin : null,
        age_max: ageActif && ageMax > 0 ? ageMax : null,
        sexe: poste.restriction.sexe,
        nationalites: poste.restriction.nationalites,
        justification: justification.trim(),
      },
    })
  }

  const enregistrer = useMutation({
    // Le barème d'abord : il réévalue le poste, et la fiche le réévaluera
    // ensuite sur les exigences à jour. L'ordre inverse laisserait les notes
    // calculées sur les anciennes exigences.
    mutationFn: async () => {
      if (extrasChanges) {
        await recrutementApi.definirExtrasFormation(poste.id, {
          points_par_certification: pointsCertification,
          certifications_max: certificationsMax,
          points_formation_complementaire: pointsComplementaire,
        })
      }
      return enregistrerFiche()
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['poste', poste.id] })
      void queryClient.invalidateQueries({ queryKey: ['grille', poste.id] })
      void queryClient.invalidateQueries({ queryKey: ['candidatures', poste.id] })
      onEnregistre(
        'Fiche enregistrée. Les dossiers du poste ont été réévalués sur les nouvelles exigences.',
      )
      onClose()
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Enregistrement impossible'),
  })

  const specifiqueMax = Math.max(0, ...specifiques.map((e) => e.annees_min))
  const incoherent = specifiqueMax > experience
  // Le sexe et la nationalité se posent ailleurs mais partagent la même
  // justification : lever la condition d'âge ne doit pas laisser les deux
  // autres sans motif écrit.
  const autresRestrictions =
    poste.restriction.sexe !== null || poste.restriction.nationalites.length > 0
  const justificationManquante = (ageActif || autresRestrictions) && !justification.trim()

  return (
    <Modal open title="Fiche de poste" onClose={onClose}>
      <div className="space-y-5">
        <Field label="Intitulé du poste" htmlFor="fiche-intitule">
          <input
            id="fiche-intitule"
            className="input"
            value={intitule}
            onChange={(e) => setIntitule(e.target.value)}
          />
        </Field>

        <Field label="Niveau de diplôme exigé" htmlFor="fiche-niveau">
          <select
            id="fiche-niveau"
            className="input"
            value={niveau}
            onChange={(e) => setNiveau(Number(e.target.value))}
          >
            {NIVEAUX.map(({ valeur, libelle }) => (
              <option key={valeur} value={valeur}>
                {libelle}
              </option>
            ))}
          </select>
        </Field>

        <Field
          label="Domaines de formation acceptés"
          htmlFor="fiche-domaines"
          hint="Séparés par des virgules. Un diplôme hors de ces domaines est écarté comme non conforme. Laisser vide accepte tout diplôme du niveau exigé."
        >
          <input
            id="fiche-domaines"
            className="input"
            value={domainesAcceptes}
            onChange={(e) => setDomainesAcceptes(e.target.value)}
          />
        </Field>

        <Field
          label="Expérience générale exigée (années)"
          htmlFor="fiche-exp"
          hint="Toute expérience professionnelle, chevauchements déduits."
        >
          <input
            id="fiche-exp"
            type="number"
            min={0}
            max={60}
            className="input"
            value={experience}
            onChange={(e) => setExperience(Number(e.target.value))}
          />
        </Field>

        <div>
          <div className="flex flex-wrap items-baseline gap-2">
            <span className="label mb-0">Expériences spécifiques exigées</span>
            <button
              type="button"
              className="btn-ghost ml-auto px-2 py-1 text-xs"
              onClick={() =>
                setSpecifiques((liste) => [
                  ...liste,
                  { libelle: '', domaines: [], annees_min: 0, poids: 1 },
                ])
              }
            >
              Ajouter une exigence
            </button>
          </div>
          <p className="hint mb-2">
            Chacune est vérifiée séparément : un candidat doit satisfaire toutes celles qui
            portent un nombre d&apos;années. Les 15 points du critère se partagent au prorata
            des poids.
          </p>
          <div className="space-y-2">
            {specifiques.map((exigence, index) => (
              <LigneExperience
                key={index}
                valeur={exigence}
                onChange={(v) =>
                  setSpecifiques((liste) => liste.map((x, i) => (i === index ? v : x)))
                }
                onRetirer={() =>
                  setSpecifiques((liste) => liste.filter((_, i) => i !== index))
                }
              />
            ))}
          </div>
          {incoherent && (
            <div className="mt-2">
              <Callout tone="warning">
                Une expérience spécifique de {specifiqueMax} an(s) dépasse l&apos;expérience
                générale de {experience} an(s). Une expérience spécifique est aussi une
                expérience : le serveur refusera l&apos;enregistrement.
              </Callout>
            </div>
          )}
        </div>

        <Field
          label="Formation complémentaire souhaitée"
          htmlFor="fiche-complementaire"
          hint="Figure dans l'avis. Notée seulement si le barème du poste lui accorde des points ; jamais éliminatoire."
        >
          <input
            id="fiche-complementaire"
            className="input"
            value={complementaire}
            placeholder="certificat en passation des marchés publics"
            onChange={(e) => setComplementaire(e.target.value)}
          />
        </Field>

        <div className="rounded-lg border border-ink-200 p-3">
          <span className="label mb-0">Ce que la formation rapporte au-delà du diplôme</span>
          <p className="hint mb-3">
            Ces points se prennent <strong>dans les 7 de la formation académique</strong> : le
            barème reste à 30. À zéro — le réglage du cabinet — seul le niveau de diplôme est
            noté.
          </p>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Points par certification" htmlFor="fiche-pts-certif">
              <input
                id="fiche-pts-certif"
                type="number"
                min={0}
                max={7}
                step={0.5}
                className="input"
                value={pointsCertification}
                onChange={(e) => setPointsCertification(Number(e.target.value))}
              />
            </Field>
            <Field label="Certifications comptées au plus" htmlFor="fiche-certif-max">
              <input
                id="fiche-certif-max"
                type="number"
                min={1}
                max={10}
                className="input"
                value={certificationsMax}
                onChange={(e) => setCertificationsMax(Number(e.target.value) || 1)}
              />
            </Field>
            <Field
              label="Formation complémentaire"
              htmlFor="fiche-pts-compl"
              hint="Attribués si le dossier y répond."
            >
              <input
                id="fiche-pts-compl"
                type="number"
                min={0}
                max={7}
                step={0.5}
                className="input"
                value={pointsComplementaire}
                onChange={(e) => setPointsComplementaire(Number(e.target.value))}
              />
            </Field>
          </div>
        </div>

        <Field
          label="Nombre de candidats à proposer au client"
          htmlFor="fiche-nombre"
          hint="0 = aucun quota : tous les préqualifiés sont proposés."
        >
          <input
            id="fiche-nombre"
            type="number"
            min={0}
            className="input"
            value={nombreARetenir}
            onChange={(e) => setNombreARetenir(Number(e.target.value))}
          />
        </Field>

        <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-3">
          <Toggle
            checked={ageActif}
            onChange={(actif) => {
              setAgeActif(actif)
              if (!actif) {
                setAgeMin(0)
                setAgeMax(0)
              }
            }}
            label="Poser une condition d'âge"
            hint="L'âge s'apprécie à la date de clôture de l'avis, jamais à la date du calcul. Un candidat dont la date de naissance est inconnue n'est jamais écarté automatiquement."
          />
          {ageActif && (
            <div className="mt-3">
              <div className="grid grid-cols-2 gap-3">
                <Field label="Âge minimum" hint="0 = pas de minimum" htmlFor="fiche-age-min">
                  <input
                    id="fiche-age-min"
                    type="number"
                    min={0}
                    max={120}
                    className="input"
                    value={ageMin}
                    onChange={(e) => setAgeMin(Number(e.target.value))}
                  />
                </Field>
                <Field label="Âge maximum" hint="0 = pas de maximum" htmlFor="fiche-age-max">
                  <input
                    id="fiche-age-max"
                    type="number"
                    min={0}
                    max={120}
                    className="input"
                    value={ageMax}
                    onChange={(e) => setAgeMax(Number(e.target.value))}
                  />
                </Field>
              </div>
            </div>
          )}
          {/* La justification vaut aussi pour le sexe et la nationalité, qui se
              posent ailleurs : elle reste éditable tant qu'une condition
              quelconque est active, sinon la lever rendrait la fiche
              inenregistrable sans moyen de la corriger. */}
          {(ageActif || autresRestrictions) && (
            <div className="mt-3">
              <Field
                label="Justification de la condition"
                htmlFor="fiche-justification"
                hint="Obligatoire. Ce texte est recopié sur chaque élimination provoquée par la condition, et c'est lui qu'on produira si elle est contestée."
              >
                <textarea
                  id="fiche-justification"
                  className="input"
                  rows={2}
                  value={justification}
                  placeholder="Limite d'âge fixée par le statut du personnel du commanditaire."
                  onChange={(e) => setJustification(e.target.value)}
                />
              </Field>
            </div>
          )}
        </div>

        {erreur && <Callout tone="danger">{erreur}</Callout>}

        <div className="flex flex-wrap items-center gap-2">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Annuler
          </button>
          <button
            type="button"
            className="btn-primary"
            disabled={
              enregistrer.isPending || !intitule.trim() || incoherent || justificationManquante
            }
            onClick={() => enregistrer.mutate()}
          >
            {enregistrer.isPending && <Spinner />}
            Enregistrer et recalculer
          </button>
          {justificationManquante && (
            <span className="text-xs text-amber-700">
              {ageActif
                ? "Une condition d'âge doit être justifiée par écrit."
                : 'Ce poste porte une condition de sexe ou de nationalité : sa justification ne peut pas rester vide.'}
            </span>
          )}
        </div>
      </div>
    </Modal>
  )
}
