import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { confianceApi, type VoieConfiance } from '@/lib/api'
import { Callout, EmptyState, Spinner } from '@/components/ui'

/**
 * Les dossiers à vérifier, rangés par ce qu'ils demandent vraiment.
 *
 * Relire seize dossiers pour en corriger trois, c'était le travail que la
 * plateforme devait épargner. Chaque dossier porte maintenant une voie :
 * « À relire » (un signe d'erreur grave), « Une question » (un ou deux points
 * précis), ou « Vérifié automatiquement ». Un dossier sûr sur dix remonte au
 * hasard pour contrôle, et aucun motif n'élimine personne sans un humain.
 */

interface Item {
  id: string
  nom: string
  prenom: string | null
  note: number | null
  total_max: number | null
  motifs: unknown[]
  doublons: number
}

const VOIES: Array<{ cle: VoieConfiance; libelle: string; ton: string; aide: string }> = [
  {
    cle: 'RELIRE',
    libelle: 'À relire',
    ton: 'bg-red-50 text-red-800 border-red-200',
    aide: 'Un signe d’erreur de lecture grave : rouvrir le dossier entier.',
  },
  {
    cle: 'QUESTION',
    libelle: 'Une question',
    ton: 'bg-amber-50 text-amber-800 border-amber-200',
    aide: 'Un ou deux points précis à trancher ; le reste est sûr.',
  },
  {
    cle: 'SUR',
    libelle: 'Vérifiés automatiquement',
    ton: 'bg-emerald-50 text-emerald-800 border-emerald-200',
    aide: 'Rien ne signale d’erreur ni d’enjeu : à confirmer d’un coup.',
  },
  {
    cle: 'ECARTE',
    libelle: 'Écartés nets',
    ton: 'bg-ink-100 text-ink-700 border-ink-300',
    aide: 'Un motif net (loin du seuil, ou un fait simple) et aucun doute sur la lecture : l’élimination reste à confirmer.',
  },
]
const ORDRE: Record<VoieConfiance, number> = { RELIRE: 0, QUESTION: 1, SUR: 2, ECARTE: 3, FAIT: 4 }

