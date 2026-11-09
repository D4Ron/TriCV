import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { recrutementApi } from '@/lib/api'
import { Spinner } from '@/components/ui'
import type { Candidature, LigneNotation } from '@/types'

/**
 * Les lignes de la note, chacune corrigeable par qui a lu le document.
 *
 * Le calcul propose, le recruteur décide : une correction garde la valeur
 * calculée à côté, dit pourquoi, et se défait d'un clic. Le total, la catégorie
 * et le seuil suivent côté serveur.
 */

const MOTIFS_RAPIDES = ['Vérifié sur le document', 'Erreur de lecture', 'Équivalence acceptée']

function nombre(valeur: string): number | null {
  const n = Number(valeur.replace(',', '.'))
  return valeur.trim() === '' || Number.isNaN(n) ? null : n
}

function Ligne({
  candidatureId,
  ligne,
  onFait,
}: {
  candidatureId: string
  ligne: LigneNotation
  onFait: () => void
}) {
  const [ouvert, setOuvert] = useState(false)
  const [points, setPoints] = useState(String(ligne.points))
  const [motif, setMotif] = useState(ligne.ajustement_motif ?? '')
  const [erreur, setErreur] = useState<string | null>(null)
  const ajustee = ligne.points_calcules !== null && ligne.points_calcules !== undefined

  const enregistrer = useMutation({
    mutationFn: (p: { points: number | null; motif: string }) =>
      recrutementApi.ajusterLigne(candidatureId, ligne.code, p.points, p.motif),
    onSuccess: () => {
      setOuvert(false)
      setErreur(null)
      onFait()
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Correction refusée'),
  })

  const valeur = nombre(points)
  const horsBornes = valeur === null || valeur < 0 || valeur > ligne.points_max
  const id = `ligne-${candidatureId}-${ligne.code}`

  return (
    <li className="rounded-lg bg-ink-50 px-3 py-2">
      <div className="flex items-baseline gap-2">
        <p className="min-w-0 flex-1 text-sm font-medium text-ink-800">{ligne.libelle}</p>
        <span className="text-sm font-semibold tabular-nums text-ink-900">
          {ligne.points}
          <span className="text-ink-400">/{ligne.points_max}</span>
        </span>
        {!ouvert && (
          <button
            type="button"
            className="text-xs font-medium text-ink-600 underline hover:text-ink-900"
            onClick={() => {
              setPoints(String(ligne.points))
              setMotif(ligne.ajustement_motif ?? '')
              setOuvert(true)
            }}
          >
            Corriger
          </button>
        )}
      </div>
      {ligne.detail && <p className="mt-0.5 text-xs text-ink-500">{ligne.detail}</p>}
      {ajustee && !ouvert && (
        <p className="mt-0.5 text-xs text-amber-800">
          Corrigé (le système donnait {ligne.points_calcules}) : {ligne.ajustement_motif}.{' '}
          <button
            type="button"
            className="font-medium underline"
            disabled={enregistrer.isPending}
            onClick={() => enregistrer.mutate({ points: null, motif: '' })}
          >
            Revenir au calcul
          </button>
        </p>
      )}

      {ouvert && (
        <div className="mt-2 space-y-1.5">
          <div className="flex items-center gap-1.5">
            <label className="text-xs text-ink-600" htmlFor={id}>
              Points
            </label>
            <input
              id={id}
              className="input w-20 py-1 text-sm"
              inputMode="decimal"
              value={points}
              autoFocus
              onChange={(e) => setPoints(e.target.value)}
            />
            <span className="text-xs text-ink-500">sur {ligne.points_max}</span>
          </div>
          <input
            className="input py-1 text-sm"
            aria-label={`Motif de la correction : ${ligne.libelle}`}
            placeholder="Pourquoi cette note ?"
            value={motif}
            onChange={(e) => setMotif(e.target.value)}
          />
          <div className="flex flex-wrap gap-1">
            {MOTIFS_RAPIDES.map((m) => (
              <button
                key={m}
                type="button"
                className="rounded-full border border-ink-200 bg-white px-2 py-0.5 text-xs text-ink-600 hover:border-ink-400"
                onClick={() => setMotif(m)}
              >
                {m}
              </button>
            ))}
          </div>
          {erreur && <p className="text-xs text-red-700">{erreur}</p>}
          {/* Le bouton grisé sans un mot laissait chercher ce qui manquait. */}
          {!erreur && points.trim() !== '' && horsBornes && (
            <p className="text-xs text-red-700">Entre 0 et {ligne.points_max} points.</p>
          )}
          {!erreur && !horsBornes && !motif.trim() && (
            <p className="text-xs text-ink-500">Écrivez pourquoi : la correction est relue et peut être contestée.</p>
          )}
          <div className="flex gap-1.5">
            <button
              type="button"
              className="btn-primary px-2.5 py-1 text-xs"
              disabled={enregistrer.isPending || horsBornes || !motif.trim()}
              onClick={() => enregistrer.mutate({ points: valeur, motif: motif.trim() })}
            >
              {enregistrer.isPending && <Spinner />}
              Enregistrer
            </button>
            <button type="button" className="btn-ghost px-2.5 py-1 text-xs" onClick={() => setOuvert(false)}>
              Annuler
            </button>
          </div>
        </div>
      )}
    </li>
  )
}

/** La note entière, quand c'est le total qu'on veut poser plutôt qu'une ligne. */
export function NoteGlobale({ candidature, onFait }: { candidature: Candidature; onFait: () => void }) {
  const n = candidature.notation
  const [ouvert, setOuvert] = useState(false)
  const [note, setNote] = useState(n?.note_manuelle === null ? '' : String(n?.note_manuelle ?? ''))
  const [motif, setMotif] = useState(n?.note_manuelle_motif ?? '')
  const [erreur, setErreur] = useState<string | null>(null)
  const enregistrer = useMutation({
    mutationFn: (p: { note: number | null; motif: string }) =>
      recrutementApi.noteManuelle(candidature.id, p.note, p.motif),
    onSuccess: () => {
      setOuvert(false)
      setErreur(null)
      onFait()
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Note refusée'),
  })
  if (!n) return null
  const valeur = nombre(note)
  const posee = n.note_manuelle !== null

  return (
    <div className="mt-2 text-xs text-ink-600">
      {posee && !ouvert && (
        <p className="text-amber-800">
          Note totale posée à la main : {n.note_manuelle}/{n.total_max} (lignes : {n.total}) —{' '}
          {n.note_manuelle_motif}.{' '}
          <button
            type="button"
            className="font-medium underline"
            disabled={enregistrer.isPending}
            onClick={() => enregistrer.mutate({ note: null, motif: '' })}
          >
            Retirer
          </button>
        </p>
      )}
      {!ouvert && !posee && (
        <button type="button" className="underline hover:text-ink-900" onClick={() => setOuvert(true)}>
          Poser la note totale à la main
        </button>
      )}
      {ouvert && (
        <div className="mt-1 space-y-1.5">
          <div className="flex items-center gap-1.5">
            <input
              className="input w-20 py-1 text-sm"
              inputMode="decimal"
              aria-label="Note totale"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
            <span>sur {n.total_max}</span>
          </div>
          <input
            className="input py-1 text-sm"
            aria-label="Motif de la note totale"
            placeholder="Pourquoi cette note ?"
            value={motif}
            onChange={(e) => setMotif(e.target.value)}
          />
          {erreur && <p className="text-red-700">{erreur}</p>}
          <div className="flex gap-1.5">
            <button
              type="button"
              className="btn-primary px-2.5 py-1 text-xs"
              disabled={
                enregistrer.isPending || valeur === null || valeur > n.total_max || !motif.trim()
              }
              onClick={() => enregistrer.mutate({ note: valeur, motif: motif.trim() })}
            >
              Enregistrer
            </button>
            <button type="button" className="btn-ghost px-2.5 py-1 text-xs" onClick={() => setOuvert(false)}>
              Annuler
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default function LignesDeNote({
  candidature,
  garder,
  onFait,
}: {
  candidature: Candidature
  /** Pour ne montrer que les lignes qu'un document concerne. */
  garder?: (code: string) => boolean
  onFait: () => void
}) {
  const lignes = (candidature.notation?.lignes ?? []).filter((l) => !garder || garder(l.code))
  if (lignes.length === 0) return null
  return (
    <ul className="space-y-1.5">
      {lignes.map((ligne) => (
        <Ligne key={ligne.code} candidatureId={candidature.id} ligne={ligne} onFait={onFait} />
      ))}
    </ul>
  )
}
