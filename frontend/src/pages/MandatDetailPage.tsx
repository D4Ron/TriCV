import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fichesApi, recrutementApi } from '@/lib/api'
import {
  Callout,
  EmptyState,
  ErrorState,
  Field,
  Modal,
  PageLoader,
  Spinner,
  delaiListe,
} from '@/components/ui'
import ActionsMandat from '@/components/ActionsMandat'
import PanneauEspaceClient from '@/components/PanneauEspaceClient'
import PanneauRapports from '@/components/PanneauRapports'
import { NIVEAUX } from '@/lib/niveaux'
import { enListe } from '@/lib/pieces'
import PiecesDuDossier, {
  CHOIX_PAR_DEFAUT,
  groupesDepuis,
  piecesVers,
  type ChoixPieces,
} from '@/components/PiecesDuDossier'
import type { GroupePieces } from '@/types'
import DepartPoste, { type Depart } from '@/components/DepartPoste'


/**
 * Ce qu'il faut dire d'un champ repris d'une fiche.
 *
 * Un champ lu dans le document se vérifie d'un coup d'œil ; un champ que
 * l'assistance a comblé se relit. Ne rien dire reviendrait à les présenter
 * comme équivalents, ce qu'ils ne sont pas.
 */
function aideOrigine(
  origines: Record<string, string>,
  champ: string,
): string | undefined {
  if (origines[champ] === 'document') return 'Lu dans la fiche.'
  if (origines[champ] === 'assistance') return 'Proposé par l’assistance — à vérifier.'
  return undefined
}

/** Une valeur de la proposition, si elle est du bon type. */
function depuis<T>(valeurs: Record<string, unknown> | undefined, cle: string, defaut: T): T {
  const valeur = valeurs?.[cle]
  return valeur === undefined || valeur === null ? defaut : (valeur as T)
}

