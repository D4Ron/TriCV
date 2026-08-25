import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { recrutementApi } from '@/lib/api'
import { Callout, Modal, Spinner } from '@/components/ui'

/**
 * Archiver, et rien d'autre.
 *
 * La suppression définitive n'est pas proposée ici : elle passe par la page
 * Archives. Une action irréversible n'a pas sa place à portée de clic dans une
 * liste de travail, et l'archivage — réversible, sans perte — couvre le besoin
 * courant de sortir un dossier terminé de la vue.
 */
export default function ActionsMandat({
  mandatId,
  archive,
  onChange,
}: {
  mandatId: string
  archive: boolean
  onChange: () => void
}) {
  const [erreur, setErreur] = useState<string | null>(null)

  const basculer = useMutation({
    mutationFn: () =>
      archive
        ? recrutementApi.desarchiverMandat(mandatId)
        : recrutementApi.archiverMandat(mandatId),
    onSuccess: onChange,
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Action impossible'),
  })

  return (
    <>
      <button
        type="button"
        className="btn-ghost px-2 py-1 text-xs"
        disabled={basculer.isPending}
        onClick={() => basculer.mutate()}
        title={
          archive
            ? 'Remettre ce mandat dans les listes de travail'
            : "Sort des listes sans rien effacer. La suppression se fait ensuite depuis les Archives."
        }
      >
        {basculer.isPending && <Spinner />}
        {archive ? 'Restaurer' : 'Archiver'}
      </button>

      {erreur && (
        <Modal open title="Action impossible" onClose={() => setErreur(null)}>
          <Callout tone="danger">{erreur}</Callout>
          <div className="mt-4 flex justify-end">
            <button type="button" className="btn-ghost" onClick={() => setErreur(null)}>
              Fermer
            </button>
          </div>
        </Modal>
      )}
    </>
  )
}