export default function VoiesDeRelecture({
  posteId,
  items,
  onOuvrir,
}: {
  posteId: string
  items: Item[]
  onOuvrir: (id: string) => void
}) {
  const queryClient = useQueryClient()
  const [voie, setVoie] = useState<VoieConfiance | 'TOUTES'>('TOUTES')
  const confiance = useQuery({
    queryKey: ['confiance', posteId],
    queryFn: () => confianceApi.duPoste(posteId),
  })

  const confirmer = useMutation({
    mutationFn: (v: 'SUR' | 'ECARTE') => confianceApi.confirmerVoie(posteId, v),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['confiance', posteId] })
      void queryClient.invalidateQueries({ queryKey: ['candidatures', posteId] })
      void queryClient.invalidateQueries({ queryKey: ['grille', posteId] })
    },
  })

  const avis = confiance.data?.dossiers ?? {}
  const voieDe = (id: string): VoieConfiance => avis[id]?.voie ?? 'QUESTION'
  const tries = [...items].sort((a, b) => ORDRE[voieDe(a.id)] - ORDRE[voieDe(b.id)])
  const visibles = voie === 'TOUTES' ? tries : tries.filter((i) => voieDe(i.id) === voie)
  const surs = items.filter((i) => voieDe(i.id) === 'SUR').length
  const ecartes = items.filter((i) => voieDe(i.id) === 'ECARTE').length

  if (items.length === 0) {
    return <EmptyState title="Rien à vérifier" hint="Tous les dossiers ont été relus." />
  }

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          aria-pressed={voie === 'TOUTES'}
          onClick={() => setVoie('TOUTES')}
          className={`rounded-full border px-3 py-1 text-xs font-medium ${
            voie === 'TOUTES' ? 'border-brand-400 bg-brand-50 text-brand-800' : 'border-ink-200 text-ink-600'
          }`}
        >
          Tous ({items.length})
        </button>
        {VOIES.map((v) => (
          <button
            key={v.cle}
            type="button"
            title={v.aide}
            aria-pressed={voie === v.cle}
            onClick={() => setVoie(v.cle)}
            className={`rounded-full border px-3 py-1 text-xs font-medium ${
              voie === v.cle ? v.ton : 'border-ink-200 text-ink-600'
            }`}
          >
            {v.libelle} ({items.filter((i) => voieDe(i.id) === v.cle).length})
          </button>
        ))}
        {confiance.isLoading && <Spinner />}
        <div className="ml-auto flex flex-wrap gap-1.5">
          <button
            type="button"
            className="btn-primary px-3 py-1.5 text-xs"
            disabled={surs === 0 || confirmer.isPending}
            onClick={() => {
              if (
                window.confirm(
                  `Confirmer les données des ${surs} dossier(s) vérifiés automatiquement ? ` +
                    'Les dossiers à relire, avec une question ou écartés ne sont pas concernés.',
                )
              )
                confirmer.mutate('SUR')
            }}
          >
            {confirmer.isPending && <Spinner />}
            Confirmer les {surs} dossier(s) sûrs
          </button>
          <button
            type="button"
            className="btn-ghost px-3 py-1.5 text-xs"
            disabled={ecartes === 0 || confirmer.isPending}
            onClick={() => {
              if (
                window.confirm(
                  `Confirmer l'élimination de ${ecartes} dossier(s) écartés par un motif net ? ` +
                    'Chacun reste consultable, et un motif se lève à tout moment depuis le dossier.',
                )
              )
                confirmer.mutate('ECARTE')
            }}
          >
            Confirmer les {ecartes} élimination(s) nette(s)
          </button>
        </div>
      </div>
      {confirmer.data && (
        <div className="mb-3">
          <Callout tone="success">{confirmer.data.confirmes} dossier(s) confirmé(s).</Callout>
        </div>
      )}
      {confirmer.isError && (
        <div className="mb-3">
          <Callout tone="danger">
            {confirmer.error instanceof Error ? confirmer.error.message : 'Confirmation impossible.'}
          </Callout>
        </div>
      )}

      <div className="card divide-y divide-ink-100">
        {visibles.map((item) => {
          const a = avis[item.id]
          const v = VOIES.find((x) => x.cle === (a?.voie ?? 'QUESTION'))
          const signaux = a?.signaux ?? []
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => onOuvrir(item.id)}
              className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-ink-50"
            >
              <div className="min-w-0 flex-1">
                <p className="flex items-center gap-2 text-sm font-medium text-ink-900">
                  <span className="truncate">
                    {item.nom.toUpperCase()} {item.prenom}
                  </span>
                  {v && (
                    <span className={`shrink-0 rounded border px-1.5 py-0.5 text-[11px] font-medium ${v.ton}`}>
                      {a?.controle ? 'Contrôle au hasard' : v.libelle}
                    </span>
                  )}
                  {item.doublons > 0 && (
                    <span className="shrink-0 rounded bg-amber-100 px-1.5 py-0.5 text-[11px] font-medium text-amber-800">
                      {item.doublons} doublon(s)
                    </span>
                  )}
                </p>
                {signaux.length > 0 ? (
                  <ul className="mt-0.5 space-y-0.5">
                    {signaux.slice(0, 3).map((s) => (
                      <li key={s.code + s.texte} className="truncate text-xs text-ink-600">
                        • {s.texte}
                      </li>
                    ))}
                    {signaux.length > 3 && (
                      <li className="text-xs text-ink-400">+ {signaux.length - 3} autre(s) point(s)</li>
                    )}
                  </ul>
                ) : (
                  <p className="text-xs text-ink-500">Rien à signaler.</p>
                )}
              </div>
              <span className="text-sm font-semibold tabular-nums text-ink-700">
                {item.note ?? '—'}
                <span className="text-ink-400">/{item.total_max ?? ''}</span>
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
