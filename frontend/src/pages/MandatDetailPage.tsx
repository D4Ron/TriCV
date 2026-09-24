import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { recrutementApi } from '@/lib/api'
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


const PIECES = [
  ['LETTRE_MOTIVATION', 'Lettre de motivation'],
  ['CV', 'CV détaillé'],
  ['COPIE_DIPLOMES', 'Copie des diplômes'],
  ['ATTESTATIONS_TRAVAIL', 'Attestations de travail'],
  ['PIECE_IDENTITE', "Carte nationale d'identité"],
  ['PASSEPORT', 'Passeport'],
  ['CERTIFICAT_NATIONALITE', 'Certificat de nationalité'],
  ['LETTRE_RECOMMANDATION', 'Lettre de recommandation'],
] as const

/**
 * Les groupes de pièces liées.
 *
 * Deux besoins que « exigée / facultative » ne sait pas exprimer :
 * « la carte d'identité **ou** le passeport » — exiger les deux obligerait un
 * candidat qui n'a qu'un passeport valide à en refaire une — et « le diplôme
 * **et** son attestation », qui ne valent rien l'un sans l'autre.
 */
const GROUPES_TYPES = [
  {
    libelle: "Pièce d'identité",
    mode: 'AU_MOINS_UNE' as const,
    codes: ['PIECE_IDENTITE', 'PASSEPORT'],
    aide: "La carte nationale d'identité ou le passeport, au choix du candidat.",
  },
  {
    libelle: 'Diplôme et attestation',
    mode: 'TOUTES' as const,
    codes: ['COPIE_DIPLOMES', 'ATTESTATIONS_TRAVAIL'],
    aide: "Les deux sont exigés : l'un sans l'autre ne prouve rien.",
  },
]

/** Découpe une saisie « a, b ; c » en liste propre. */
function enListe(valeur: string): string[] {
  return valeur
    .split(/[,;]/)
    .map((x) => x.trim())
    .filter(Boolean)
}

function NouveauPoste({ mandatId, onClose }: { mandatId: string; onClose: () => void }) {
  const queryClient = useQueryClient()
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
  const [pieces, setPieces] = useState<string[]>(['LETTRE_MOTIVATION', 'CV'])
  const [facultatives, setFacultatives] = useState<string[]>([])
  const [groupes, setGroupes] = useState<number[]>([])
  // Formats imposés, par code de pièce. Vide = tout format accepté.
  const [pdfSeul, setPdfSeul] = useState<string[]>([])
  const [libresAutorisees, setLibresAutorisees] = useState(true)
  const [erreur, setErreur] = useState<string | null>(null)

  const creer = useMutation({
    mutationFn: () =>
      recrutementApi.creerPoste(mandatId, {
        intitule: intitule.trim(),
        niveau_min: niveau,
        domaines_acceptes: enListe(domaines),
        annees_experience_min: experience,
        annees_experience_specifique_min: experienceSpec,
        domaines_experience: enListe(domainesExp).length
          ? enListe(domainesExp)
          : enListe(domaines),
        pieces_requises: pieces,
        pieces_facultatives: facultatives,
        groupes_pieces: groupes.map((i) => ({
          codes: GROUPES_TYPES[i].codes,
          mode: GROUPES_TYPES[i].mode,
          libelle: GROUPES_TYPES[i].libelle,
        })),
        formats_pieces: Object.fromEntries(pdfSeul.map((code) => [code, ['pdf']])),
        pieces_libres_autorisees: libresAutorisees,
        langues_requises: ['français'],
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['postes', mandatId] })
      onClose()
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Création impossible'),
  })

  return (
    <Modal open title="Nouvelle fiche de poste" onClose={onClose}>
      <div className="space-y-4">
        <Field label="Intitulé du poste" htmlFor="poste-intitule">
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

        <Field
          label="Pièces du dossier"
          hint="Exigée : son absence élimine le dossier. Facultative : acceptée, jamais éliminatoire. Cochez « PDF » pour imposer ce format."
        >
          <div className="space-y-1.5">
            {PIECES.map(([code, libelle]) => {
              const etat = pieces.includes(code)
                ? 'exigee'
                : facultatives.includes(code)
                  ? 'facultative'
                  : 'aucune'
              return (
                <div key={code} className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 truncate text-sm text-ink-700">{libelle}</span>
                  <label className="flex items-center gap-1 text-xs text-ink-500">
                    <input
                      type="checkbox"
                      checked={pdfSeul.includes(code)}
                      aria-label={`PDF exigé — ${libelle}`}
                      onChange={(e) =>
                        setPdfSeul((a) =>
                          e.target.checked ? [...a, code] : a.filter((c) => c !== code),
                        )
                      }
                    />
                    PDF
                  </label>
                  <select
                    className="input w-auto py-1 text-xs"
                    value={etat}
                    aria-label={libelle}
                    onChange={(e) => {
                      const v = e.target.value
                      setPieces((a) => (v === 'exigee' ? [...a, code] : a.filter((c) => c !== code)))
                      setFacultatives((a) =>
                        v === 'facultative' ? [...a, code] : a.filter((c) => c !== code),
                      )
                    }}
                  >
                    <option value="aucune">Non demandée</option>
                    <option value="exigee">Exigée</option>
                    <option value="facultative">Facultative</option>
                  </select>
                </div>
              )
            })}
          </div>
        </Field>

        <Field
          label="Pièces liées"
          hint="Ce que « exigée / facultative » ne sait pas dire : un choix entre deux documents, ou deux documents indissociables."
        >
          <div className="space-y-1.5">
            {GROUPES_TYPES.map((groupe, index) => (
              <label key={groupe.libelle} className="flex items-start gap-2 text-sm text-ink-700">
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={groupes.includes(index)}
                  onChange={(e) =>
                    setGroupes((a) =>
                      e.target.checked ? [...a, index] : a.filter((i) => i !== index),
                    )
                  }
                />
                <span>
                  {groupe.libelle}
                  <span className="block text-xs text-ink-500">{groupe.aide}</span>
                </span>
              </label>
            ))}
          </div>
        </Field>

        <label className="flex items-start gap-2 text-sm text-ink-700">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={libresAutorisees}
            onChange={(e) => setLibresAutorisees(e.target.checked)}
          />
          <span>
            Autoriser les documents libres
            <span className="block text-xs text-ink-500">
              Le candidat peut joindre ce qu'il juge utile — lettre de recommandation,
              attestation — en le nommant lui-même.
            </span>
          </span>
        </label>

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
