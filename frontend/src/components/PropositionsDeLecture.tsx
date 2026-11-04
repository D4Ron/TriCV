import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { recrutementApi } from '@/lib/api'
import { Spinner } from '@/components/ui'
import type { Candidature } from '@/types'

const FAMILLE: Record<string, string> = {
  experience: 'Expérience',
  diplome: 'Diplôme',
  langue: 'Langue',
  certification: 'Certification',
}

/**
 * Ce qu'une relecture voit autrement que ce qu'un humain a posé.
 *
 * Rien ici ne touche au dossier ni à la note avant d'être accepté, et ce qui est
 * écarté ne revient pas à la prochaine lecture.
 */
export default function PropositionsDeLecture({
  candidature,
  onFait,
}: {
  candidature: Candidature
  onFait: () => void
}) {
  const [erreur, setErreur] = useState<string | null>(null)
  const trancher = useMutation({
    mutationFn: (p: { ids: string[] | null; accepter: boolean }) =>
      recrutementApi.trancherPropositions(candidature.id, p.ids, p.accepter),
    onSuccess: () => {
      setErreur(null)
      onFait()
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Décision refusée'),
  })

  const propositions = candidature.candidat.propositions ?? []
  if (propositions.length === 0) return null

  return (
    <section className="rounded-lg border border-sky-200 bg-sky-50/60 p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-sky-900">
          Nouvelle lecture : {propositions.length} proposition(s)
        </h3>
        <div className="flex gap-2 text-xs">
          <button
            type="button"
            className="font-medium text-sky-900 underline"
            disabled={trancher.isPending}
            onClick={() => trancher.mutate({ ids: null, accepter: true })}
          >
            Tout accepter
          </button>
          <button
            type="button"
            className="text-ink-600 underline"
            disabled={trancher.isPending}
            onClick={() => trancher.mutate({ ids: null, accepter: false })}
          >
            Tout écarter
          </button>
        </div>
      </div>
      <p className="mt-1 text-xs text-ink-600">
        Ce qui a été confirmé ou saisi n&apos;a pas changé. Rien ne compte tant que vous
        n&apos;acceptez pas.
      </p>
      <ul className="mt-2 space-y-1.5">
        {propositions.map((p) => (
          <li key={p.id} className="rounded-md bg-white px-2.5 py-1.5 text-sm">
            <p className="text-ink-900">
              <span className="text-xs text-ink-500">
                {FAMILLE[p.famille] ?? p.famille} · {p.action === 'modifier' ? 'à modifier' : 'à ajouter'}
              </span>
              <br />
              {p.libelle}
            </p>
            {p.avant && <p className="text-xs text-ink-500">Aujourd&apos;hui : {p.avant}</p>}
            <div className="mt-1 flex gap-1.5">
              <button
                type="button"
                className="btn-secondary px-2 py-0.5 text-xs"
                disabled={trancher.isPending}
                onClick={() => trancher.mutate({ ids: [p.id], accepter: true })}
              >
                {trancher.isPending && <Spinner />}
                Accepter
              </button>
              <button
                type="button"
                className="btn-ghost px-2 py-0.5 text-xs"
                disabled={trancher.isPending}
                onClick={() => trancher.mutate({ ids: [p.id], accepter: false })}
              >
                Écarter
              </button>
            </div>
          </li>
        ))}
      </ul>
      {erreur && <p className="mt-1 text-xs text-red-700">{erreur}</p>}
    </section>
  )
}