function NouveauPoste({ mandatId, onClose }: { mandatId: string; onClose: () => void }) {
  const queryClient = useQueryClient()
  // Le formulaire ne s'ouvre plus d'emblée : on demande d'abord d'où vient le
  // poste. Une fiche existe presque toujours, et elle porte l'essentiel.
  const [depart, setDepart] = useState<Depart | null>(null)
  const proposition = depart?.mode === 'formulaire' ? depart.proposition : null
  const valeurs = proposition?.valeurs as Record<string, unknown> | undefined
  const origines = proposition?.origines ?? {}

  const [intitule, setIntitule] = useState('')
  const [niveau, setNiveau] = useState(4)
  const [domaines, setDomaines] = useState('')
  const [experience, setExperience] = useState(5)
  const [experienceSpec, setExperienceSpec] = useState(3)
  // Les domaines qui font compter une expérience comme « spécifique ». Ils
  // reprenaient en silence ceux du diplôme, ce qui est souvent juste et
  // parfois faux — un poste peut demander un diplôme en droit et une
  // expérience en passation de marchés. Le champ est désormais visible, et
  // vide il retombe sur l'ancien comportement.
  const [domainesExp, setDomainesExp] = useState('')
  // Les pièces, leurs formats et leurs groupes : un seul objet, et le même
  // bloc d'écran qu'à la modification de la fiche.
  const [choixPieces, setChoixPieces] = useState<ChoixPieces>(CHOIX_PAR_DEFAUT)
  const [erreur, setErreur] = useState<string | null>(null)

  /**
   * Reprend la proposition dans le formulaire, une fois la fiche lue.
   *
   * Seuls les champs que la fiche a renseignés bougent : ce qu'elle n'a pas
   * trouvé garde la valeur par défaut, qui reste un point de départ valable.
   */
  function reprendre(choix: Depart) {
    setDepart(choix)
    if (choix.mode !== 'formulaire' || !choix.proposition) return
    const v = choix.proposition.valeurs as Record<string, unknown>
    setIntitule(depuis(v, 'intitule', ''))
    setNiveau(depuis(v, 'niveau_min', 4))
    setDomaines(depuis<string[]>(v, 'domaines_acceptes', []).join(', '))
    setExperience(depuis(v, 'annees_experience_min', 5))
    setExperienceSpec(depuis(v, 'annees_experience_specifique_min', 3))
    setDomainesExp(depuis<string[]>(v, 'domaines_experience', []).join(', '))
    // Les pièces d'un coup : exigées, facultatives et alternatives se lisent sur
    // la même rubrique, et n'en reprendre qu'une partie ferait dire à la fiche
    // autre chose que ce qu'elle dit — « la CNI ou le passeport » deviendrait
    // deux exigences, ou rien.
    const requises = depuis<string[]>(v, 'pieces_requises', [])
    const facultatives = depuis<string[]>(v, 'pieces_facultatives', [])
    const groupes = groupesDepuis(depuis<GroupePieces[]>(v, 'groupes_pieces', []))
    if (requises.length || facultatives.length || groupes.length) {
      setChoixPieces((c) => ({
        ...c,
        requises: requises.length ? requises : c.requises,
        facultatives,
        groupes,
      }))
    }
  }

  const creer = useMutation({
    mutationFn: async () => {
      const poste = await recrutementApi.creerPoste(mandatId, {
        intitule: intitule.trim(),
        niveau_min: niveau,
        domaines_acceptes: enListe(domaines),
        annees_experience_min: experience,
        annees_experience_specifique_min: experienceSpec,
        domaines_experience: enListe(domainesExp).length
          ? enListe(domainesExp)
          : enListe(domaines),
        ...piecesVers(choixPieces),
        langues_requises: ['français'],
        // Ce que la fiche apporte et que le formulaire ne demande pas : on le
        // transmet tel quel plutôt que de le perdre entre la lecture et
        // l'enregistrement.
        localisation: depuis<string | null>(valeurs, 'localisation', null),
        rattachement: depuis<string | null>(valeurs, 'rattachement', null),
        description: depuis<string | null>(valeurs, 'description', null),
        missions: depuis<string[]>(valeurs, 'missions', []),
        responsabilites: depuis<string[]>(valeurs, 'responsabilites', []),
        competences_techniques: depuis<string[]>(valeurs, 'competences_techniques', []),
        competences_comportementales: depuis<string[]>(
          valeurs,
          'competences_comportementales',
          [],
        ),
      })

      // Le document suit le poste : c'est lui que la rédaction d'un avis
      // relira en entier. `proposer: false` — les champs viennent d'être
      // relus, il n'y a pas lieu de les reproposer.
      const source = depart?.mode === 'formulaire' ? depart.source : null
      if (source) {
        try {
          await fichesApi.joindre(poste.id, source, { proposer: false })
        } catch {
          // Le poste existe : perdre la pièce jointe ne doit pas le perdre
          // avec elle. Elle se rattache depuis la fiche du poste.
        }
      }
      return poste
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['postes', mandatId] })
      onClose()
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Création impossible'),
  })

  /** Le poste minimal : un intitulé, et tout le reste à compléter. */
  const creerRapide = useMutation({
    mutationFn: (titre: string) =>
      recrutementApi.creerPoste(mandatId, { intitule: titre, a_completer: true }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['postes', mandatId] })
      onClose()
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Création impossible'),
  })

  // Premier temps : d'où vient ce poste. Le formulaire ne s'ouvre qu'ensuite.
  if (depart === null) {
    return (
      <Modal open title="Nouveau poste" onClose={onClose}>
        <DepartPoste
          onChoix={(choix) => {
            if (choix.mode === 'plus-tard') creerRapide.mutate(choix.intitule)
            else reprendre(choix)
          }}
        />
        {erreur && (
          <div className="mt-3">
            <Callout tone="danger">{erreur}</Callout>
          </div>
        )}
      </Modal>
    )
  }

  return (
    <Modal open title="Nouvelle fiche de poste" onClose={onClose}>
      <div className="space-y-4">
        {proposition && (
          <Callout tone={proposition.avertissement ? 'warning' : 'info'}>
            {proposition.avertissement ?? (
              <>
                Champs repris de la fiche. Ceux marqués{' '}
                <b>proposé par l’assistance</b> n’ont pas été trouvés dans le document :
                relisez-les avant d’enregistrer.
              </>
            )}
          </Callout>
        )}

        <Field label="Intitulé du poste" htmlFor="poste-intitule" hint={aideOrigine(origines, 'intitule')}>
          <input
            id="poste-intitule"
            className="input"
            value={intitule}
            onChange={(e) => setIntitule(e.target.value)}
            placeholder="Directeur Général"
          />
        </Field>

        <Field label="Niveau de diplôme exigé" htmlFor="poste-niveau">
          <select
            id="poste-niveau"
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
          label="Domaines acceptés"
          htmlFor="poste-domaines"
          hint="Séparés par des virgules. Un diplôme hors de ces domaines est écarté comme non conforme."
        >
          <input
            id="poste-domaines"
            className="input"
            value={domaines}
            onChange={(e) => setDomaines(e.target.value)}
            placeholder="gestion hôtelière, management des affaires"
          />
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Expérience générale (ans)" htmlFor="poste-exp">
            <input
              id="poste-exp"
              type="number"
              min={0}
              max={60}
              className="input"
              value={experience}
              onChange={(e) => setExperience(Number(e.target.value))}
            />
          </Field>
          <Field label="Dont expérience spécifique" htmlFor="poste-exp-spec">
            <input
              id="poste-exp-spec"
              type="number"
              min={0}
              max={60}
              className="input"
              value={experienceSpec}
              onChange={(e) => setExperienceSpec(Number(e.target.value))}
            />
          </Field>
        </div>

        <Field
          label="Domaines de l'expérience spécifique"
          htmlFor="poste-domaines-exp"
          hint="Vide, ce sont les domaines de formation ci-dessus qui servent. Ce critère pèse 15 des 30 points : plusieurs exigences distinctes se règlent ensuite depuis « Modifier la fiche »."
        >
          <input
            id="poste-domaines-exp"
            className="input"
            value={domainesExp}
            onChange={(e) => setDomainesExp(e.target.value)}
            placeholder="passation des marchés, gestion de projet"
          />
        </Field>

        <PiecesDuDossier valeur={choixPieces} onChange={setChoixPieces} />

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
            disabled={!intitule.trim() || creer.isPending}
            onClick={() => creer.mutate()}
          >
            {creer.isPending && <Spinner />}
            Créer le poste
          </button>
        </div>
      </div>
    </Modal>
  )
}

