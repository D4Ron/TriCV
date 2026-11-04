import { useEffect, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { recrutementApi } from '@/lib/api'
import { Callout } from '@/components/ui'
import type { EtatLectures, FournisseurIaEtat } from '@/types'

/**
 * Où en est la lecture des dossiers du poste, et quand elle finira.
 *
 * Le temps vient de la durée mesurée des dernières lectures et des limites que
 * le fournisseur annonce vraiment. Aucune offre gratuite ne publie son solde du
 * mois : l'écran le dit au lieu d'inventer un chiffre.
 */

export function dureeEnLettres(secondes: number): string {
  if (secondes < 60) return 'moins d’une minute'
  const minutes = Math.round(secondes / 60)
  if (minutes < 60) return `environ ${minutes} min`
  const heures = Math.floor(minutes / 60)
  const reste = minutes % 60
  return `environ ${heures} h${reste ? ` ${String(reste).padStart(2, '0')}` : ''}`
}

function heure(date: Date): string {
  return date.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
}

function milliers(n: number): string {
  return n >= 1000 ? `${Math.round(n / 1000)} k` : String(n)
}

function ligneFournisseur(f: FournisseurIaEtat): string {
  const morceaux: string[] = []
  if (!f.disponible) {
    morceaux.push(`au repos encore ${dureeEnLettres(f.repos_secondes).replace('environ ', '')}`)
  }
  if (f.requetes_limite !== null) {
    morceaux.push(
      `${f.requetes_restantes ?? '?'} requêtes sur ${f.requetes_limite} par ${f.periode_requetes}`,
    )
  }
  if (f.jetons_limite !== null) {
    morceaux.push(
      `${milliers(f.jetons_restants ?? 0)} jetons sur ${milliers(f.jetons_limite)} par ${f.periode_jetons}`,
    )
  }
  if (f.indicatif) {
    morceaux.push(
      `environ ${f.indicatif.par_minute} requêtes par minute et ${f.indicatif.par_jour} par jour (ordre de grandeur)`,
    )
  } else if (f.requetes_limite === null && f.jetons_limite === null) {
    morceaux.push(f.quota_lu ? 'ne communique pas son quota' : 'quota lu à son premier appel')
  }
  if (f.lectures_du_jour > 0) {
    morceaux.push(
      `${f.lectures_du_jour} lecture(s) aujourd’hui, ${milliers(f.jetons_du_jour)} jetons`,
    )
  }
  return `${f.nom} : ${morceaux.join(' · ')}`
}

function raison(e: EtatLectures, reprise: string | null): string {
  if (e.cause === 'attente' && reprise) {
    return `Quota épuisé : la lecture attend et reprendra seule vers ${reprise}.`
  }
  if (e.cause === 'quota') return 'Le rythme est fixé par le quota par minute du fournisseur.'
  if (e.mesures === 0) return 'Première estimation : elle s’affine après quelques dossiers.'
  return `Calculé sur la durée des ${e.mesures} dernières lectures.`
}

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

  if (restants === 0) {
    if (e.echecs === 0) return null
    return (
      <div className="mb-5">
        <Callout tone="warning">
          {e.echecs} dossier(s) n&apos;ont pas pu être lus
          {e.derniere_erreur ? ` : ${e.derniere_erreur}` : '.'}
        </Callout>
      </div>
    )
  }

  const reprise = e.reprise_le ? heure(new Date(`${e.reprise_le}Z`)) : null
  // Un serveur plus ancien que l'écran n'envoie pas tout : on fait sans.
  const secondes = e.secondes_restantes ?? 0
  const fournisseurs = e.fournisseurs ?? []
  const fin = heure(new Date(Date.now() + secondes * 1000))

  return (
    <div className="card mb-5 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <p className="text-sm font-medium text-ink-900">
          Lecture des dossiers : {e.faits + e.echecs} sur {e.total ?? e.faits + e.echecs + restants}
        </p>
        <p className="text-sm tabular-nums text-ink-700">
          {dureeEnLettres(secondes)} restantes · fin vers {fin}
        </p>
      </div>
      <div
        role="progressbar"
        aria-label="Avancement de la lecture"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={e.pourcentage ?? 0}
        className="mt-2 h-2 overflow-hidden rounded-full bg-ink-100"
      >
        <div
          className={`h-full rounded-full transition-[width] duration-500 ${
            e.cause === 'attente' ? 'bg-amber-500' : 'bg-ink-800'
          }`}
          style={{ width: `${Math.max(e.pourcentage ?? 0, 2)}%` }}
        />
      </div>
      <p className="mt-2 text-xs text-ink-600">
        {raison(e, reprise)} Vous pouvez quitter cette page, la lecture continue.{' '}
        <button
          type="button"
          className="font-medium underline"
          disabled={annuler.isPending}
          onClick={() => annuler.mutate()}
        >
          Annuler ce qui reste
        </button>
      </p>
      {fournisseurs.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-xs text-ink-500">
          {fournisseurs.map((f) => (
            <li key={f.nom}>{ligneFournisseur(f)}</li>
          ))}
        </ul>
      )}
      <p className="mt-1 text-xs text-ink-400">
        Aucun fournisseur gratuit ne publie son solde du mois : un quota épuisé en route allongerait
        ce temps, et la lecture reprendrait seule.
      </p>
    </div>
  )
}
