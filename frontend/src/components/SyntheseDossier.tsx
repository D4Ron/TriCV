import type { SyntheseDossier as Synthese } from '@/types'

/**
 * Qui est cette personne, ce qui se remarque, ce qu'il faut vérifier.
 *
 * Tout vient de ce qui a déjà été lu : rien n'est inventé, et « à vérifier » dit
 * où regarder, pas quoi décider.
 */
export default function SyntheseDossier({ synthese }: { synthese: Synthese | null | undefined }) {
  if (!synthese || (!synthese.profil && !synthese.notes.length && !synthese.a_verifier.length)) {
    return null
  }

  return (
    <section className="rounded-lg border border-ink-200 bg-white p-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">En bref</h3>
      {synthese.profil && <p className="mt-1.5 text-sm text-ink-900">{synthese.profil}</p>}
      {synthese.notes.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-1">
          {synthese.notes.map((note) => (
            <li key={note} className="rounded-full bg-ink-100 px-2 py-0.5 text-xs text-ink-700">
              {note}
            </li>
          ))}
        </ul>
      )}
      {synthese.lecteur && (
        <p className="mt-2 text-xs text-ink-500">
          Lu par {synthese.lecteur}
          {synthese.remarques ? ` : ${synthese.remarques}` : '.'}
        </p>
      )}
      {synthese.a_verifier.length > 0 && (
        <div className="mt-2.5 border-t border-ink-100 pt-2">
          <p className="text-xs font-medium text-ink-700">À vérifier</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-ink-600">
            {synthese.a_verifier.map((point) => (
              <li key={point}>{point}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
