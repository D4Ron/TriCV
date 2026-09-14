import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { PORTEES_ENVOI, recrutementApi, type PorteeEnvoi } from '@/lib/api'
import { Callout, Modal, Spinner } from '@/components/ui'

/**
 * À qui écrire, avant de rédiger quoi que ce soit.
 *
 * L'écran ne proposait d'écrire qu'aux préqualifiés et aux proposés. Tout le
 * reste du fichier — les dossiers écartés, ceux à qui il manque une pièce, et
 * simplement tous ceux qui ont postulé — n'avait aucun moyen d'être contacté
 * depuis l'application, alors que ce sont les envois les plus nombreux : un
 * accusé de réception, une réclamation de pièce, une lettre de refus.
 *
 * Les listes viennent du serveur et non de la grille affichée. La différence
 * compte pour « tous les candidats » : la grille montre ce qu'elle a chargé,
 * le serveur sait ce qui a été reçu.
 */
export default function ChoisirDestinataires({
  posteId,
  onChoisi,
  onClose,
}: {
  posteId: string
  /** `note` signale ce que la portée laisse de côté : à afficher par l'appelant,
   *  cette fenêtre se refermant aussitôt. */
  onChoisi: (ids: string[], libelle: string, note: string | null) => void
  onClose: () => void
}) {
  const [erreur, setErreur] = useState<string | null>(null)
  const [enCours, setEnCours] = useState<PorteeEnvoi | null>(null)

  const charger = useMutation({
    mutationFn: (portee: PorteeEnvoi) => recrutementApi.destinataires(posteId, portee),
    onSuccess: (resultat, portee) => {
      setEnCours(null)
      const libelle = PORTEES_ENVOI.find((p) => p.cle === portee)?.libelle ?? portee
      if (resultat.candidature_ids.length === 0) {
        setErreur(
          resultat.total > 0
            ? `${libelle} : ${resultat.total} dossier(s), aucun avec une adresse email.`
            : `${libelle} : aucun dossier.`,
        )
        return
      }
      onChoisi(
        resultat.candidature_ids,
        libelle,
        resultat.sans_adresse > 0
          ? `${libelle} : ${resultat.sans_adresse} dossier(s) sans adresse email ne recevront ` +
            `rien ; ${resultat.candidature_ids.length} destinataire(s) retenu(s).`
          : null,
      )
    },
    onError: (e) => {
      setEnCours(null)
      setErreur(e instanceof Error ? e.message : 'Liste indisponible')
    },
  })

  return (
    <Modal open title="Écrire aux candidats" onClose={onClose}>
      <p className="text-sm text-ink-600">
        Choisissez à qui vous écrivez. Le texte sera montré, dossier par dossier, avant
        d&apos;être expédié.
      </p>

      {erreur && (
        <div className="mt-3">
          <Callout tone="warning">{erreur}</Callout>
        </div>
      )}

      <div className="mt-4 space-y-2">
        {PORTEES_ENVOI.map((portee) => (
          <button
            key={portee.cle}
            type="button"
            className="card-interactive w-full p-3 text-left"
            disabled={charger.isPending}
            onClick={() => {
              setErreur(null)
              setEnCours(portee.cle)
              charger.mutate(portee.cle)
            }}
          >
            <span className="flex items-center gap-2 text-sm font-medium text-ink-900">
              {portee.libelle}
              {enCours === portee.cle && <Spinner />}
            </span>
            <span className="mt-0.5 block text-xs text-ink-500">{portee.aide}</span>
          </button>
        ))}
      </div>
    </Modal>
  )
}
