import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { settingsApi } from '@/lib/api'
import { Callout, Spinner } from '@/components/ui'

/**
 * Le lecteur local : Ollama sur un poste du cabinet lit les dossiers à la place
 * du fournisseur. Le poste appelle la plateforme, jamais l'inverse.
 */
export default function LecteurLocal({ estAdmin }: { estAdmin: boolean }) {
  const queryClient = useQueryClient()
  const [cle, setCle] = useState<string | null>(null)
  const etat = useQuery({
    queryKey: ['lecteur'],
    queryFn: settingsApi.etatLecteur,
    refetchInterval: 15_000,
  })
  const rafraichir = () => void queryClient.invalidateQueries({ queryKey: ['lecteur'] })
  const creer = useMutation({
    mutationFn: settingsApi.creerCleLecteur,
    onSuccess: (r) => {
      setCle(r.cle)
      rafraichir()
    },
  })
  const retirer = useMutation({
    mutationFn: settingsApi.retirerCleLecteur,
    onSuccess: () => {
      setCle(null)
      rafraichir()
    },
  })
  const e = etat.data
  const adresse = window.location.origin

  return (
    <div className="mt-6 border-t border-ink-100 pt-5">
      <h2 className="text-sm font-semibold text-ink-900">Lecteur local</h2>
      <p className="mt-1 text-xs text-ink-500">
        Un modèle Ollama sur un poste du cabinet lit les dossiers : rien ne part à un fournisseur
        tant qu&apos;il tourne, et sans quota. Arrêté, le fournisseur choisi plus haut reprend.
      </p>
      <p className="mt-2 text-xs text-ink-700">
        {e?.actif
          ? `Connecté${e.modele ? ` : ${e.modele}` : ''}.`
          : e?.configure
            ? 'Clé créée, aucun lecteur connecté pour l’instant.'
            : 'Aucune clé : le lecteur local n’est pas en service.'}
      </p>

      {cle && (
        <div className="mt-3">
          <Callout tone="info">
            Copiez cette clé maintenant : elle ne sera plus affichée. Sur le poste, dans le dossier
            du projet :
            <code className="mt-1 block break-all rounded bg-white px-2 py-1 text-xs text-ink-900">
              python backend/tools/lecteur_local.py --url {adresse} --cle {cle}
            </code>
          </Callout>
        </div>
      )}

      {estAdmin && (
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            className="btn-ghost px-3 py-1.5 text-xs"
            disabled={creer.isPending}
            onClick={() => creer.mutate()}
          >
            {creer.isPending && <Spinner />}
            {e?.configure ? 'Remplacer la clé' : 'Créer une clé'}
          </button>
          {e?.configure && (
            <button
              type="button"
              className="btn-ghost px-3 py-1.5 text-xs"
              disabled={retirer.isPending}
              onClick={() => retirer.mutate()}
            >
              Retirer la clé
            </button>
          )}
        </div>
      )}
    </div>
  )
}