const ONGLETS = [
  { cle: 'postes', libelle: 'Postes' },
  { cle: 'client', libelle: 'Espace du promoteur' },
  { cle: 'rapports', libelle: 'Rapports' },
] as const

type Onglet = (typeof ONGLETS)[number]['cle']

export default function MandatDetailPage() {
  const { mandatId = '' } = useParams()
  const navigate = useNavigate()
  const [ouvert, setOuvert] = useState(false)
  const [onglet, setOnglet] = useState<Onglet>('postes')

  const mandat = useQuery({
    queryKey: ['mandat', mandatId],
    queryFn: () => recrutementApi.mandat(mandatId),
  })
  const postes = useQuery({
    queryKey: ['postes', mandatId],
    queryFn: () => recrutementApi.postes(mandatId),
  })

  if (mandat.isLoading || postes.isLoading) return <PageLoader />
  if (mandat.isError) return <ErrorState error={mandat.error} onRetry={() => mandat.refetch()} />

  return (
    <div>
      <Link to="/mandats" className="text-xs text-ink-500 hover:underline">
        ← Tous les mandats
      </Link>

      <div className="mb-6 mt-2 flex flex-wrap items-start gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-ink-900">
            {mandat.data?.intitule}
          </h1>
          <p className="mt-1 text-sm text-ink-500">{mandat.data?.client_nom}</p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <ActionsMandat
            mandatId={mandatId}
            archive={mandat.data?.archive_le != null}
            onChange={() => navigate('/mandats')}
          />
          <button type="button" className="btn-primary" onClick={() => setOuvert(true)}>
            Nouveau poste
          </button>
        </div>
      </div>

      <div className="mb-6 flex gap-2 border-b border-ink-200">
        {ONGLETS.map((o) => (
          <button
            key={o.cle}
            type="button"
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${
              onglet === o.cle
                ? 'border-brand-700 font-medium text-brand-800'
                : 'border-transparent text-ink-500 hover:text-ink-800'
            }`}
            onClick={() => setOnglet(o.cle)}
          >
            {o.libelle}
          </button>
        ))}
      </div>

      {onglet === 'client' && <PanneauEspaceClient mandatId={mandatId} />}
      {onglet === 'rapports' && <PanneauRapports mandatId={mandatId} />}

      {onglet === 'postes' && (
      <>
      <h2 className="mb-1 text-sm font-semibold text-ink-900">Postes à pourvoir</h2>
      <p className="mb-3 text-xs text-ink-500">
        Un poste porte sa <strong>fiche de poste</strong> — le document interne qui fixe le
        niveau, les domaines, l'expérience et les pièces exigées. L'<strong>avis de
        recrutement</strong>, lui, se publie ensuite depuis le poste.
      </p>

      {postes.data && postes.data.length === 0 ? (
        <EmptyState
          title="Aucun poste"
          hint="Étape suivante : « Nouveau poste » ci-dessus. Tout ce que vous y saisirez devient une règle de présélection."
        />
      ) : (
        <div className="grid gap-3">
          {postes.data?.map((poste, index) => (
            <Link
              key={poste.id}
              to={`/postes/${poste.id}`}
              className="card-interactive stagger flex animate-rise flex-wrap items-center gap-3 p-4"
              style={delaiListe(index)}
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-ink-900">{poste.intitule}</p>
                <p className="mt-0.5 text-xs text-ink-500">
                  BAC+{poste.niveau_min} · {poste.annees_experience_min} ans d'expérience
                  {poste.domaines_acceptes.length > 0
                    ? ` · ${poste.domaines_acceptes.join(', ')}`
                    : ''}
                </p>
              </div>
              {poste.restriction.justification && (
                <span
                  className="badge bg-amber-100 text-amber-800"
                  title={poste.restriction.justification}
                >
                  Poste restreint
                </span>
              )}
              <span className="text-xs text-ink-500">
                {poste.nombre_candidatures} candidature
                {poste.nombre_candidatures > 1 ? 's' : ''}
              </span>
            </Link>
          ))}
        </div>
      )}

      {postes.data && postes.data.length > 0 && (
        <div className="mt-6">
          <Callout tone="info">
            Aucun seuil de présélection n'est posé au départ : c'est le classement qui
            sélectionne. La barre se trace sur la grille du poste, une fois les notes connues —
            et l'abaisser ensuite demande une justification écrite.
          </Callout>
        </div>
      )}
      </>
      )}

      {ouvert && <NouveauPoste mandatId={mandatId} onClose={() => setOuvert(false)} />}
    </div>
  )
}
