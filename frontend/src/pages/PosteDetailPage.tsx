import { useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fichesApi, rapportsApi, recrutementApi } from '@/lib/api'
import {
  Callout,
  CopyField,
  EmptyState,
  ErrorState,
  Field,
  Modal,
  PageLoader,
  Spinner,
  delaiListe,
} from '@/components/ui'
import CandidatureDrawer from '@/components/CandidatureDrawer'
import DepotEnLot from '@/components/DepotEnLot'
import { LIBELLE_PIECE } from '@/lib/pieces'
import EnvoyerAuxCandidats from '@/components/EnvoyerAuxCandidats'
import ChoisirDestinataires from '@/components/ChoisirDestinataires'
import ChoisirExportGrille from '@/components/ChoisirExportGrille'
import FichePosteEditeur from '@/components/FichePosteEditeur'
import GrilleEntretienEditeur from '@/components/GrilleEntretienEditeur'
import type { Avis, LigneGrille, Poste, PropositionFiche } from '@/types'
import { NIVEAUX, libelleNiveau } from '@/lib/niveaux'

type Onglet = 'preselection' | 'sous_seuil' | 'elimination' | 'a_verifier'


const LIBELLE_TYPE_AVIS: Record<string, string> = {
  NATIONAL: 'Avis national',
  INTERNATIONAL: 'Avis international',
  GRE_A_GRE: 'Gré à gré',
}

const LIBELLE_STATUT_AVIS: Record<string, string> = {
  BROUILLON: 'Brouillon',
  PUBLIE: 'Publié',
  CLOTURE: 'Clôturé',
}

function Statistique({
  valeur,
  libelle,
  ton,
  actif,
  onClick,
}: {
  valeur: number
  libelle: string
  ton: string
  actif?: boolean
  onClick?: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!onClick}
      className={`card px-4 py-3 text-left transition-[background-color,border-color,box-shadow]
        duration-180 ease-out-soft ${
        onClick ? 'hover:border-ink-300' : ''
      } ${actif ? 'border-ink-900' : ''}`}
    >
      <p className={`text-2xl font-semibold tabular-nums ${ton}`}>{valeur}</p>
      <p className="mt-0.5 text-xs text-ink-500">{libelle}</p>
    </button>
  )
}

/** Le rappel des exigences : c'est la fiche de poste, pas l'avis publié. */
function FichePoste({ poste }: { poste: Poste }) {
  const lignes: Array<[string, string]> = [
    ['Diplôme exigé', libelleNiveau(poste.niveau_min)],
    [
      'Domaines acceptés',
      poste.domaines_acceptes.length ? poste.domaines_acceptes.join(', ') : 'tous',
    ],
    ['Expérience générale', `${poste.annees_experience_min} an(s)`],
    // Plusieurs exigences spécifiques ne tiennent pas dans la ligne unique :
    // affichée telle quelle, elle annonçait « 0 an(s) » alors que le poste en
    // exigeait deux fois plusieurs années.
    poste.experiences_specifiques.length > 0
      ? ([
          'Dont expériences spécifiques',
          poste.experiences_specifiques
            .map(
              (e) =>
                `${e.annees_min} an(s) en ${
                  e.libelle || e.domaines.join(', ') || 'le domaine du poste'
                }`,
            )
            .join(' ; '),
        ] as [string, string])
      : ([
          'Dont expérience spécifique',
          `${poste.annees_experience_specifique_min} an(s)${
            poste.domaines_experience.length
              ? ` en ${poste.domaines_experience.join(', ')}`
              : ''
          }`,
        ] as [string, string]),
    [
      'Pièces exigées',
      poste.pieces_requises.map((c) => LIBELLE_PIECE[c] ?? c).join(', ') || 'aucune',
    ],
    [
      'Pièces facultatives',
      poste.pieces_facultatives.map((c) => LIBELLE_PIECE[c] ?? c).join(', ') || 'aucune',
    ],
    ['Postes à pourvoir', String(poste.nombre_a_pourvoir)],
  ]

  // Le lieu et le rattachement ne notent personne : ils décrivent le poste, et
  // ils paraissent dans l'avis. Ils viennent de la fiche du client, alors ils
  // s'affichent là où on relit la fiche — pas ailleurs.
  if (poste.localisation) lignes.splice(1, 0, ['Lieu d’affectation', poste.localisation])
  if (poste.rattachement) lignes.splice(1, 0, ['Rattachement', poste.rattachement])

  if (poste.formation_complementaire_souhaitee) {
    lignes.splice(2, 0, [
      'Formation complémentaire souhaitée',
      poste.formation_complementaire_souhaitee,
    ])
  }
  for (const groupe of poste.groupes_pieces ?? []) {
    lignes.push([
      groupe.libelle || 'Pièces liées',
      groupe.codes
        .map((c) => LIBELLE_PIECE[c] ?? c)
        .join(groupe.mode === 'AU_MOINS_UNE' ? ' ou ' : ' et '),
    ])
  }
  const formats = Object.entries(poste.formats_pieces ?? {}).filter(([, f]) => f.length)
  lignes.push([
    'Formats acceptés',
    formats.length
      ? formats
          .map(([code, f]) => `${LIBELLE_PIECE[code] ?? code} : ${f.join('/').toUpperCase()}`)
          .join(' · ')
      : 'PDF ou Word',
  ])
  if (poste.pieces_libres_autorisees) {
    lignes.push(['Documents libres', 'le candidat peut en joindre'])
  }

  return (
    <section className="card p-4">
      <h2 className="mb-3 text-sm font-semibold text-ink-900">Fiche de poste</h2>
      <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
        {lignes.map(([cle, valeur]) => (
          <div key={cle} className="min-w-0">
            <dt className="text-xs text-ink-500">{cle}</dt>
            <dd className="truncate text-sm text-ink-800" title={valeur}>
              {valeur}
            </dd>
          </div>
        ))}
      </dl>
      <Liste titre="Responsabilités" valeurs={poste.responsabilites} />
      <Liste titre="Compétences techniques" valeurs={poste.competences_techniques} />
      <Liste
        titre="Compétences comportementales"
        valeurs={poste.competences_comportementales}
      />
    </section>
  )
}

/**
 * Une liste de la fiche, repliée si elle est longue.
 *
 * Une fiche de poste énumère volontiers douze responsabilités ; déroulées, elles
 * repoussent la grille des candidats sous la ligne de flottaison. Les trois
 * premières suffisent à reconnaître le poste, le reste se déplie.
 */
