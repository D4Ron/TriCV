import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ApiError, recrutementApi, type PurgeResultat } from '@/lib/api'
import { Callout, EmptyState, ErrorState, Modal, PageLoader, Spinner } from '@/components/ui'
import { formatDate } from '@/lib/format'

/**
 * Les archives, et le seul endroit d'où l'on peut effacer définitivement.
 *
 * Ce détour est volontaire : une suppression irréversible ne doit pas se
 * trouver à portée de clic d'une liste de travail. On archive d'abord — geste
 * réversible et sans perte — et l'effacement se décide ici, à froid, sur un
 * dossier qu'on est déjà venu chercher.
 */

/**
 * Purge des fichiers d'un mandat archivé.
 *
 * C'est ainsi qu'on maîtrise le stockage — en bornant ce qu'on garde dans le
 * temps — plutôt qu'en refusant à l'arrivée un scan de diplômes un peu lourd.
 * Les CV et lettres disparaissent ; le parcours saisi, la note et son détail,
 * les motifs d'élimination restent. Une grille recalculée après purge donne le
 * même résultat qu'avant.
 */
function PurgeFichiers({ mandatId, titre }: { mandatId: string; titre: string }) {
  const [ouvert, setOuvert] = useState(false)
  const [fait, setFait] = useState<PurgeResultat | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)

  const estimation = useQuery({
    queryKey: ['purge', mandatId],
    queryFn: () => recrutementApi.estimerPurge(mandatId),
    enabled: ouvert,
  })

  const purger = useMutation({
    mutationFn: () => recrutementApi.purgerMandat(mandatId),
    onSuccess: (resultat) => {
      setOuvert(false)
      setFait(resultat)
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Purge impossible'),
  })

  if (fait) {
    return (
      <span className="text-xs text-ink-500">
        {fait.fichiers} fichier(s) effacé(s) · {fait.mo} Mo libérés
      </span>
    )
  }

  return (
    <>
      <button
        type="button"
        className="btn-ghost px-2 py-1 text-xs"
        onClick={() => {
          setErreur(null)
          setOuvert(true)
        }}
      >
        Purger les fichiers
      </button>

      {ouvert && (
        <Modal open title={`Purger les fichiers de « ${titre} » ?`} onClose={() => setOuvert(false)}>
          {estimation.isLoading ? (
            <p className="text-sm text-ink-500">Calcul en cours…</p>
          ) : estimation.data && estimation.data.fichiers === 0 ? (
            <p className="text-sm text-ink-600">
              Ce mandat ne conserve plus aucun fichier. Rien à purger.
            </p>
          ) : (
            <>
              <p className="text-sm text-ink-700">
                {estimation.data?.fichiers} fichier(s), {estimation.data?.mo} Mo, répartis sur{' '}
                {estimation.data?.candidatures} candidature(s).
              </p>
              <Callout tone="warning" title="Ce qui est effacé, ce qui reste">
                Les CV, lettres et diplômes sont supprimés du disque. Les dossiers restent
                entiers : parcours saisi, note et son détail, motifs d'élimination, historique.
                La grille reste reproductible à l'identique.
              </Callout>
              {erreur && <Callout tone="danger">{erreur}</Callout>}
            </>
          )}

          <div className="mt-4 flex flex-wrap justify-end gap-2">
            <button type="button" className="btn-ghost" onClick={() => setOuvert(false)}>
              {estimation.data?.fichiers === 0 ? 'Fermer' : 'Annuler'}
            </button>
            {estimation.data && estimation.data.fichiers > 0 && (
              <button
                type="button"
                className="btn-primary"
                disabled={purger.isPending}
                onClick={() => purger.mutate()}
              >
                {purger.isPending && <Spinner />}
                Effacer les fichiers
              </button>
            )}
          </div>
        </Modal>
      )}
    </>
  )
}

