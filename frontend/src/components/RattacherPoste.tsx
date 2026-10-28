import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { dossiersApi } from '@/lib/api'
import { Spinner } from '@/components/ui'

/**
 * Ranger un dossier sous un poste.
 *
 * Sert à deux endroits : un dossier arrivé sans poste (un courriel dont l'objet
 * ne nommait aucun avis), et un dossier rangé sous le mauvais poste. Le
 * serveur le note aussitôt selon le poste choisi.
 */
export default function RattacherPoste({
  candidatureId,
  posteActuel,
  libelle = 'Rattacher',
  onRattache,
}: {
  candidatureId: string
  posteActuel?: string | null
  libelle?: string
  onRattache: (intitule: string, posteId: string) => void
}) {
  const queryClient = useQueryClient()
  const [posteId, setPosteId] = useState('')
  const postes = useQuery({ queryKey: ['postes-actifs'], queryFn: dossiersApi.postesActifs })

  const rattacher = useMutation({
    mutationFn: () => dossiersApi.rattacher(candidatureId, posteId),
    onSuccess: () => {
      const poste = postes.data?.find((p) => p.id === posteId)
      void queryClient.invalidateQueries({ queryKey: ['dossiers-sans-poste'] })
      void queryClient.invalidateQueries({ queryKey: ['grille'] })
      void queryClient.invalidateQueries({ queryKey: ['candidatures'] })
      void queryClient.invalidateQueries({ queryKey: ['vivier'] })
      onRattache(poste?.intitule ?? 'le poste', posteId)
      setPosteId('')
    },
  })

  const choix = (postes.data ?? []).filter((p) => p.id !== posteActuel)

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <select
          className="input min-w-0 flex-1 py-1.5 text-sm"
          value={posteId}
          aria-label="Poste"
          disabled={postes.isLoading || rattacher.isPending}
          onChange={(e) => setPosteId(e.target.value)}
        >
          <option value="">{postes.isLoading ? 'Chargement…' : 'Choisir un poste…'}</option>
          {choix.map((p) => (
            <option key={p.id} value={p.id}>
              {p.intitule}
              {p.client ? ` — ${p.client}` : ''}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="btn-secondary px-3 py-1.5 text-xs"
          disabled={!posteId || rattacher.isPending}
          onClick={() => rattacher.mutate()}
        >
          {rattacher.isPending && <Spinner />}
          {libelle}
        </button>
      </div>
      {rattacher.isError && (
        <p className="mt-1.5 text-xs text-red-700">
          {rattacher.error instanceof Error ? rattacher.error.message : 'Rattachement impossible.'}
        </p>
      )}
    </div>
  )
}