function Liste({ titre, valeurs }: { titre: string; valeurs: string[] }) {
  const [tout, setTout] = useState(false)
  if (!valeurs.length) return null
  const visibles = tout ? valeurs : valeurs.slice(0, 3)
  const reste = valeurs.length - 3
  return (
    <div className="mt-3 border-t border-ink-100 pt-3">
      <p className="text-xs text-ink-500">{titre}</p>
      <ul className="mt-1 list-disc space-y-0.5 pl-4 text-sm text-ink-800">
        {visibles.map((v, i) => (
          <li key={`${v}-${i}`}>{v}</li>
        ))}
      </ul>
      {valeurs.length > 3 && (
        <button
          type="button"
          className="mt-1 text-xs font-medium text-ink-500 underline"
          onClick={() => setTout(!tout)}
        >
          {tout ? 'Replier' : reste === 1 ? 'Voir la dernière' : `Voir les ${reste} autres`}
        </button>
      )}
    </div>
  )
}

/**
 * Le document que le client a transmis.
 *
 * La fiche de poste est une pièce du dossier, pas une saisie : c'est elle qu'on
 * ressort quand un candidat conteste une exigence, et c'est sur son texte que
 * l'avis se rédige. Elle restait pourtant invisible une fois déposée — on
 * pouvait la joindre et ne plus jamais savoir laquelle était jointe.
 *
 * Joindre une fiche à un poste déjà ouvert pose une question de plus :
 * faut-il en reprendre les exigences ? Le document seul ne change rien à la
 * notation — et c'est parfois exactement ce qu'on veut, quand la fiche arrive
 * après que les exigences ont été négociées. La case le demande, et la
 * relecture se fait dans le formulaire, pas à l'insu de qui la coche.
 */
function DocumentFiche({
  poste,
  onProposition,
  onCompteRendu,
  onErreur,
}: {
  poste: Poste
  onProposition: (proposition: PropositionFiche | null) => void
  onCompteRendu: (message: string) => void
  onErreur: (message: string) => void
}) {
  const queryClient = useQueryClient()
  const [collage, setCollage] = useState(false)
  const [texte, setTexte] = useState('')
  const [reprendre, setReprendre] = useState(!poste.fiche_a_texte)
  const fichierRef = useRef<HTMLInputElement>(null)

  const rafraichir = () => {
    void queryClient.invalidateQueries({ queryKey: ['poste', poste.id] })
  }

  const joindre = useMutation({
    mutationFn: (source: { fichier?: File; texte?: string }) =>
      fichesApi.joindre(poste.id, source, { proposer: reprendre }),
    onSuccess: (r) => {
      rafraichir()
      setCollage(false)
      setTexte('')
      if (r.proposition) onProposition(r.proposition)
      else onCompteRendu('Fiche jointe au poste.')
    },
    onError: (e) => onErreur(e instanceof Error ? e.message : "La fiche n'a pas pu être jointe"),
  })

  const retirer = useMutation({
    mutationFn: () => fichesApi.retirer(poste.id),
    onSuccess: () => {
      rafraichir()
      onCompteRendu('Fiche retirée. Les exigences du poste, elles, restent en place.')
    },
    onError: (e) => onErreur(e instanceof Error ? e.message : 'Le retrait a échoué'),
  })

  const ouvrir = useMutation({
    mutationFn: () => fichesApi.telecharger(poste.id, poste.fiche_nom_fichier),
    onError: (e) => onErreur(e instanceof Error ? e.message : "L'ouverture a échoué"),
  })

  const occupe = joindre.isPending || retirer.isPending || ouvrir.isPending
  const jointe = Boolean(poste.fiche_nom_fichier) || poste.fiche_a_texte

  return (
    <section className="card p-4">
      <h2 className="mb-3 text-sm font-semibold text-ink-900">Document de la fiche</h2>

      {!jointe && (
        <p className="text-sm text-ink-600">
          Aucune fiche n’est jointe. L’avis se rédige alors sur les seules exigences saisies,
          sans le texte du client.
        </p>
      )}

      {jointe && (
        <div className="text-sm text-ink-800">
          <p className="font-medium">
            {poste.fiche_nom_fichier ?? 'Texte collé, sans document'}
          </p>
          <p className="mt-0.5 text-xs text-ink-500">
            {poste.fiche_deposee_le
              ? `Déposée le ${new Date(poste.fiche_deposee_le).toLocaleDateString('fr-FR')}`
              : 'Date de dépôt inconnue'}
            {poste.fiche_a_texte
              ? ' · texte relevé, la rédaction d’un avis peut s’y appuyer'
              : ' · texte non relevé : l’avis ne pourra pas s’y appuyer'}
          </p>
        </div>
      )}

      {collage ? (
        <div className="mt-3 space-y-2">
          <textarea
            className="input font-mono text-xs"
            rows={8}
            value={texte}
            onChange={(e) => setTexte(e.target.value)}
            placeholder="Collez ici le texte de la fiche de poste…"
          />
          <Reprise valeur={reprendre} onChange={setReprendre} />
          <div className="flex gap-2">
            <button
              type="button"
              className="btn-primary px-3 py-1.5 text-xs"
              disabled={occupe || texte.trim().length < 40}
              onClick={() => joindre.mutate({ texte: texte.trim() })}
            >
              {joindre.isPending && <Spinner />}
              Joindre ce texte
            </button>
            <button
              type="button"
              className="btn-ghost px-3 py-1.5 text-xs"
              onClick={() => setCollage(false)}
            >
              Annuler
            </button>
          </div>
        </div>
      ) : (
        <>
          <div className="mt-3 flex flex-wrap gap-2">
            {poste.fiche_nom_fichier && (
              <button
                type="button"
                className="btn-ghost px-3 py-1.5 text-xs"
                disabled={occupe}
                onClick={() => ouvrir.mutate()}
              >
                {ouvrir.isPending && <Spinner />}
                Ouvrir le document
              </button>
            )}
            <button
              type="button"
              className="btn-ghost px-3 py-1.5 text-xs"
              disabled={occupe}
              onClick={() => fichierRef.current?.click()}
            >
              {jointe ? 'Remplacer par un document' : 'Joindre un document'}
            </button>
            <button
              type="button"
              className="btn-ghost px-3 py-1.5 text-xs"
              disabled={occupe}
              onClick={() => setCollage(true)}
            >
              {jointe ? 'Remplacer par du texte' : 'Coller le texte'}
            </button>
            {jointe && (
              <button
                type="button"
                className="btn-ghost px-3 py-1.5 text-xs text-red-700"
                disabled={occupe}
                onClick={() => retirer.mutate()}
              >
                {retirer.isPending && <Spinner />}
                Retirer
              </button>
            )}
          </div>
          <div className="mt-2">
            <Reprise valeur={reprendre} onChange={setReprendre} />
          </div>
        </>
      )}

      <input
        ref={fichierRef}
        type="file"
        accept=".pdf,.docx"
        className="hidden"
        onChange={(e) => {
          const fichier = e.target.files?.[0]
          if (fichier) joindre.mutate({ fichier })
          e.target.value = ''
        }}
      />
    </section>
  )
}

