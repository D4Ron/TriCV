import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { TYPES_GRILLE, recrutementApi, type TypeGrille } from '@/lib/api'
import { Callout, Modal, Spinner } from '@/components/ui'

/**
 * Quel document tableur exporter.
 *
 * Un seul bouton produisait un classeur de quatre onglets. Pratique en
 * interne, embarrassant à l'envoi : joindre le classement au client lui
 * transmettait aussi le tableau d'élimination et les observations du jury.
 * On choisit maintenant ce qu'on envoie, comme on choisit le type de rapport.
 *
 * Les feuilles sont produites par le même code dans les deux cas : un tableau
 * d'élimination exporté seul est mot pour mot celui du classeur complet.
 */
export default function ChoisirExportGrille({
  posteId,
  nombreEntretiens,
  onClose,
  onExporte,
}: {
  posteId: string
  nombreEntretiens: number
  onClose: () => void
  onExporte: (libelle: string) => void
}) {
  const [erreur, setErreur] = useState<string | null>(null)
  const [enCours, setEnCours] = useState<TypeGrille | null>(null)

  const exporter = useMutation({
    mutationFn: (type: TypeGrille) => recrutementApi.telechargerGrille(posteId, type),
    onSuccess: (_, type) => {
      setEnCours(null)
      onExporte(TYPES_GRILLE.find((t) => t.cle === type)?.libelle ?? 'Document')
      onClose()
    },
    onError: (e) => {
      setEnCours(null)
      setErreur(e instanceof Error ? e.message : "L'export a échoué")
    },
  })

  return (
    <Modal open title="Exporter" onClose={onClose}>
      <p className="text-sm text-ink-600">
        Chaque document s&apos;adresse à quelqu&apos;un de différent. Choisissez celui que vous
        transmettez.
      </p>

      {erreur && (
        <div className="mt-3">
          <Callout tone="danger">{erreur}</Callout>
        </div>
      )}

      <div className="mt-4 space-y-2">
        {TYPES_GRILLE.map((type) => {
          // Sans entretien saisi, la feuille existerait mais ne dirait rien
          // d'autre que son absence : autant l'annoncer avant le clic.
          const vide = type.cle === 'ENTRETIENS' && nombreEntretiens === 0
          return (
            <button
              key={type.cle}
              type="button"
              className="card-interactive w-full p-3 text-left disabled:opacity-50"
              disabled={exporter.isPending || vide}
              onClick={() => {
                setErreur(null)
                setEnCours(type.cle)
                exporter.mutate(type.cle)
              }}
            >
              <span className="flex items-center gap-2 text-sm font-medium text-ink-900">
                {type.libelle}
                {enCours === type.cle && <Spinner />}
              </span>
              <span className="mt-0.5 block text-xs text-ink-500">
                {vide ? "Aucun entretien n'a encore été saisi sur ce poste." : type.pour}
              </span>
            </button>
          )
        })}
      </div>
    </Modal>
  )
}
