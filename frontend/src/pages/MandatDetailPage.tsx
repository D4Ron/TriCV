import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { recrutementApi } from '@/lib/api'
import { Callout, EmptyState, ErrorState, Field, Modal, PageLoader, Spinner } from '@/components/ui'
import ActionsMandat from '@/components/ActionsMandat'

const NIVEAUX = [
  [0, 'BAC'],
  [2, 'BAC+2 (DUT, BTS)'],
  [3, 'BAC+3 (Licence)'],
  [4, 'BAC+4 (Maîtrise, Master 1)'],
  [5, 'BAC+5 (Master, Ingénieur)'],
  [8, 'BAC+8 (Doctorat)'],
] as const

const PIECES = [
  ['LETTRE_MOTIVATION', 'Lettre de motivation'],
  ['CV', 'CV détaillé'],
  ['COPIE_DIPLOMES', 'Copie des diplômes'],
  ['ATTESTATIONS_TRAVAIL', 'Attestations de travail'],
  ['PIECE_IDENTITE', "Pièce d'identité"],
  ['CERTIFICAT_NATIONALITE', 'Certificat de nationalité'],
] as const

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
  const [pieces, setPieces] = useState<string[]>(['LETTRE_MOTIVATION', 'CV'])
  const [facultatives, setFacultatives] = useState<string[]>([])
  const [erreur, setErreur] = useState<string | null>(null)

  const creer = useMutation({
    mutationFn: () =>
      recrutementApi.creerPoste(mandatId, {
        intitule: intitule.trim(),
        niveau_min: niveau,
        domaines_acceptes: enListe(domaines),
        annees_experience_min: experience,
        annees_experience_specifique_min: experienceSpec,
        domaines_experience: enListe(domaines),
        pieces_requises: pieces,
        pieces_facultatives: facultatives,
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
            {NIVEAUX.map(([valeur, libelle]) => (
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
          label="Pièces du dossier"
          hint="Exigée : son absence élimine le dossier. Facultative : acceptée, jamais éliminatoire."
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

export default function MandatDetailPage() {
  const { mandatId = '' } = useParams()
  const navigate = useNavigate()
  const [ouvert, setOuvert] = useState(false)

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
          {postes.data?.map((poste) => (
            <Link
              key={poste.id}
              to={`/postes/${poste.id}`}
              className="card flex flex-wrap items-center gap-3 p-4 transition-colors hover:border-ink-300"
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
            Le seuil de présélection est de 20/30 par défaut. Il se règle poste par poste, et
            l'abaisser demande une justification écrite.
          </Callout>
        </div>
      )}

      {ouvert && <NouveauPoste mandatId={mandatId} onClose={() => setOuvert(false)} />}
    </div>
  )
}