function LigneArchivee({
  titre,
  soustitre,
  date,
  contenu,
  desarchiver,
  supprimer,
  onChange,
  actions,
}: {
  titre: string
  soustitre: string
  date: string | null
  contenu: string
  desarchiver: () => Promise<unknown>
  supprimer: (confirmer: boolean) => Promise<{ candidatures: number }>
  onChange: () => void
  actions?: ReactNode
}) {
  const [confirmation, setConfirmation] = useState<string | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)

  const restaurer = useMutation({
    mutationFn: desarchiver,
    onSuccess: onChange,
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Action impossible'),
  })

  const effacer = useMutation({
    mutationFn: (confirmer: boolean) => supprimer(confirmer),
    onSuccess: () => {
      setConfirmation(null)
      onChange()
    },
    onError: (e) => {
      if (e instanceof ApiError && e.status === 409) {
        setConfirmation(e.message.replace(/\s*Confirmez avec.*$/s, ''))
        return
      }
      setErreur(e instanceof Error ? e.message : 'Suppression impossible')
    },
  })

  return (
    <div className="card flex flex-wrap items-center gap-3 p-4">
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-semibold text-ink-900">{titre}</p>
        <p className="mt-0.5 truncate text-xs text-ink-500">
          {soustitre} · {contenu}
          {date ? ` · archivé le ${formatDate(date, 'fr')}` : ''}
        </p>
      </div>

      {actions}
      <button
        type="button"
        className="btn-ghost px-2 py-1 text-xs"
        disabled={restaurer.isPending}
        onClick={() => restaurer.mutate()}
      >
        {restaurer.isPending && <Spinner />}
        Restaurer
      </button>
      <button
        type="button"
        className="btn-ghost px-2 py-1 text-xs text-red-700 hover:bg-red-50"
        disabled={effacer.isPending}
        onClick={() => {
          setErreur(null)
          effacer.mutate(false)
        }}
      >
        Supprimer définitivement
      </button>

      {erreur && (
        <Modal open title="Action impossible" onClose={() => setErreur(null)}>
          <Callout tone="danger">{erreur}</Callout>
          <div className="mt-4 flex justify-end">
            <button type="button" className="btn-ghost" onClick={() => setErreur(null)}>
              Fermer
            </button>
          </div>
        </Modal>
      )}

      {confirmation && (
        <Modal
          open
          tone="danger"
          title={`Supprimer définitivement « ${titre} » ?`}
          onClose={() => setConfirmation(null)}
        >
          <Callout tone="danger">{confirmation}</Callout>
          <p className="mt-3 text-sm text-ink-600">
            Les candidatures seront effacées, ainsi que les états civils qui ne seraient plus
            rattachés à aucune autre candidature. Rien ne pourra être récupéré.
          </p>
          <div className="mt-4 flex flex-wrap justify-end gap-2">
            <button type="button" className="btn-ghost" onClick={() => setConfirmation(null)}>
              Annuler
            </button>
            <button
              type="button"
              className="btn-primary bg-red-600 hover:bg-red-700"
              disabled={effacer.isPending}
              onClick={() => effacer.mutate(true)}
            >
              {effacer.isPending && <Spinner />}
              Supprimer définitivement
            </button>
          </div>
        </Modal>
      )}
    </div>
  )
}

export default function ArchivesPage() {
  const mandats = useQuery({
    queryKey: ['mandats', 'archives'],
    queryFn: () => recrutementApi.mandats({ archives: true }),
  })
  const clients = useQuery({
    queryKey: ['clients', 'archives'],
    queryFn: () => recrutementApi.clients(undefined, true),
  })

  if (mandats.isLoading || clients.isLoading) return <PageLoader />
  if (mandats.isError) return <ErrorState error={mandats.error} onRetry={() => mandats.refetch()} />

  const mandatsArchives = (mandats.data ?? []).filter((m) => m.archive_le !== null)
  const clientsArchives = (clients.data ?? []).filter((c) => c.archive_le !== null)
  const rafraichir = () => {
    void mandats.refetch()
    void clients.refetch()
  }

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-xl font-semibold tracking-tight text-ink-900">Archives</h1>
        <p className="mt-1 text-sm text-ink-500">
          Les dossiers archivés restent complets et consultables. C'est aussi le seul endroit
          d'où ils peuvent être supprimés définitivement.
        </p>
        <p className="mt-1 text-sm text-ink-500">
          Purger les fichiers d'un mandat terminé efface les CV et les lettres du disque et garde
          tout le reste : parcours saisi, notes, motifs d'élimination, historique. C'est ainsi que
          le stockage se maîtrise — aucune limite de taille n'est imposée au dépôt.
        </p>
      </div>

      {mandatsArchives.length === 0 && clientsArchives.length === 0 ? (
        <EmptyState
          title="Aucune archive"
          hint="Archivez un mandat depuis sa fiche lorsqu'il est terminé ou abandonné : rien n'est effacé, il sort simplement des listes de travail."
        />
      ) : (
        <div className="space-y-8">
          {mandatsArchives.length > 0 && (
            <section>
              <h2 className="mb-3 text-sm font-semibold text-ink-900">
                Mandats <span className="font-normal text-ink-400">({mandatsArchives.length})</span>
              </h2>
              <div className="grid gap-3">
                {mandatsArchives.map((mandat) => (
                  <LigneArchivee
                    key={mandat.id}
                    titre={mandat.intitule}
                    soustitre={mandat.client_nom ?? '—'}
                    date={mandat.archive_le}
                    contenu={`${mandat.nombre_postes} poste(s)`}
                    desarchiver={() => recrutementApi.desarchiverMandat(mandat.id)}
                    supprimer={(c) => recrutementApi.supprimerMandat(mandat.id, c)}
                    onChange={rafraichir}
                    actions={<PurgeFichiers mandatId={mandat.id} titre={mandat.intitule} />}
                  />
                ))}
              </div>
            </section>
          )}

          {clientsArchives.length > 0 && (
            <section>
              <h2 className="mb-3 text-sm font-semibold text-ink-900">
                Clients <span className="font-normal text-ink-400">({clientsArchives.length})</span>
              </h2>
              <div className="grid gap-3">
                {clientsArchives.map((client) => (
                  <LigneArchivee
                    key={client.id}
                    titre={client.nom}
                    soustitre={client.secteur ?? '—'}
                    date={client.archive_le}
                    contenu={`${client.nombre_mandats} mandat(s)`}
                    desarchiver={() => recrutementApi.desarchiverClient(client.id)}
                    supprimer={(c) => recrutementApi.supprimerClient(client.id, c)}
                    onChange={rafraichir}
                  />
                ))}
              </div>
            </section>
          )}
        </div>
      )}

      <p className="mt-8 text-xs text-ink-500">
        <Link to="/mandats" className="hover:underline">
          ← Retour aux mandats
        </Link>
      </p>
    </div>
  )
}
