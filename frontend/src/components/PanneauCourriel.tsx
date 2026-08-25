import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { recrutementApi } from '@/lib/api'
import { Callout, Modal, Spinner } from '@/components/ui'

/**
 * Relevé de la boîte de candidatures.
 *
 * Trois gestes, dans cet ordre : tester la connexion, voir ce que le relevé
 * ferait, puis relever. Le premier branchement d'une boîte réelle réserve
 * toujours des surprises — encodages, pièces jointes inattendues, réponses
 * automatiques — et il vaut mieux les découvrir sur un aperçu que dans la
 * grille. Masqué tant qu'aucune boîte n'est configurée : un bouton qui ne peut
 * qu'échouer n'aide personne.
 */

const LIBELLE_ACTION: Record<string, string> = {
  creerait_une_candidature: 'Créerait une candidature',
  non_rattache: "Aucune référence d'avis reconnue",
  deja_recu: 'Déjà reçu',
  aucune_piece_exploitable: 'Aucune pièce lisible',
}

const TON_ACTION: Record<string, string> = {
  creerait_une_candidature: 'bg-emerald-100 text-emerald-800',
  non_rattache: 'bg-amber-100 text-amber-800',
  deja_recu: 'bg-ink-100 text-ink-600',
  aucune_piece_exploitable: 'bg-amber-100 text-amber-800',
}

type Apercu = Awaited<ReturnType<typeof recrutementApi.apercuCourriel>>

export default function PanneauCourriel() {
  const queryClient = useQueryClient()
  const [message, setMessage] = useState<string | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  const [apercu, setApercu] = useState<Apercu | null>(null)

  const etat = useQuery({ queryKey: ['courriel'], queryFn: recrutementApi.etatCourriel })

  const echec = (e: unknown) => {
    setMessage(null)
    setErreur(e instanceof Error ? e.message : 'Action impossible')
  }

  const tester = useMutation({
    mutationFn: recrutementApi.testerCourriel,
    onSuccess: (r) => {
      setErreur(null)
      setMessage(
        `Connexion établie à ${r.boite} (${r.dossier}) — ${r.messages} message(s), ` +
          `dont ${r.non_lus} non lu(s).`,
      )
    },
    onError: echec,
  })

  const voir = useMutation({
    mutationFn: recrutementApi.apercuCourriel,
    onSuccess: (r) => {
      setErreur(null)
      setMessage(null)
      setApercu(r)
    },
    onError: echec,
  })

  const relever = useMutation({
    mutationFn: recrutementApi.releverCourriel,
    onSuccess: (r) => {
      const parts = [`${r.crees} candidature(s) créée(s)`]
      if (r.ignores) parts.push(`${r.ignores} déjà reçue(s)`)
      if (r.non_rattaches.length) parts.push(`${r.non_rattaches.length} sans référence`)
      if (r.sans_piece.length) parts.push(`${r.sans_piece.length} sans pièce jointe`)
      setErreur(null)
      setApercu(null)
      setMessage(parts.join(' · '))
      void queryClient.invalidateQueries({ queryKey: ['mandats'] })
      void queryClient.invalidateQueries({ queryKey: ['grille'] })
    },
    onError: echec,
  })

  // Boîte non configurée ou relevé désactivé : le panneau disparaît plutôt
  // que d'offrir des boutons qui refuseraient. Tout se règle dans
  // Paramètres › Boîte de candidatures ; le dépôt manuel reste disponible.
  if (!etat.data?.actif) return null

  const enCours = tester.isPending || voir.isPending || relever.isPending

  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        {message && <span className="text-xs text-ink-600">{message}</span>}
        <button
          type="button"
          className="btn-ghost px-2 py-1 text-xs"
          disabled={enCours}
          onClick={() => tester.mutate()}
          title={`Boîte : ${etat.data.boite}`}
        >
          {tester.isPending && <Spinner />}
          Tester
        </button>
        <button
          type="button"
          className="btn-ghost px-2 py-1 text-xs"
          disabled={enCours}
          onClick={() => voir.mutate()}
        >
          {voir.isPending && <Spinner />}
          Aperçu
        </button>
        <button
          type="button"
          className="btn-ghost"
          disabled={enCours}
          onClick={() => relever.mutate()}
        >
          {relever.isPending && <Spinner />}
          Relever la boîte
        </button>
      </div>

      {erreur && (
        <Modal open title="Boîte inaccessible" onClose={() => setErreur(null)}>
          <Callout tone="danger">{erreur}</Callout>
          <div className="mt-4 flex justify-end">
            <button type="button" className="btn-ghost" onClick={() => setErreur(null)}>
              Fermer
            </button>
          </div>
        </Modal>
      )}

      {apercu && (
        <Modal
          open
          title={`Aperçu du relevé — ${apercu.messages} message(s)`}
          onClose={() => setApercu(null)}
        >
          <p className="mb-3 text-sm text-ink-600">
            Rien n'a été écrit. Voici ce que le relevé ferait de chaque message.
          </p>

          {apercu.messages === 0 && (
            <Callout tone="info">Aucun message non lu dans la boîte.</Callout>
          )}

          <div className="max-h-[26rem] space-y-2 overflow-y-auto">
            {apercu.details.map((m) => (
              <div key={m.sujet + m.recu_le} className="rounded-lg border border-ink-200 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={`badge ${TON_ACTION[m.action] ?? 'bg-ink-100 text-ink-700'}`}
                  >
                    {LIBELLE_ACTION[m.action] ?? m.action}
                  </span>
                  {m.poste && <span className="text-xs text-ink-600">→ {m.poste}</span>}
                </div>
                <p className="mt-1.5 truncate text-sm font-medium text-ink-900">{m.sujet}</p>
                <p className="truncate text-xs text-ink-500">
                  {m.expediteur} · nom deviné : {m.nom_devine || '—'}
                </p>
                {m.pieces.length > 0 ? (
                  <ul className="mt-1.5 space-y-0.5 text-xs">
                    {m.pieces.map((p) => (
                      <li key={p.nom} className={p.retenue ? 'text-ink-700' : 'text-ink-400'}>
                        {p.retenue ? '✓' : '✕'} {p.nom} · {Math.round(p.octets / 1024)} Ko ·{' '}
                        {p.type}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-1.5 text-xs text-ink-400">Aucune pièce jointe.</p>
                )}
              </div>
            ))}
          </div>

          <div className="mt-4 flex justify-end gap-2">
            <button type="button" className="btn-ghost" onClick={() => setApercu(null)}>
              Fermer
            </button>
            <button
              type="button"
              className="btn-primary"
              disabled={enCours}
              onClick={() => relever.mutate()}
            >
              {relever.isPending && <Spinner />}
              Relever maintenant
            </button>
          </div>
        </Modal>
      )}
    </>
  )
}
