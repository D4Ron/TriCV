import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { dossiersApi, recrutementApi } from '@/lib/api'
import { Callout } from '@/components/ui'
import { formatDate } from '@/lib/format'
import RattacherPoste from '@/components/RattacherPoste'

/**
 * Les candidatures reçues sans poste, pièces en main.
 *
 * Surtout des courriels dont l'objet ne citait aucun avis : le candidat visait
 * sans doute un poste, mais rien ne permettait de dire lequel. Ils rejoignaient
 * le vivier sans que personne puisse ouvrir leurs pièces ni les ranger. Ici on
 * les lit, puis on les rattache — ou on les laisse au vivier.
 */
const SOURCES: Record<string, string> = {
  EMAIL: 'Courriel',
  FORMULAIRE: 'Formulaire du site',
  IMPORT_MANUEL: 'Déposé par les RH',
}

export default function DossiersSansPoste() {
  const liste = useQuery({ queryKey: ['dossiers-sans-poste'], queryFn: dossiersApi.sansPoste })
  const [compteRendu, setCompteRendu] = useState<{ texte: string; posteId: string } | null>(null)
  const [erreurPiece, setErreurPiece] = useState<string | null>(null)

  const ouvrir = async (candidatureId: string, pieceId: string) => {
    setErreurPiece(null)
    // Ouverte avant l'attente : un onglet ouvert après coup serait bloqué
    // comme fenêtre surgissante.
    const onglet = window.open('', '_blank')
    try {
      const url = await recrutementApi.pieceObjectUrl(candidatureId, pieceId)
      if (onglet) onglet.location.href = url
      else window.location.href = url
    } catch (e) {
      onglet?.close()
      setErreurPiece(e instanceof Error ? e.message : 'Pièce indisponible')
    }
  }

  if (!liste.data || (liste.data.length === 0 && !compteRendu)) return null

  return (
    <section className="card mb-5 p-4">
      <h2 className="text-sm font-semibold text-ink-900">
        Candidatures sans poste{' '}
        <span className="font-normal text-ink-400">({liste.data.length})</span>
      </h2>
      <p className="mt-1 text-xs text-ink-500">
        Reçues hors de tout avis — le plus souvent un courriel dont l&apos;objet ne nommait aucun
        poste. Ouvrez les pièces, puis rangez le dossier sous le poste visé : il y sera noté
        comme les autres. Laissé ici, il reste au vivier.
      </p>

      {compteRendu && (
        <div className="mt-3">
          <Callout tone="success">
            {compteRendu.texte}{' '}
            <Link to={`/postes/${compteRendu.posteId}`} className="font-medium underline">
              Ouvrir le poste
            </Link>
          </Callout>
        </div>
      )}
      {erreurPiece && (
        <div className="mt-3">
          <Callout tone="danger">{erreurPiece}</Callout>
        </div>
      )}

      <ul className="mt-3 divide-y divide-ink-100">
        {liste.data.map((c) => (
          <li key={c.id} className="py-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="text-sm font-medium text-ink-900">
                {c.nom.toUpperCase()} {c.prenom}
              </span>
              <span className="text-xs text-ink-500">
                {SOURCES[c.source] ?? c.source} · reçue le{' '}
                {formatDate(c.recue_le, 'fr')}
              </span>
            </div>
            {(c.email || c.objet) && (
              <p className="mt-0.5 truncate text-xs text-ink-500" title={c.objet ?? undefined}>
                {[c.email, c.objet].filter(Boolean).join(' · ')}
              </p>
            )}
            <div className="mt-2 flex flex-wrap gap-1.5">
              {c.pieces.length === 0 && (
                <span className="text-xs text-ink-400">Aucune pièce jointe exploitable</span>
              )}
              {c.pieces.map((p) =>
                p.disponible ? (
                  <button
                    key={p.id}
                    type="button"
                    className="rounded-md border border-ink-200 px-2 py-1 text-xs text-ink-700 hover:border-brand-300 hover:text-brand-800"
                    onClick={() => void ouvrir(c.id, p.id)}
                  >
                    {p.nom_fichier}
                  </button>
                ) : (
                  <span key={p.id} className="rounded-md border border-ink-100 px-2 py-1 text-xs text-ink-400">
                    {p.nom_fichier} (purgé)
                  </span>
                ),
              )}
            </div>
            <div className="mt-2 max-w-xl">
              <RattacherPoste
                candidatureId={c.id}
                onRattache={(intitule, posteId) =>
                  setCompteRendu({
                    texte: `${c.nom.toUpperCase()} ${c.prenom} est rangé(e) sous « ${intitule} ».`,
                    posteId,
                  })
                }
              />
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}
