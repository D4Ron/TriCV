import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { dossiersApi, recrutementApi } from '@/lib/api'
import { useAnnulable } from '@/lib/annulable'
import { Callout, Modal } from '@/components/ui'
import { formatDate } from '@/lib/format'
import RattacherPoste from '@/components/RattacherPoste'

/**
 * Les candidatures reçues sans poste, pièces en main.
 *
 * Surtout des courriels dont l'objet ne citait aucun avis. Le relevé les prend
 * tous, et c'est voulu : un dossier inutile se supprime, une candidature manquée
 * ne se rattrape pas. Encore faut-il que le ménage soit rapide : on coche — un
 * à un, ou tout ce qui vient d'une même adresse —, on supprime d'un coup, et on
 * peut demander que ces expéditeurs ne produisent plus de dossier.
 *
 * Les retenues de la suppression unitaire tiennent : un dossier passé en
 * entretien, écrit ou présélectionné n'est pas supprimé sans confirmation.
 */

const SOURCES: Record<string, string> = {
  EMAIL: 'Courriel',
  FORMULAIRE: 'Formulaire du site',
  IMPORT_MANUEL: 'Déposé par les RH',
}

export default function DossiersSansPoste() {
  const queryClient = useQueryClient()
  const liste = useQuery({ queryKey: ['dossiers-sans-poste'], queryFn: dossiersApi.sansPoste })
  const [compteRendu, setCompteRendu] = useState<{ texte: string; posteId?: string } | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  const [coches, setCoches] = useState<Set<string>>(new Set())
  const [confirmation, setConfirmation] = useState(false)
  const [motif, setMotif] = useState('Pas une candidature')
  const [ignorerExpediteurs, setIgnorerExpediteurs] = useState(true)
  const [retenus, setRetenus] = useState<Array<{ id: string; nom: string; raison: string }>>([])
  const annulable = useAnnulable()

  const dossiers = liste.data ?? []

  // Les provenances qui reviennent : de quoi écarter d'un coup toute une
  // lettre d'information.
  const provenances = useMemo(() => {
    const compte = new Map<string, number>()
    dossiers.forEach((d) => d.domaine && compte.set(d.domaine, (compte.get(d.domaine) ?? 0) + 1))
    return [...compte.entries()].filter(([, n]) => n > 1).sort((a, b) => b[1] - a[1])
  }, [dossiers])

  const supprimer = useMutation({
    mutationFn: (p: { ids: string[]; motif: string; ignorer: boolean; confirmer: boolean }) =>
      dossiersApi.supprimerEnLot(p.ids, p.motif, {
        ignorerExpediteurs: p.ignorer,
        confirmer: p.confirmer,
      }),
    onSuccess: (r) => {
      setCoches(new Set())
      setRetenus(r.retenus)
      const parts = [`${r.supprimes} dossier(s) supprimé(s)`]
      if (r.retenus.length) parts.push(`${r.retenus.length} gardé(s), à confirmer`)
      if (r.expediteurs_ignores.length)
        parts.push(`${r.expediteurs_ignores.length} expéditeur(s) désormais ignoré(s)`)
      setCompteRendu({ texte: parts.join(' · ') + '.' })
      void queryClient.invalidateQueries({ queryKey: ['dossiers-sans-poste'] })
      void queryClient.invalidateQueries({ queryKey: ['vivier'] })
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Suppression impossible'),
  })

  const ouvrir = async (candidatureId: string, pieceId: string) => {
    setErreur(null)
    // Ouverte avant l'attente : un onglet ouvert après coup serait bloqué
    // comme fenêtre surgissante.
    const onglet = window.open('', '_blank')
    try {
      const url = await recrutementApi.pieceObjectUrl(candidatureId, pieceId)
      if (onglet) onglet.location.href = url
      else window.location.href = url
    } catch (e) {
      onglet?.close()
      setErreur(e instanceof Error ? e.message : 'Pièce indisponible')
    }
  }

  if (!liste.data || (dossiers.length === 0 && !compteRendu)) return annulable.bandeau

  const basculer = (id: string) =>
    setCoches((s) => {
      const n = new Set(s)
      if (n.has(id)) n.delete(id)
      else n.add(id)
      return n
    })
  const tout = dossiers.length > 0 && dossiers.every((d) => coches.has(d.id))
  const selection = dossiers.filter((d) => coches.has(d.id))
  const adresses = new Set(selection.map((d) => d.email).filter(Boolean))

  const lancer = (confirmer = false, ids = selection.map((d) => d.id)) => {
    const p = { ids, motif: motif.trim(), ignorer: ignorerExpediteurs, confirmer }
    setConfirmation(false)
    setErreur(null)
    annulable.programmer(`Suppression de ${ids.length} dossier(s)…`, () => supprimer.mutate(p))
  }

  return (
    <section className="card mb-5 p-4">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-sm font-semibold text-ink-900">
          Candidatures sans poste <span className="font-normal text-ink-400">({dossiers.length})</span>
        </h2>
        <Link to="/boite" className="ml-auto text-xs font-medium text-brand-700 underline">
          Ouvrir la boîte de recrutement
        </Link>
      </div>
      <p className="mt-1 text-xs text-ink-500">
        Reçues hors de tout avis — le plus souvent un courriel dont l&apos;objet ne nommait aucun
        poste. Rangez sous son poste ce qui est une candidature ; supprimez d&apos;un coup ce qui
        n&apos;en est pas une.
      </p>

      {compteRendu && (
        <div className="mt-3">
          <Callout tone="success">
            {compteRendu.texte}{' '}
            {compteRendu.posteId && (
              <Link to={`/postes/${compteRendu.posteId}`} className="font-medium underline">
                Ouvrir le poste
              </Link>
            )}
          </Callout>
        </div>
      )}
      {retenus.length > 0 && (
        <div className="mt-3">
          <Callout tone="warning">
            Gardés, parce qu&apos;ils ne ressemblent pas à une erreur :
            <ul className="mt-1 list-disc pl-5">
              {retenus.map((r) => (
                <li key={r.id}>
                  {r.nom} — {r.raison.replace(/^Ce dossier ne ressemble pas à une erreur de saisie : /, '')}
                </li>
              ))}
            </ul>
            <button
              type="button"
              className="mt-2 font-medium underline"
              onClick={() => {
                const ids = retenus.map((r) => r.id)
                setRetenus([])
                lancer(true, ids)
              }}
            >
              Les supprimer quand même
            </button>
          </Callout>
        </div>
      )}
      {erreur && (
        <div className="mt-3">
          <Callout tone="danger">{erreur}</Callout>
        </div>
      )}

      {dossiers.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          <label className="flex items-center gap-1.5 font-medium text-ink-700">
            <input
              type="checkbox"
              checked={tout}
              onChange={() => setCoches(tout ? new Set() : new Set(dossiers.map((d) => d.id)))}
            />
            Tout
          </label>
          {provenances.slice(0, 6).map(([dom, n]) => (
            <button
              key={dom}
              type="button"
              className="rounded-full border border-ink-200 px-2 py-0.5 text-ink-600 hover:border-ink-300"
              onClick={() =>
                setCoches((s) => {
                  const nouv = new Set(s)
                  dossiers.filter((d) => d.domaine === dom).forEach((d) => nouv.add(d.id))
                  return nouv
                })
              }
              title={`Cocher tous les dossiers venus de ${dom}`}
            >
              {dom} ({n})
            </button>
          ))}
          {selection.length > 0 && (
            <button
              type="button"
              className="ml-auto rounded-lg bg-red-700 px-3 py-1 font-medium text-white hover:bg-red-800"
              onClick={() => setConfirmation(true)}
            >
              Supprimer {selection.length} dossier(s)…
            </button>
          )}
        </div>
      )}

      <ul className="mt-2 max-h-[32rem] divide-y divide-ink-100 overflow-y-auto">
        {dossiers.map((c) => (
          <li key={c.id} className="flex gap-2 py-3">
            <input
              type="checkbox"
              className="mt-1"
              aria-label={`Sélectionner ${c.nom}`}
              checked={coches.has(c.id)}
              onChange={() => basculer(c.id)}
            />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-sm font-medium text-ink-900">
                  {c.nom.toUpperCase()} {c.prenom}
                </span>
                <span className="text-xs text-ink-500">
                  {SOURCES[c.source] ?? c.source} · reçue le {formatDate(c.recue_le, 'fr')}
                </span>
              </div>
              {(c.email || c.objet) && (
                <p className="mt-0.5 truncate text-xs text-ink-500" title={c.objet ?? undefined}>
                  {[c.email, c.objet].filter(Boolean).join(' · ')}
                </p>
              )}
              <div className="mt-2 flex flex-wrap gap-1.5">
                {c.pieces.length === 0 && (
                  <span className="text-xs text-ink-400">Aucune pièce jointe exploitable</span>
                )}
                {c.pieces.map((p) =>
                  p.disponible ? (
                    <button
                      key={p.id}
                      type="button"
                      className="rounded-md border border-ink-200 px-2 py-1 text-xs text-ink-700 hover:border-brand-300 hover:text-brand-800"
                      onClick={() => void ouvrir(c.id, p.id)}
                    >
                      {p.nom_fichier}
                    </button>
                  ) : (
                    <span key={p.id} className="rounded-md border border-ink-100 px-2 py-1 text-xs text-ink-400">
                      {p.nom_fichier} (purgé)
                    </span>
                  ),
                )}
              </div>
              <div className="mt-2 max-w-xl">
                <RattacherPoste
                  candidatureId={c.id}
                  onRattache={(intitule, posteId) =>
                    setCompteRendu({
                      texte: `${c.nom.toUpperCase()} ${c.prenom} est rangé(e) sous « ${intitule} ».`,
                      posteId,
                    })
                  }
                />
              </div>
            </div>
          </li>
        ))}
      </ul>

      {confirmation && (
        <Modal open title={`Supprimer ${selection.length} dossier(s)`} onClose={() => setConfirmation(false)}>
          <div className="space-y-3 text-sm">
            <p className="text-ink-600">
              Les dossiers, leurs pièces et leur notation disparaissent ; le journal garde nom,
              pièces et motif. Les messages restent dans la boîte Microsoft, et le relevé ne les
              réimportera pas.
            </p>
            <label className="block">
              <span className="text-xs font-medium text-ink-700">Motif (journalisé)</span>
              <input className="input mt-1" value={motif} onChange={(e) => setMotif(e.target.value)} />
            </label>
            {adresses.size > 0 && (
              <label className="flex items-start gap-2">
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={ignorerExpediteurs}
                  onChange={(e) => setIgnorerExpediteurs(e.target.checked)}
                />
                <span>
                  Ignorer aussi ces {adresses.size} expéditeur(s) à l&apos;avenir
                  <span className="block text-xs text-ink-500">
                    Le relevé n&apos;en tirera plus de dossier. Réversible dans la boîte,
                    « Expéditeurs ignorés ».
                  </span>
                </span>
              </label>
            )}
            <p className="text-xs text-ink-500">
              Vous aurez dix secondes pour annuler. Un dossier passé en entretien, écrit ou
              présélectionné est gardé et signalé.
            </p>
          </div>
          <div className="mt-5 flex justify-end gap-2">
            <button type="button" className="btn-ghost" onClick={() => setConfirmation(false)}>
              Annuler
            </button>
            <button
              type="button"
              className="rounded-lg bg-red-700 px-4 py-2 text-sm font-medium text-white hover:bg-red-800 disabled:opacity-50"
              disabled={motif.trim().length < 3}
              onClick={() => lancer()}
            >
              Supprimer
            </button>
          </div>
        </Modal>
      )}
      {annulable.bandeau}
    </section>
  )
}