function Reprise({ valeur, onChange }: { valeur: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-start gap-2 text-xs text-ink-600">
      <input
        type="checkbox"
        className="mt-0.5"
        checked={valeur}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>
        Relire les exigences d’après ce document — le formulaire s’ouvrira prérempli. Décoché,
        le document est simplement conservé et les exigences actuelles ne bougent pas.
      </span>
    </label>
  )
}

/**
 * Les avis du poste, et leur rédaction.
 *
 * Le niveau de diplôme minimum et la formation complémentaire souhaitée se
 * saisissent ici, au moment où l'on rédige l'avis : c'est là qu'on y pense, et
 * c'est là que le cabinet les a demandés. Ils s'écrivent bien sur la fiche de
 * poste — ce sont des exigences, pas du texte — mais l'écran ne doit pas
 * obliger à faire un détour pour les poser.
 *
 * La rédaction du texte est facultative, et de deux sortes : à partir de la
 * fiche seule, ou en suivant un modèle imposé par le client. Dans les deux
 * cas ce n'est qu'un brouillon : un avis publié est opposable, et une condition
 * inventée devient une condition réelle.
 */
function PanneauAvis({ posteId, poste }: { posteId: string; poste: Poste }) {
  const queryClient = useQueryClient()
  // `null` = fermé, `''` = création, un identifiant = reprise de ce brouillon.
  // Un seul état plutôt que deux booléens : le formulaire est le même, seule
  // la destination change.
  const [ouvert, setOuvert] = useState<string | null>(null)
  const [reference, setReference] = useState('')
  const [type, setType] = useState('NATIONAL')
  const [cloture, setCloture] = useState('')
  const [niveau, setNiveau] = useState(poste.niveau_min)
  const [complementaire, setComplementaire] = useState(
    poste.formation_complementaire_souhaitee ?? '',
  )
  const [erreur, setErreur] = useState<string | null>(null)

  // Rédaction assistée : le texte proposé, l'avis qu'il concerne, le modèle.
  const [redaction, setRedaction] = useState<{
    avisId: string
    texte: string
    propose: boolean
    avertissement: string | null
  } | null>(null)
  const [modeleId, setModeleId] = useState('')

  const avis = useQuery({ queryKey: ['avis', posteId], queryFn: () => recrutementApi.avis(posteId) })
  const modeles = useQuery({
    queryKey: ['modeles-documents', 'avis', poste.mandat_id],
    queryFn: () => rapportsApi.modeles({ mandat_id: poste.mandat_id, usage: 'AVIS' }),
  })

  const rafraichir = () => {
    void queryClient.invalidateQueries({ queryKey: ['avis', posteId] })
    void queryClient.invalidateQueries({ queryKey: ['grille', posteId] })
  }

  /** Ouvre le formulaire sur un avis existant, ou vide pour en créer un. */
  const reprendre = (a: Avis | null) => {
    setErreur(null)
    setReference(a?.reference ?? '')
    setType(a?.type_avis ?? 'NATIONAL')
    setCloture(a?.date_cloture ?? '')
    setNiveau(poste.niveau_min)
    setComplementaire(poste.formation_complementaire_souhaitee ?? '')
    setOuvert(a?.id ?? '')
  }

  const supprimer = useMutation({
    mutationFn: (id: string) => recrutementApi.supprimerAvis(id),
    onSuccess: rafraichir,
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Suppression impossible'),
  })

  const creer = useMutation({
    mutationFn: async () => {
      // Les exigences saisies dans ce formulaire appartiennent à la fiche de
      // poste : c'est elle qui fait foi pour la présélection. On les y écrit
      // avant de créer l'avis, pour que le texte publié et la règle appliquée
      // ne puissent pas diverger.
      if (
        niveau !== poste.niveau_min ||
        complementaire.trim() !== (poste.formation_complementaire_souhaitee ?? '')
      ) {
        await recrutementApi.modifierPoste(posteId, {
          niveau_min: niveau,
          formation_complementaire_souhaitee: complementaire.trim() || null,
        })
      }
      const donnees = {
        reference: reference.trim() || null,
        type_avis: type,
        date_cloture: cloture || null,
      }
      // Reprise d'un brouillon, ou création : la même saisie sert aux deux.
      return ouvert
        ? recrutementApi.modifierAvis(ouvert, donnees)
        : recrutementApi.creerAvis(posteId, donnees)
    },
    onSuccess: () => {
      setOuvert(null)
      setReference('')
      setCloture('')
      void queryClient.invalidateQueries({ queryKey: ['poste', posteId] })
      rafraichir()
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Création impossible'),
  })

  const rediger = useMutation({
    mutationFn: (params: { avisId: string; avecAssistance: boolean }) =>
      recrutementApi.redigerAvis(posteId, {
        avis_id: params.avisId,
        modele_id: modeleId || null,
        avec_assistance: params.avecAssistance,
      }),
    onSuccess: (r, params) => {
      setErreur(null)
      setRedaction({
        avisId: params.avisId,
        texte: r.texte,
        propose: r.propose,
        avertissement: r.avertissement,
      })
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Rédaction impossible'),
  })

  const enregistrerTexte = useMutation({
    mutationFn: () =>
      recrutementApi.modifierAvis(redaction!.avisId, { texte: redaction!.texte }),
    onSuccess: () => {
      setRedaction(null)
      rafraichir()
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Enregistrement impossible'),
  })

  const publier = useMutation({
    mutationFn: (id: string) => recrutementApi.publierAvis(id),
    onSuccess: rafraichir,
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Publication impossible'),
  })

  const cloturer = useMutation({
    mutationFn: (id: string) => recrutementApi.cloturerAvis(id),
    onSuccess: rafraichir,
  })

  return (
    <section className="card p-4">
      <div className="mb-3 flex items-center gap-2">
        <h2 className="text-sm font-semibold text-ink-900">Avis de recrutement</h2>
        <button
          type="button"
          className="btn-ghost ml-auto px-2 py-1 text-xs"
          onClick={() => reprendre(null)}
        >
          Nouvel avis
        </button>
      </div>

      <p className="mb-3 text-xs text-ink-500">
        L'avis est tiré de la fiche de poste : il reprend le profil recherché et décrit le
        processus que suivront les candidats.
      </p>

      {erreur && (
        <p className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {erreur}
        </p>
      )}

      {avis.data?.length === 0 && (
        <div className="rounded-lg border border-dashed border-ink-300 px-3 py-3">
          <p className="text-sm font-medium text-ink-800">Étape suivante : créer l'avis</p>
          <p className="mt-1 text-xs text-ink-500">
            Sans avis publié, le poste n'a pas de lien de candidature et sa date de clôture — qui
            sert de référence au calcul de l'âge et de l'ancienneté — n'est pas fixée.
          </p>
        </div>
      )}

      <div className="space-y-2">
        {avis.data?.map((a: Avis) => (
          <div key={a.id} className="rounded-lg border border-ink-200 px-3 py-2.5">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium text-ink-900">
                {a.reference || 'sans référence'}
              </span>
              <span className="badge bg-ink-100 text-ink-700">
                {LIBELLE_TYPE_AVIS[a.type_avis]}
              </span>
              <span
                className={`badge ${
                  a.statut === 'PUBLIE'
                    ? 'bg-emerald-100 text-emerald-800'
                    : a.statut === 'CLOTURE'
                      ? 'bg-ink-100 text-ink-500'
                      : 'bg-amber-100 text-amber-800'
                }`}
              >
                {LIBELLE_STATUT_AVIS[a.statut]}
              </span>
              <span
                className={`ml-auto text-xs ${
                  a.date_cloture ? 'text-ink-500' : 'text-amber-700'
                }`}
              >
                {a.date_cloture
                  ? `clôture le ${a.date_cloture}`
                  : 'sans date de clôture — à fixer pour publier'}
              </span>
            </div>

            <div className="mt-2 flex flex-wrap items-center gap-2">
              {a.statut === 'BROUILLON' && (
                <>
                  <button
                    type="button"
                    className="btn-ghost px-2 py-1 text-xs"
                    disabled={publier.isPending || !a.date_cloture}
                    title={
                      a.date_cloture
                        ? undefined
                        : 'Fixez la date de clôture : elle sert de référence au calcul.'
                    }
                    onClick={() => publier.mutate(a.id)}
                  >
                    Publier
                  </button>
                  <button
                    type="button"
                    className="btn-ghost px-2 py-1 text-xs"
                    onClick={() => reprendre(a)}
                  >
                    Modifier
                  </button>
                  <button
                    type="button"
                    className="btn-ghost px-2 py-1 text-xs text-red-700 hover:bg-red-50"
                    disabled={supprimer.isPending}
                    onClick={() => supprimer.mutate(a.id)}
                  >
                    Supprimer
                  </button>
                </>
              )}
              {a.statut !== 'CLOTURE' && (
                <button
                  type="button"
                  className="btn-ghost px-2 py-1 text-xs"
                  disabled={rediger.isPending}
                  onClick={() => rediger.mutate({ avisId: a.id, avecAssistance: true })}
                >
                  {rediger.isPending && <Spinner />}
                  {a.texte ? 'Reprendre le texte' : 'Rédiger le texte'}
                </button>
              )}
              {a.statut === 'PUBLIE' && (
                <>
                  <button
                    type="button"
                    className="btn-ghost px-2 py-1 text-xs"
                    onClick={() => cloturer.mutate(a.id)}
                  >
                    Clôturer
                  </button>
                  <div className="w-full">
                    <CopyField
                      label="Lien de candidature"
                      value={`${window.location.origin}/apply/${a.cle_publique}`}
                    />
                  </div>
                </>
              )}
              {a.reference && (
                <p className="w-full text-xs text-ink-500">
                  Les candidatures reçues par email sont rattachées à cet avis si l'objet
                  contient <code className="rounded bg-ink-100 px-1">[{a.reference}]</code>.
                </p>
              )}
            </div>
          </div>
        ))}
      </div>

      {redaction && (
        <Modal open title="Texte de l'avis" onClose={() => setRedaction(null)}>
          <div className="space-y-4">
            {redaction.avertissement && <Callout tone="warning">{redaction.avertissement}</Callout>}
            {redaction.propose && (
              <Callout tone="info">
                Ce texte a été proposé à partir de la fiche de poste. Relisez-le : une fois
                publié, un avis est opposable, et une condition qui s'y trouve devient une
                condition réelle.
              </Callout>
            )}

            {(modeles.data?.length ?? 0) > 0 && (
              <Field
                label="Modèle imposé par le client"
                htmlFor="avis-modele"
                hint="Facultatif. Le texte suit alors sa présentation, mais les exigences restent celles de la fiche."
              >
                <div className="flex gap-2">
                  <select
                    id="avis-modele"
                    className="input"
                    value={modeleId}
                    onChange={(e) => setModeleId(e.target.value)}
                  >
                    <option value="">Présentation du cabinet</option>
                    {modeles.data!.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.libelle}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="btn-ghost shrink-0 px-3 text-xs"
                    disabled={rediger.isPending}
                    onClick={() =>
                      rediger.mutate({ avisId: redaction.avisId, avecAssistance: true })
                    }
                  >
                    Reproposer
                  </button>
                </div>
              </Field>
            )}

            <textarea
              className="input min-h-[24rem] font-mono text-xs"
              value={redaction.texte}
              aria-label="Texte de l'avis"
              onChange={(e) => setRedaction((r) => (r ? { ...r, texte: e.target.value } : r))}
            />

            <div className="flex flex-wrap justify-end gap-2">
              <button
                type="button"
                className="btn-ghost text-xs"
                disabled={rediger.isPending}
                onClick={() =>
                  rediger.mutate({ avisId: redaction.avisId, avecAssistance: false })
                }
              >
                Repartir des seuls éléments de la fiche
              </button>
              <button type="button" className="btn-ghost" onClick={() => setRedaction(null)}>
                Annuler
              </button>
              <button
                type="button"
                className="btn-primary"
                disabled={enregistrerTexte.isPending}
                onClick={() => enregistrerTexte.mutate()}
              >
                {enregistrerTexte.isPending && <Spinner />}
                Enregistrer le texte
              </button>
            </div>
          </div>
        </Modal>
      )}

      {ouvert !== null && (
        <Modal
          open
          title={ouvert ? "Reprendre le brouillon d'avis" : 'Nouvel avis de recrutement'}
          onClose={() => setOuvert(null)}
        >
          <div className="space-y-4">
            <Field
              label="Référence"
              htmlFor="avis-ref"
              hint="Sert à rattacher les candidatures reçues par email, via l'objet du message."
            >
              <input
                id="avis-ref"
                className="input"
                value={reference}
                onChange={(e) => setReference(e.target.value)}
                placeholder="AVIS-2026-014"
              />
            </Field>

            <Field label="Type d'avis" htmlFor="avis-type">
              <select
                id="avis-type"
                className="input"
                value={type}
                onChange={(e) => setType(e.target.value)}
              >
                {Object.entries(LIBELLE_TYPE_AVIS).map(([valeur, libelle]) => (
                  <option key={valeur} value={valeur}>
                    {libelle}
                  </option>
                ))}
              </select>
            </Field>

            <Field
              label="Date de clôture"
              htmlFor="avis-cloture"
              hint="Obligatoire pour publier : l'âge et l'ancienneté se calculent à cette date."
            >
              <input
                id="avis-cloture"
                type="date"
                className="input"
                value={cloture}
                onChange={(e) => setCloture(e.target.value)}
              />
            </Field>

            <Field
              label="Niveau de diplôme minimum exigé"
              htmlFor="avis-niveau"
              hint="Écrit sur la fiche de poste : c'est cette valeur qui écarte un dossier, pas le texte de l'avis."
            >
              <select
                id="avis-niveau"
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
              label="Formation complémentaire souhaitée"
              htmlFor="avis-complementaire"
              hint="Souhaitée, non exigée : elle figure dans l'avis et se compare à la lecture. Aucune règle de présélection ne la note."
            >
              <input
                id="avis-complementaire"
                className="input"
                value={complementaire}
                placeholder="Certification en gestion de projet, formation en passation de marchés…"
                onChange={(e) => setComplementaire(e.target.value)}
              />
            </Field>

            <div className="flex justify-end gap-2">
              <button type="button" className="btn-ghost" onClick={() => setOuvert(null)}>
                Annuler
              </button>
              <button
                type="button"
                className="btn-primary"
                disabled={creer.isPending}
                onClick={() => creer.mutate()}
              >
                {creer.isPending && <Spinner />}
                {ouvert ? 'Enregistrer' : "Créer l'avis"}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </section>
  )
}

/**
 * Le tableau de la grille.
 *
 * Le rang ouvre la ligne : le processus retient « les N premiers candidats
 * ayant obtenu les meilleures notes », donc c'est la première chose qu'on
 * cherche. La note est affichée sur 30 *et* sur 100, parce qu'une note sur 30
 * lue seule se prend pour un résultat final alors que la présélection ne pèse
 * que 30 % — les entretiens portent le reste.
 */
function TableauGrille({
  lignes,
  onOuvrir,
  colonneMotifs = false,
  colonneRang = false,
}: {
  lignes: LigneGrille[]
  onOuvrir: (id: string) => void
  colonneMotifs?: boolean
  colonneRang?: boolean
}) {
  if (lignes.length === 0) return <EmptyState title="Aucun dossier dans cette catégorie" />
  return (
    <div className="card overflow-x-auto">
      <table className="w-full min-w-[52rem] text-sm">
        <thead>
          <tr className="border-b border-ink-200 text-left text-xs uppercase tracking-wide text-ink-500">
            {colonneRang && <th className="px-3 py-2 font-medium">Rang</th>}
            <th className="px-3 py-2 font-medium">Nom</th>
            <th className="px-3 py-2 font-medium">Prénom</th>
            <th className="px-3 py-2 font-medium">Âge</th>
            <th className="px-3 py-2 font-medium">Nationalité</th>
            <th className="px-3 py-2 font-medium">Dernier diplôme</th>
            <th className="px-3 py-2 font-medium">École / Université</th>
            <th className="px-3 py-2 font-medium">Structure / Employeur</th>
            <th className="px-3 py-2 text-right font-medium">
              {colonneMotifs ? 'Motifs' : 'Note'}
            </th>
            {colonneRang && <th className="px-3 py-2 text-right font-medium">Finale /100</th>}
          </tr>
        </thead>
        <tbody>
          {lignes.map((ligne, index) => (
            <tr
              key={ligne.candidature_id}
              className="row-interactive stagger animate-fade-in border-b border-ink-100 last:border-0"
              style={delaiListe(index, 16)}
              onClick={() => onOuvrir(ligne.candidature_id)}
            >
              {colonneRang && (
                <td className="px-3 py-2 tabular-nums text-ink-500">
                  {ligne.rang ?? '—'}
                  {ligne.propose && ligne.rang !== null && (
                    <span
                      className="ml-1.5 rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-medium text-emerald-800"
                      title="Fait partie des candidats proposés au client"
                    >
                      proposé
                    </span>
                  )}
                </td>
              )}
              <td className="px-3 py-2 font-medium text-ink-900">
                {ligne.nom}
                {ligne.appreciation_attendue && !ligne.elimine && (
                  <span
                    className="ml-1.5 rounded bg-sky-100 px-1.5 py-0.5 text-[10px] font-medium text-sky-800"
                    title="La motivation et l'expression écrite n'ont pas encore été appréciées : des points de consistance restent à prendre"
                  >
                    à lire
                  </span>
                )}
                {ligne.doublons > 0 && (
                  <span
                    className="ml-1.5 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-800"
                    title={`${ligne.doublons} autre(s) dossier(s) reçu(s) de la même adresse email — souvent un envoi corrigé, à comparer avant de trancher`}
                  >
                    renvoi
                  </span>
                )}
              </td>
              <td className="px-3 py-2 text-ink-700">{ligne.prenom}</td>
              <td className="px-3 py-2 tabular-nums text-ink-700">{ligne.age ?? '—'}</td>
              <td className="px-3 py-2 text-ink-700">{ligne.nationalite ?? '—'}</td>
              <td className="px-3 py-2 text-ink-700">{ligne.dernier_diplome ?? '—'}</td>
              <td className="px-3 py-2 text-ink-700">{ligne.ecole_universite ?? '—'}</td>
              <td className="px-3 py-2 text-ink-700">{ligne.structure_employeur ?? '—'}</td>
              <td className="px-3 py-2 text-right">
                {colonneMotifs ? (
                  <span className="text-xs text-red-700">{ligne.motifs.length}</span>
                ) : (
                  <span className="font-semibold tabular-nums text-ink-900">
                    {ligne.note ?? '—'}
                    <span className="text-ink-400">/{ligne.total_max ?? ''}</span>
                    {ligne.note_sur_cent !== null && (
                      <span
                        className="ml-1.5 text-xs font-normal text-ink-500"
                        title="Contribution à la note finale sur 100 ; les entretiens portent les 70 % restants"
                      >
                        ({ligne.note_sur_cent}/100)
                      </span>
                    )}
                  </span>
                )}
              </td>
              {colonneRang && (
                <td className="px-3 py-2 text-right">
                  {ligne.note_finale_sur_cent === null ? (
                    <span className="text-xs text-ink-400" title="Pas encore reçu en entretien">
                      —
                    </span>
                  ) : (
                    <span className="font-semibold tabular-nums text-ink-900">
                      {ligne.note_finale_sur_cent}
                      <span className="text-ink-400">/100</span>
                      {!ligne.entretien_complet && (
                        <span
                          className="ml-1 text-[10px] font-normal text-amber-700"
                          title="Tous les critères d'entretien ne sont pas notés"
                        >
                          partiel
                        </span>
                      )}
                    </span>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/**
 * Poser la barre de présélection.
 *
 * Le geste réel est celui-ci : on regarde comment les notes se répartissent, et
 * on trace la barre là où elle sépare quelque chose. Un seuil choisi d'avance,
 * avant d'avoir vu les dossiers, revenait à décider à l'aveugle — c'est pour
 * cela qu'il a quitté les paramètres du cabinet.
 *
 * La répartition est donc affichée ici, à côté du champ. Une barre tracée juste
 * au-dessus d'un peloton de douze candidats n'est pas la même décision qu'une
 * barre tracée dans un vide, et l'écran doit le montrer.
 */
function ReglerSeuil({
  posteId,
  seuilActuel,
  seuilNominal,
  totalMax,
  distribution,
  onClose,
}: {
  posteId: string
  seuilActuel: number
  seuilNominal: number
  totalMax: number
  distribution: Array<{ de: number; a: number; candidats: number }>
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [seuil, setSeuil] = useState(seuilActuel)
  const [justification, setJustification] = useState('')
  const [erreur, setErreur] = useState<string | null>(null)
  // Le premier seuil posé devient la référence : c'est lui qui engage, et
  // c'est l'abaisser ensuite qui demande une justification écrite.
  const premiere = seuilNominal <= 0
  const abaisse = !premiere && seuil < seuilNominal
  const maximum = Math.max(...distribution.map((d) => d.candidats), 1)
  const retenus = distribution
    .filter((tranche) => tranche.a > seuil)
    .reduce((somme, tranche) => somme + tranche.candidats, 0)

  const enregistrer = useMutation({
    mutationFn: () => recrutementApi.changerSeuil(posteId, seuil, justification),
    onSuccess: async () => {
      await recrutementApi.evaluerPoste(posteId)
      void queryClient.invalidateQueries({ queryKey: ['grille', posteId] })
      void queryClient.invalidateQueries({ queryKey: ['poste', posteId] })
      onClose()
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Enregistrement impossible'),
  })

  return (
    <Modal open title="Seuil de présélection" onClose={onClose}>
      <div className="space-y-4">
        {distribution.length > 0 && (
          <div>
            <p className="text-sm font-medium text-ink-800">Répartition des notes obtenues</p>
            <p className="mt-0.5 text-xs text-ink-500">
              Environ {retenus} dossier{retenus > 1 ? 's' : ''} au-dessus de la barre actuelle.
            </p>
            <div className="mt-2 space-y-1">
              {[...distribution].reverse().map((tranche) => {
                const auDessus = tranche.a > seuil
                return (
                  <button
                    key={`${tranche.de}-${tranche.a}`}
                    type="button"
                    className="flex w-full items-center gap-2 text-left"
                    title={`Poser la barre à ${tranche.de}`}
                    onClick={() => setSeuil(tranche.de)}
                  >
                    <span className="w-20 shrink-0 text-right text-xs tabular-nums text-ink-500">
                      {tranche.de}–{tranche.a}
                    </span>
                    <span className="h-4 flex-1 rounded bg-ink-100">
                      <span
                        className={`block h-4 rounded ${
                          auDessus ? 'bg-brand-600' : 'bg-ink-300'
                        }`}
                        style={{ width: `${(tranche.candidats / maximum) * 100}%` }}
                      />
                    </span>
                    <span className="w-6 shrink-0 text-xs tabular-nums text-ink-600">
                      {tranche.candidats}
                    </span>
                  </button>
                )
              })}
            </div>
          </div>
        )}

        <Field
          label={premiere ? `Seuil (sur ${totalMax})` : `Seuil (référence : ${seuilNominal})`}
          htmlFor="seuil"
          hint={
            premiere
              ? "Aucune barre n'a encore été posée. Celle que vous tracez ici devient la référence : l'abaisser ensuite demandera une justification écrite."
              : undefined
          }
        >
          <input
            id="seuil"
            type="number"
            step={0.5}
            min={0}
            max={totalMax}
            className="input"
            value={seuil}
            onChange={(e) => setSeuil(Number(e.target.value))}
          />
        </Field>

        {abaisse && (
          <Field
            label="Justification"
            htmlFor="justification"
            hint="Obligatoire, et reprise dans le fichier remis au client."
          >
            <textarea
              id="justification"
              className="input min-h-[5rem]"
              value={justification}
              onChange={(e) => setJustification(e.target.value)}
              placeholder="Poste en tension, trois candidatures reçues."
            />
          </Field>
        )}

        {erreur && (
          <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {erreur}
          </p>
        )}

        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Annuler
          </button>
          <button
            type="button"
            className="btn-primary"
            disabled={(abaisse && !justification.trim()) || enregistrer.isPending}
            onClick={() => enregistrer.mutate()}
          >
            {enregistrer.isPending && <Spinner />}
            Enregistrer
          </button>
        </div>
      </div>
    </Modal>
  )
}

export default function PosteDetailPage() {
  const { posteId = '' } = useParams()
  const queryClient = useQueryClient()
  // Null tant que la grille n'est pas chargée : l'onglet ouvert est alors
  // celui qui contient effectivement des dossiers, plutôt qu'une liste vide.
  const [ongletChoisi, setOnglet] = useState<Onglet | null>(null)
  const [selection, setSelection] = useState<string | null>(null)
  const [seuilOuvert, setSeuilOuvert] = useState(false)
  const [grilleOuverte, setGrilleOuverte] = useState(false)
  // Les dossiers à qui écrire. Vide = aucune fenêtre d'envoi ouverte.
  const [destinataires, setDestinataires] = useState<string[]>([])
  // Fenêtre de choix de la portée, ouverte avant la rédaction.
  const [choixPortee, setChoixPortee] = useState(false)
  // Quel document tableur exporter : le choix se fait avant, pas après.
  const [choixExport, setChoixExport] = useState(false)
  const [ficheOuverte, setFicheOuverte] = useState(false)
  // Ce qu'une fiche jointe propose. Non nul = le formulaire s'ouvre dessus ;
  // rien n'est enregistré tant que personne n'a relu.
  const [proposition, setProposition] = useState<PropositionFiche | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  // Ce qu'une action menée dans une fenêtre laisse derrière elle : un dossier
  // supprimé, une fiche modifiée. La fenêtre se referme et les compteurs de la
  // grille changent ; sans cette ligne, rien ne dirait pourquoi.
  const [compteRendu, setCompteRendu] = useState<string | null>(null)

  const poste = useQuery({ queryKey: ['poste', posteId], queryFn: () => recrutementApi.poste(posteId) })
  const grille = useQuery({ queryKey: ['grille', posteId], queryFn: () => recrutementApi.grille(posteId) })
  const aVerifier = useQuery({
    queryKey: ['candidatures', posteId, 'A_VERIFIER'],
    queryFn: () => recrutementApi.candidatures(posteId, { statut: 'A_VERIFIER', page_size: 200 }),
  })

  const reevaluer = useMutation({
    mutationFn: () => recrutementApi.evaluerPoste(posteId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['grille', posteId] })
      void queryClient.invalidateQueries({ queryKey: ['candidatures', posteId] })
    },
  })

  /**
   * Les CV des candidats proposés, sous une présentation unique.
   *
   * La demande réelle du client : recevoir vingt dossiers sous la même forme.
   * Un dossier dont le parcours n'a pas été relu est écarté de l'archive — sur
   * un lot, une mention se perdrait — et le compte rendu le dit.
   */
  const [compteRenduCv, setCompteRenduCv] = useState<string | null>(null)
  const exporterCv = useMutation({
    mutationFn: (anonyme: boolean) =>
      rapportsApi.cvsMaison(posteId, {
        format: 'docx',
        portee: 'proposes',
        avecCoordonnees: !anonyme,
      }),
    onSuccess: (r) => {
      setErreur(null)
      setCompteRenduCv(
        r.ecartes
          ? `${r.inclus} CV exporté(s) · ${r.ecartes} écarté(s), parcours non relu — la liste est dans l'archive.`
          : `${r.inclus} CV exporté(s).`,
      )
    },
    onError: (e) => {
      setCompteRenduCv(null)
      setErreur(e instanceof Error ? e.message : "L'export a échoué")
    },
  })

  if (poste.isLoading || grille.isLoading) return <PageLoader />
  if (grille.isError) return <ErrorState error={grille.error} onRetry={() => grille.refetch()} />

  const g = grille.data!
  const p = poste.data!

  const onglet =
    ongletChoisi ??
    (g.nombre_preselectionnes > 0
      ? 'preselection'
      : g.nombre_a_verifier > 0
        ? 'a_verifier'
        : g.nombre_elimines > 0
          ? 'elimination'
          : 'preselection')

  const onglets: Array<[Onglet, string, number]> = [
    ['preselection', 'Préqualifiés', g.nombre_preselectionnes],
    ['sous_seuil', 'Sous le seuil', g.non_retenus.length],
    ['elimination', 'Éliminés', g.nombre_elimines],
    ['a_verifier', 'À vérifier', g.nombre_a_verifier],
  ]

  return (
    <div>
      <nav className="flex flex-wrap items-center gap-1 text-xs text-ink-500">
        <Link to="/mandats" className="hover:underline">
          Mandats
        </Link>
        <span>›</span>
        <Link to={`/mandats/${p.mandat_id}`} className="hover:underline">
          {g.mandat_intitule ?? 'Mandat'}
        </Link>
        <span>›</span>
        <span className="text-ink-700">{p.intitule}</span>
      </nav>

      <div className="mb-5 mt-2 flex flex-wrap items-start gap-3">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight text-ink-900">{p.intitule}</h1>
          <p className="mt-1 text-sm text-ink-500">
            {g.client_nom}
            {g.date_reference ? ` · clôture le ${g.date_reference}` : ''}
          </p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <button type="button" className="btn-ghost" onClick={() => setSeuilOuvert(true)}>
            {g.seuil > 0 ? `Seuil : ${g.seuil}/${g.total_max}` : 'Poser un seuil'}
          </button>
          <button type="button" className="btn-ghost" onClick={() => setFicheOuverte(true)}>
            Modifier la fiche
          </button>
          <button type="button" className="btn-ghost" onClick={() => setGrilleOuverte(true)}>
            Grille d&apos;entretien
          </button>
          <button
            type="button"
            className="btn-ghost"
            disabled={g.nombre_candidatures === 0}
            onClick={() => setChoixPortee(true)}
          >
            Écrire aux candidats
          </button>
          <button
            type="button"
            className="btn-ghost"
            disabled={reevaluer.isPending}
            onClick={() => reevaluer.mutate()}
          >
            {reevaluer.isPending && <Spinner />}
            Recalculer
          </button>
          <button
            type="button"
            className="btn-ghost"
            disabled={exporterCv.isPending || g.nombre_preselectionnes === 0}
            title="Les CV des candidats proposés, remis en forme à l'en-tête du cabinet."
            onClick={() => exporterCv.mutate(false)}
          >
            {exporterCv.isPending && <Spinner />}
            CV à en-tête (Word)
          </button>
          <button
            type="button"
            className="btn-primary"
            disabled={g.nombre_candidatures === 0}
            onClick={() => setChoixExport(true)}
          >
            Exporter (Excel)
          </button>
        </div>
      </div>

      {erreur && (
        <div className="mb-5">
          <Callout tone="danger">{erreur}</Callout>
        </div>
      )}

      {compteRenduCv && (
        <div className="mb-5">
          <Callout tone={compteRenduCv.includes('écarté') ? 'warning' : 'success'}>
            {compteRenduCv}
          </Callout>
        </div>
      )}

      {compteRendu && (
        <div className="mb-5">
          <Callout tone="info">
            {compteRendu}{' '}
            <button
              type="button"
              className="font-medium underline"
              onClick={() => setCompteRendu(null)}
            >
              Masquer
            </button>
          </Callout>
        </div>
      )}

      {p.a_completer && (
        <div className="mb-5">
          <Callout tone="warning">
            <b>Fiche à compléter.</b> Ce poste a été créé avec son seul intitulé : ses exigences
            — diplôme, années, domaines, pièces — sont des valeurs par défaut que personne n’a
            posées.{' '}
            {g.nombre_candidatures > 0
              ? `Les ${g.nombre_candidatures} dossier(s) déjà déposés ont été notés dessus et seront réévalués.`
              : 'Aucun avis ne peut être publié tant que c’est le cas.'}{' '}
            <button
              type="button"
              className="font-medium underline"
              onClick={() => setFicheOuverte(true)}
            >
              Compléter la fiche
            </button>
          </Callout>
        </div>
      )}

      <div className="mb-5 grid items-start gap-4 lg:grid-cols-2">
        <div className="space-y-4">
          <FichePoste poste={p} />
          <DocumentFiche
            poste={p}
            onProposition={(prop) => {
              setErreur(null)
              setCompteRendu(
                'Fiche jointe. Relisez ce qui en a été lu avant d’enregistrer — une valeur ' +
                  'mal lue deviendrait une exigence réelle.',
              )
              setProposition(prop)
              setFicheOuverte(true)
            }}
            onCompteRendu={(m) => {
              setErreur(null)
              setCompteRendu(m)
            }}
            onErreur={setErreur}
          />
        </div>
        <PanneauAvis posteId={posteId} poste={p} />
      </div>

      <div className="mb-5">
        <DepotEnLot posteId={posteId} />
      </div>

      {p.restriction.justification && (
        <div className="mb-5">
          <Callout tone="warning">
            <strong>Poste restreint.</strong> {p.restriction.justification}
          </Callout>
        </div>
      )}

      {p.seuil_justification && (
        <div className="mb-5">
          <Callout tone="info">
            <strong>Seuil abaissé à {g.seuil}.</strong> {p.seuil_justification}
          </Callout>
        </div>
      )}

      <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Statistique valeur={g.nombre_candidatures} libelle="Candidatures" ton="text-ink-900" />
        <Statistique
          valeur={g.nombre_preselectionnes}
          libelle={
            g.nombre_a_proposer
              ? `Préqualifiés · ${g.nombre_proposes} proposé(s)`
              : 'Préqualifiés'
          }
          ton="text-emerald-700"
          actif={onglet === 'preselection'}
          onClick={() => setOnglet('preselection')}
        />
        <Statistique
          valeur={g.nombre_elimines}
          libelle="Éliminés"
          ton="text-red-700"
          actif={onglet === 'elimination'}
          onClick={() => setOnglet('elimination')}
        />
        <Statistique
          valeur={g.nombre_a_verifier}
          libelle="À vérifier"
          ton="text-amber-700"
          actif={onglet === 'a_verifier'}
          onClick={() => setOnglet('a_verifier')}
        />
      </div>

      {g.nombre_candidatures === 0 ? (
        <EmptyState
          title="Aucune candidature"
          hint="Publiez un avis avec une référence, puis relevez la boîte email — ou saisissez un dossier à la main."
        />
      ) : (
        <>
          <div className="mb-4 flex gap-1 overflow-x-auto border-b border-ink-200">
            {onglets.map(([cle, libelle, nombre]) => (
              <button
                key={cle}
                type="button"
                onClick={() => setOnglet(cle)}
                className={`-mb-px shrink-0 border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
                  onglet === cle
                    ? 'border-ink-900 text-ink-900'
                    : 'border-transparent text-ink-500 hover:text-ink-800'
                }`}
              >
                {libelle} <span className="tabular-nums text-ink-400">({nombre})</span>
              </button>
            ))}
          </div>

          {onglet === 'preselection' && (
            <>
          {g.preselectionnes.length > 0 && (
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <button
                type="button"
                className="btn-ghost px-3 py-1.5 text-xs"
                onClick={() =>
                  setDestinataires(g.preselectionnes.map((ligne) => ligne.candidature_id))
                }
              >
                Écrire aux {g.preselectionnes.length} préqualifiés
              </button>
              {g.nombre_a_proposer !== null && g.nombre_proposes > 0 && (
                <button
                  type="button"
                  className="btn-ghost px-3 py-1.5 text-xs"
                  onClick={() =>
                    setDestinataires(
                      g.preselectionnes
                        .filter((ligne) => ligne.propose)
                        .map((ligne) => ligne.candidature_id),
                    )
                  }
                >
                  Écrire aux {g.nombre_proposes} proposés au client
                </button>
              )}
              <span className="text-xs text-ink-500">
                Le texte est montré avant d&apos;être expédié.
              </span>
            </div>
          )}
          <p className="mb-3 text-xs text-ink-500">
            Classement par note décroissante sur {g.total_max}, soit{' '}
            {g.poids_preselection} % de la note finale — les entretiens portent les{' '}
            {100 - g.poids_preselection} % restants.
            {g.nombre_a_proposer
              ? ` Les ${g.nombre_a_proposer} premiers sont proposés au client ; les suivants restent préqualifiés.`
              : " Aucun nombre de candidats à proposer n'est fixé sur ce poste."}
            {g.nombre_entretiens > 0
              ? ` ${g.nombre_entretiens} entretien(s) saisi(s).`
              : " Les entretiens se saisissent depuis le dossier d'un candidat."}
          </p>
          <TableauGrille lignes={g.preselectionnes} onOuvrir={setSelection} colonneRang />
        </>
          )}
          {onglet === 'sous_seuil' && (
            <TableauGrille lignes={g.non_retenus} onOuvrir={setSelection} />
          )}

          {onglet === 'a_verifier' && (
            <div>
              <div className="mb-3">
                <Callout tone="warning">
                  Ces dossiers reposent sur des données extraites automatiquement. Tant qu'un
                  relecteur ne les a pas confirmées, aucun motif ne peut les éliminer.
                </Callout>
              </div>
              {aVerifier.data?.items.length === 0 ? (
                <EmptyState title="Rien à vérifier" hint="Tous les dossiers ont été relus." />
              ) : (
                <div className="card divide-y divide-ink-100">
                  {aVerifier.data?.items.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => setSelection(item.id)}
                      className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-ink-50"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-ink-900">
                          {item.nom.toUpperCase()} {item.prenom}
                        </p>
                        <p className="truncate text-xs text-ink-500">
                          {item.motifs.length} motif(s) en attente de confirmation
                          {item.doublons > 0 && (
                            <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 font-medium text-amber-800">
                              {item.doublons} doublon(s)
                            </span>
                          )}
                        </p>
                      </div>
                      <span className="text-sm font-semibold tabular-nums text-ink-700">
                        {item.note ?? '—'}
                        <span className="text-ink-400">/{item.total_max ?? ''}</span>
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {onglet === 'elimination' && (
            <div className="space-y-6">
              {g.elimines.length === 0 && <EmptyState title="Aucun dossier éliminé" />}
              {g.elimines.map((groupe) => (
                <section key={groupe.motif}>
                  <h2 className="mb-2 text-sm font-semibold text-ink-900">
                    {groupe.libelle}
                    <span className="ml-2 font-normal text-ink-400">({groupe.lignes.length})</span>
                  </h2>
                  <TableauGrille lignes={groupe.lignes} onOuvrir={setSelection} colonneMotifs />
                </section>
              ))}
            </div>
          )}
        </>
      )}

      {selection && (
        <CandidatureDrawer
          candidatureId={selection}
          posteId={posteId}
          onClose={() => setSelection(null)}
          // Le tiroir s'est fermé sur un dossier qui n'existe plus : sans ce
          // rappel, la grille se recompte toute seule et rien ne dit ce qui
          // est parti.
          onSupprime={(compteRendu) => {
            setErreur(null)
            setCompteRendu(compteRendu)
          }}
        />
      )}

      {grilleOuverte && (
        <GrilleEntretienEditeur posteId={posteId} onClose={() => setGrilleOuverte(false)} />
      )}

      {ficheOuverte && (
        <FichePosteEditeur
          poste={p}
          proposition={proposition}
          onClose={() => {
            setFicheOuverte(false)
            setProposition(null)
          }}
          onEnregistre={(compteRendu) => {
            setErreur(null)
            setCompteRendu(compteRendu)
          }}
        />
      )}

      {choixExport && (
        <ChoisirExportGrille
          posteId={posteId}
          nombreEntretiens={g.nombre_entretiens}
          onClose={() => setChoixExport(false)}
          onExporte={(libelle) => {
            setErreur(null)
            setCompteRendu(`${libelle} téléchargé.`)
          }}
        />
      )}

      {choixPortee && (
        <ChoisirDestinataires
          posteId={posteId}
          onClose={() => setChoixPortee(false)}
          onChoisi={(ids, _libelle, note) => {
            setChoixPortee(false)
            setDestinataires(ids)
            // Les dossiers sans adresse ne recevront rien : le dire avant
            // l'envoi, pas après, sous forme d'échecs à interpréter.
            if (note) setCompteRendu(note)
          }}
        />
      )}

      {destinataires.length > 0 && (
        <EnvoyerAuxCandidats
          candidatureIds={destinataires}
          onClose={() => setDestinataires([])}
        />
      )}

      {seuilOuvert && (
        <ReglerSeuil
          posteId={posteId}
          seuilActuel={g.seuil}
          seuilNominal={p.seuil_nominal}
          totalMax={g.total_max}
          distribution={g.distribution}
          onClose={() => setSeuilOuvert(false)}
        />
      )}
    </div>
  )
}

