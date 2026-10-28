import { useEffect, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { dossiersApi, type PorteeEnvoi } from '@/lib/api'
import { Callout, Modal, Spinner } from '@/components/ui'

/**
 * Emporter plusieurs dossiers d'un coup : pour imprimer, ou sur une clé USB.
 *
 * Les RH ouvraient chaque candidat et téléchargeaient ses pièces une à une.
 * L'archive rend les fichiers tels que reçus — pas la version remise en forme
 * des « CV à en-tête » —, un dossier par candidat, et un sommaire à ouvrir dans
 * Excel. On choisit une portée, puis on décoche ceux qu'on ne veut pas.
 */

const PORTEES: Array<{ cle: PorteeEnvoi; libelle: string }> = [
  { cle: 'tous', libelle: 'Tous les candidats' },
  { cle: 'preselectionnes', libelle: 'Préqualifiés' },
  { cle: 'a_verifier', libelle: 'À vérifier' },
  { cle: 'sous_le_seuil', libelle: 'Sous le seuil' },
  { cle: 'elimines', libelle: 'Éliminés' },
]

export default function TelechargerDossiers({
  posteId,
  onClose,
  onTelecharge,
}: {
  posteId: string
  onClose: () => void
  onTelecharge: (compteRendu: string) => void
}) {
  const [portee, setPortee] = useState<PorteeEnvoi>('preselectionnes')
  const [coches, setCoches] = useState<Set<string>>(new Set())

  const liste = useQuery({
    queryKey: ['dossiers', posteId, portee],
    queryFn: () => dossiersApi.duPoste(posteId, portee),
  })

  // Une nouvelle portée part toute cochée : c'est le cas courant, et décocher
  // trois noms coûte moins que d'en cocher trente.
  useEffect(() => {
    if (liste.data) setCoches(new Set(liste.data.map((l) => l.candidature_id)))
  }, [liste.data])

  const telecharger = useMutation({
    mutationFn: () =>
      dossiersApi.telechargerArchive(
        posteId,
        (liste.data ?? []).filter((l) => coches.has(l.candidature_id)).map((l) => l.candidature_id),
      ),
    onSuccess: () => {
      onTelecharge(`${coches.size} dossier(s) téléchargé(s) dans une archive ZIP.`)
      onClose()
    },
  })

  const lignes = liste.data ?? []
  const sansFichier = lignes.filter((l) => coches.has(l.candidature_id) && l.pieces_disponibles === 0)
  const toutCoche = lignes.length > 0 && lignes.every((l) => coches.has(l.candidature_id))

  return (
    <Modal open title="Télécharger des dossiers" onClose={onClose}>
      <p className="text-sm text-ink-600">
        Une archive ZIP : un dossier par candidat, avec les fichiers tels qu&apos;ils ont été
        reçus, et un sommaire à ouvrir dans Excel. Pour imprimer ou copier sur une clé USB.
      </p>

      <div className="mt-4 flex flex-wrap gap-1.5">
        {PORTEES.map((p) => (
          <button
            key={p.cle}
            type="button"
            aria-pressed={portee === p.cle}
            onClick={() => setPortee(p.cle)}
            className={`rounded-full border px-3 py-1 text-xs font-medium transition ${
              portee === p.cle
                ? 'border-brand-400 bg-brand-50 text-brand-800'
                : 'border-ink-200 text-ink-600 hover:border-ink-300'
            }`}
          >
            {p.libelle}
          </button>
        ))}
      </div>

      <div className="mt-4">
        {liste.isLoading && <Spinner />}
        {liste.isError && <Callout tone="danger">Liste indisponible.</Callout>}
        {liste.data && lignes.length === 0 && (
          <p className="text-sm text-ink-500">Aucun dossier dans cette catégorie.</p>
        )}
        {lignes.length > 0 && (
          <>
            <label className="mb-2 flex items-center gap-2 text-xs font-medium text-ink-700">
              <input
                type="checkbox"
                checked={toutCoche}
                onChange={() =>
                  setCoches(toutCoche ? new Set() : new Set(lignes.map((l) => l.candidature_id)))
                }
              />
              {toutCoche ? 'Tout décocher' : 'Tout cocher'} ({lignes.length})
            </label>
            <ul className="max-h-72 divide-y divide-ink-100 overflow-y-auto rounded-lg border border-ink-200">
              {lignes.map((l) => (
                <li key={l.candidature_id}>
                  <label className="flex cursor-pointer items-center gap-3 px-3 py-2 text-sm hover:bg-ink-50">
                    <input
                      type="checkbox"
                      checked={coches.has(l.candidature_id)}
                      onChange={() =>
                        setCoches((c) => {
                          const suivant = new Set(c)
                          if (suivant.has(l.candidature_id)) suivant.delete(l.candidature_id)
                          else suivant.add(l.candidature_id)
                          return suivant
                        })
                      }
                    />
                    <span className="min-w-0 flex-1 truncate">
                      <span className="font-medium text-ink-900">{l.nom.toUpperCase()}</span>{' '}
                      {l.prenom}
                    </span>
                    <span className="shrink-0 text-xs text-ink-500">
                      {l.statut}
                      {l.note ? ` · ${l.note}` : ''} · {l.pieces_disponibles} fichier(s)
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>

      {sansFichier.length > 0 && (
        <div className="mt-3">
          <Callout tone="warning">
            {sansFichier.length} dossier(s) coché(s) n&apos;ont plus aucun fichier (purgés après
            archivage du mandat) : ils figureront seulement au sommaire.
          </Callout>
        </div>
      )}
      {telecharger.isError && (
        <div className="mt-3">
          <Callout tone="danger">
            {telecharger.error instanceof Error ? telecharger.error.message : 'Le téléchargement a échoué.'}
          </Callout>
        </div>
      )}

      <div className="mt-5 flex justify-end gap-2">
        <button type="button" className="btn-ghost" onClick={onClose}>
          Annuler
        </button>
        <button
          type="button"
          className="btn-primary"
          disabled={coches.size === 0 || telecharger.isPending}
          onClick={() => telecharger.mutate()}
        >
          {telecharger.isPending && <Spinner />}
          Télécharger {coches.size > 0 ? `${coches.size} dossier(s)` : ''}
        </button>
      </div>
    </Modal>
  )
}
