import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { recrutementApi } from '@/lib/api'
import {
  Badge,
  EmptyState,
  ErrorState,
  Field,
  Modal,
  PageLoader,
  Spinner,
  delaiListe,
} from '@/components/ui'
import GuidePipeline from '@/components/GuidePipeline'
import PanneauCourriel from '@/components/PanneauCourriel'
import ActionsMandat from '@/components/ActionsMandat'
import { formatDate } from '@/lib/format'
import type { StatutMandat } from '@/types'

const TON_STATUT: Record<StatutMandat, string> = {
  PROSPECT: 'bg-ink-100 text-ink-700',
  AMI_SOUMIS: 'bg-blue-100 text-blue-800',
  OFFRE_SOUMISE: 'bg-blue-100 text-blue-800',
  GAGNE: 'bg-emerald-100 text-emerald-800',
  PERDU: 'bg-red-100 text-red-700',
  CLOTURE: 'bg-ink-100 text-ink-500',
}

const LIBELLE_STATUT: Record<StatutMandat, string> = {
  PROSPECT: 'Prospect',
  AMI_SOUMIS: "Manifestation d'intérêt soumise",
  OFFRE_SOUMISE: 'Offre soumise',
  GAGNE: 'Gagné',
  PERDU: 'Perdu',
  CLOTURE: 'Clôturé',
}

const LIBELLE_ATTRIBUTION: Record<string, string> = {
  NATIONAL: 'National',
  INTERNATIONAL: 'International',
  GRE_A_GRE: 'Gré à gré',
}

function NouveauMandat({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient()
  const clients = useQuery({ queryKey: ['clients'], queryFn: () => recrutementApi.clients() })

  const [clientId, setClientId] = useState('')
  const [nouveauClient, setNouveauClient] = useState('')
  const [intitule, setIntitule] = useState('')
  const [attribution, setAttribution] = useState('NATIONAL')
  const [erreur, setErreur] = useState<string | null>(null)

  const creer = useMutation({
    mutationFn: async () => {
      // Créer le client à la volée évite un aller-retour par une autre page
      // pour le cas le plus courant : un nouveau client, un premier mandat.
      let identifiant = clientId
      if (!identifiant) {
        if (!nouveauClient.trim()) throw new Error('Indiquez un client.')
        identifiant = (await recrutementApi.creerClient({ nom: nouveauClient.trim() })).id
      }
      return recrutementApi.creerMandat({
        client_id: identifiant,
        intitule: intitule.trim(),
        type_attribution: attribution,
      })
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['mandats'] })
      void queryClient.invalidateQueries({ queryKey: ['clients'] })
      onClose()
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Création impossible'),
  })

  return (
    <Modal open title="Nouveau mandat" onClose={onClose}>
      <div className="space-y-4">
        <Field label="Client" htmlFor="client">
          <select
            id="client"
            className="input"
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
          >
            <option value="">— Nouveau client —</option>
            {clients.data?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.nom}
              </option>
            ))}
          </select>
        </Field>

        {!clientId && (
          <Field label="Nom du client" htmlFor="nouveau-client">
            <input
              id="nouveau-client"
              className="input"
              value={nouveauClient}
              onChange={(e) => setNouveauClient(e.target.value)}
              placeholder="TRANSCO CLSG"
            />
          </Field>
        )}

        <Field label="Intitulé du mandat" htmlFor="intitule">
          <input
            id="intitule"
            className="input"
            value={intitule}
            onChange={(e) => setIntitule(e.target.value)}
            placeholder="Recrutement du Directeur Général"
          />
        </Field>

        <Field
          label="Mode d'attribution"
          htmlFor="attribution"
          hint="Gré à gré : marché attribué directement, sans mise en concurrence."
        >
          <select
            id="attribution"
            className="input"
            value={attribution}
            onChange={(e) => setAttribution(e.target.value)}
          >
            {Object.entries(LIBELLE_ATTRIBUTION).map(([valeur, libelle]) => (
              <option key={valeur} value={valeur}>
                {libelle}
              </option>
            ))}
          </select>
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
            Créer le mandat
          </button>
        </div>
      </div>
    </Modal>
  )
}

export default function MandatsPage() {
  const [filtre, setFiltre] = useState('')
  const [archives, setArchives] = useState(false)
  const [ouvert, setOuvert] = useState(false)

  const mandats = useQuery({
    queryKey: ['mandats', filtre, archives],
    queryFn: () =>
      recrutementApi.mandats({ ...(filtre ? { statut: filtre } : {}), archives }),
  })

  if (mandats.isLoading) return <PageLoader />
  if (mandats.isError) return <ErrorState error={mandats.error} onRetry={() => mandats.refetch()} />

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-ink-900">Mandats</h1>
          <p className="mt-1 text-sm text-ink-500">
            Chaque mandat regroupe les postes à pourvoir pour un client.
          </p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <PanneauCourriel />
          <select
            className="input w-auto"
            value={filtre}
            onChange={(e) => setFiltre(e.target.value)}
            aria-label="Filtrer par statut"
          >
            <option value="">Tous les statuts</option>
            {Object.entries(LIBELLE_STATUT).map(([valeur, libelle]) => (
              <option key={valeur} value={valeur}>
                {libelle}
              </option>
            ))}
          </select>
          <label className="flex items-center gap-1.5 text-xs text-ink-600">
            <input
              type="checkbox"
              checked={archives}
              onChange={(e) => setArchives(e.target.checked)}
            />
            Afficher les archives
          </label>
          <button type="button" className="btn-primary" onClick={() => setOuvert(true)}>
            Nouveau mandat
          </button>
        </div>
      </div>

      {/* Ouvert d'office tant qu'aucun mandat n'existe : c'est le moment où
          l'on ignore par où commencer. */}
      <GuidePipeline ouvertParDefaut={mandats.data?.length === 0} />

      {mandats.data && mandats.data.length === 0 ? (
        <EmptyState
          title="Aucun mandat"
          hint="Commencez par « Nouveau mandat » ci-dessus : un client, un engagement. Les postes à pourvoir se décrivent ensuite à l'intérieur."
        />
      ) : (
        <div className="grid gap-3">
          {mandats.data?.map((mandat, index) => (
            <div
              key={mandat.id}
              className="card-interactive stagger flex animate-rise flex-wrap items-center gap-3 p-4"
              style={delaiListe(index)}
            >
              <Link to={`/mandats/${mandat.id}`} className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-ink-900">{mandat.intitule}</p>
                <p className="mt-0.5 truncate text-xs text-ink-500">
                  {mandat.client_nom}
                  {mandat.type_attribution
                    ? ` · ${LIBELLE_ATTRIBUTION[mandat.type_attribution]}`
                    : ''}
                </p>
              </Link>
              <Badge tone={TON_STATUT[mandat.statut]}>{LIBELLE_STATUT[mandat.statut]}</Badge>
              {mandat.archive_le && (
                <Badge tone="bg-ink-200 text-ink-600">Archivé</Badge>
              )}
              <span className="text-xs text-ink-500">
                {mandat.nombre_postes} poste{mandat.nombre_postes > 1 ? 's' : ''}
              </span>
              <span className="text-xs text-ink-400">{formatDate(mandat.created_at, 'fr')}</span>
              <ActionsMandat
                mandatId={mandat.id}
                archive={mandat.archive_le !== null}
                onChange={() => void mandats.refetch()}
              />
            </div>
          ))}
        </div>
      )}

      {ouvert && <NouveauMandat onClose={() => setOuvert(false)} />}
    </div>
  )
}
