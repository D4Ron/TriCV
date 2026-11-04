import { useEffect, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { recrutementApi } from '@/lib/api'
import { Callout } from '@/components/ui'

/**
 * Où en est la lecture des dossiers du poste.
 *
 * Une lecture par l'IA peut durer : la file avance seule, attend le quota quand
 * il manque, et reprend après un redémarrage. On peut quitter la page.
 */
export default function SuiviDesLectures({ posteId }: { posteId: string }) {
  const queryClient = useQueryClient()
  const suivi = useQuery({
    queryKey: ['lectures', posteId],
    queryFn: () => recrutementApi.suivreLectures(posteId),
    refetchInterval: (q) => {
      const d = q.state.data
      return d && d.en_attente + d.en_cours > 0 ? 3000 : false
    },
  })
  const annuler = useMutation({
    mutationFn: () => recrutementApi.annulerLectures(posteId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['lectures', posteId] }),
  })

  // Chaque dossier lu change la grille : elle suit sans qu'on recharge.
  const faits = suivi.data?.faits ?? 0
  const dejaVus = useRef(faits)
  useEffect(() => {
    if (faits === dejaVus.current) return
    dejaVus.current = faits
    void queryClient.invalidateQueries({ queryKey: ['grille', posteId] })
    void queryClient.invalidateQueries({ queryKey: ['candidatures', posteId] })
  }, [faits, posteId, queryClient])

  const e = suivi.data
  if (!e) return null
  const restants = e.en_attente + e.en_cours
  if (restants === 0 && e.echecs === 0) return null

  const reprise = e.reprise_le
    ? new Date(`${e.reprise_le}Z`).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
    : null

  return (
    <div className="mb-5">
      <Callout tone={e.echecs > 0 && restants === 0 ? 'warning' : 'info'}>
        {restants > 0 && (
          <>
            Lecture des dossiers : {e.faits} sur {e.faits + restants + e.echecs}.{' '}
            {reprise
              ? `Quota d'IA épuisé : reprise automatique vers ${reprise}.`
              : 'Vous pouvez quitter cette page, la lecture continue.'}{' '}
            <button
              type="button"
              className="font-medium underline"
              disabled={annuler.isPending}
              onClick={() => annuler.mutate()}
            >
              Annuler ce qui reste
            </button>
          </>
        )}
        {restants === 0 && e.echecs > 0 && (
          <>
            {e.echecs} dossier(s) n&apos;ont pas pu être lus
            {e.derniere_erreur ? ` : ${e.derniere_erreur}` : '.'}
          </>
        )}
      </Callout>
    </div>
  )
}
