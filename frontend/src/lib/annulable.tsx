import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Un geste qu'on peut annuler pendant quelques secondes.
 *
 * Supprimer un dossier, lever un motif, en déplacer un : ces gestes partent sur
 * un clic, et un clic se trompe de ligne. Plutôt qu'une fenêtre de plus — qu'on
 * finit par valider sans la lire —, le geste attend dix secondes avec un bouton
 * « Annuler » bien visible, puis part.
 *
 * Quitter la page pendant l'attente l'exécute : c'est ce qui était voulu. Fermer
 * l'onglet, en revanche, le perdrait — le navigateur le demande alors.
 */
export function useAnnulable(delaiSecondes = 10) {
  const [enAttente, setEnAttente] = useState<{ libelle: string; reste: number } | null>(null)
  const action = useRef<(() => unknown) | null>(null)
  const minuterie = useRef<number | null>(null)

  const arreter = () => {
    if (minuterie.current !== null) window.clearInterval(minuterie.current)
    minuterie.current = null
  }

  const executer = useCallback(() => {
    arreter()
    const a = action.current
    action.current = null
    setEnAttente(null)
    if (a) void a()
  }, [])

  const annuler = useCallback(() => {
    arreter()
    action.current = null
    setEnAttente(null)
  }, [])

  const programmer = useCallback(
    (libelle: string, a: () => unknown) => {
      // Un second geste exécute le premier sans attendre : on n'empile pas.
      if (action.current) executer()
      action.current = a
      setEnAttente({ libelle, reste: delaiSecondes })
      minuterie.current = window.setInterval(() => {
        setEnAttente((e) => {
          if (!e) return e
          if (e.reste <= 1) {
            window.setTimeout(executer, 0)
            return e
          }
          return { ...e, reste: e.reste - 1 }
        })
      }, 1000)
    },
    [delaiSecondes, executer],
  )

  useEffect(() => {
    const avant = (e: BeforeUnloadEvent) => {
      if (action.current) e.preventDefault()
    }
    window.addEventListener('beforeunload', avant)
    return () => {
      window.removeEventListener('beforeunload', avant)
      // Démonté pendant l'attente (changement de page) : le geste part.
      if (action.current) executer()
    }
  }, [executer])

  const bandeau = enAttente ? (
    <div
      role="status"
      className="fixed inset-x-0 bottom-4 z-[60] mx-auto flex w-fit max-w-[calc(100%-2rem)] items-center gap-3 rounded-lg bg-ink-900 px-4 py-2.5 text-sm text-white shadow-lg"
    >
      <span className="min-w-0 truncate">{enAttente.libelle}</span>
      <span className="shrink-0 tabular-nums text-ink-300">{enAttente.reste} s</span>
      <button
        type="button"
        className="shrink-0 rounded-md bg-white/10 px-2.5 py-1 font-medium hover:bg-white/20"
        onClick={annuler}
      >
        Annuler
      </button>
      <button
        type="button"
        className="shrink-0 text-xs text-ink-300 underline hover:text-white"
        onClick={executer}
      >
        Maintenant
      </button>
    </div>
  ) : null

  return { programmer, annuler, enAttente: enAttente !== null, bandeau }
}
