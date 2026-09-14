import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { recrutementApi } from '@/lib/api'
import type { LigneBaremeEntretien } from '@/types'
import { Callout, Field, Modal, Spinner } from '@/components/ui'

/**
 * La grille d'entretien du poste.
 *
 * Les documents du cabinet la présentent comme une « grille indicative »,
 * « validée par le client » : elle se négocie mandat par mandat. La coder en
 * dur reviendrait à imposer au commanditaire une pondération qu'il a le droit
 * de discuter — et à rendre le logiciel faux dès le premier mandat qui en
 * change.
 *
 * Le total reste libre : c'est lui qui vaut 70 % de la note finale, quel que
 * soit le nombre de points sur lequel il est exprimé. Ce qui compte est que
 * tous les candidats d'un même poste soient notés sur la même grille — ce que
 * garantit le fait qu'elle vive sur le poste et non sur la fiche.
 */
export default function GrilleEntretienEditeur({
  posteId,
  onClose,
}: {
  posteId: string
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const grille = useQuery({
    queryKey: ['grille-entretien', posteId],
    queryFn: () => recrutementApi.grilleEntretien(posteId),
  })

  const [lignes, setLignes] = useState<LigneBaremeEntretien[]>([])
  const [erreur, setErreur] = useState<string | null>(null)

  useEffect(() => {
    if (grille.data) setLignes(grille.data.criteres)
  }, [grille.data])

  const enregistrer = useMutation({
    mutationFn: (personnalisee: boolean) =>
      recrutementApi.definirGrilleEntretien(posteId, personnalisee ? lignes : null),
    onSuccess: () => {
      setErreur(null)
      void queryClient.invalidateQueries({ queryKey: ['grille-entretien', posteId] })
      void queryClient.invalidateQueries({ queryKey: ['grille', posteId] })
      onClose()
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Enregistrement impossible'),
  })

  const total = lignes.reduce((somme, l) => somme + (Number(l.points_max) || 0), 0)

  const modifier = (index: number, champ: Partial<LigneBaremeEntretien>) =>
    setLignes((tous) => tous.map((l, i) => (i === index ? { ...l, ...champ } : l)))

  return (
    <Modal open title="Grille d'entretien" onClose={onClose}>
      {grille.isLoading ? (
        <Spinner />
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-ink-600">
            Elle se négocie avec le commanditaire. Tous les candidats du poste sont notés dessus,
            et elle vaut 70 % de la note finale — quel que soit le total sur lequel elle est
            exprimée.
          </p>

          {grille.data?.par_defaut && (
            <Callout tone="info">
              Ce poste utilise la grille du cabinet. La modifier ici la rend propre à ce poste.
            </Callout>
          )}

          <div className="space-y-2">
            {lignes.map((ligne, index) => (
              <div
                key={index}
                className="grid gap-2 rounded-lg bg-ink-50 p-2 sm:grid-cols-[1fr_9rem_5rem_2rem]"
              >
                <input
                  className="input py-1 text-sm"
                  value={ligne.libelle}
                  aria-label={`Rubrique ${index + 1}`}
                  placeholder="Compétences techniques"
                  onChange={(e) => modifier(index, { libelle: e.target.value })}
                />
                <input
                  className="input py-1 text-sm"
                  value={ligne.section ?? ''}
                  aria-label={`Section — ${ligne.libelle}`}
                  placeholder="Section (facultatif)"
                  onChange={(e) => modifier(index, { section: e.target.value })}
                />
                <input
                  type="number"
                  min={0}
                  step={0.5}
                  className="input py-1 text-sm"
                  value={ligne.points_max}
                  aria-label={`Points — ${ligne.libelle}`}
                  onChange={(e) => modifier(index, { points_max: Number(e.target.value) })}
                />
                <button
                  type="button"
                  className="text-sm text-red-700 hover:underline"
                  aria-label={`Retirer ${ligne.libelle}`}
                  onClick={() => setLignes((tous) => tous.filter((_, i) => i !== index))}
                >
                  ×
                </button>
              </div>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              className="btn-ghost px-3 py-1.5 text-xs"
              onClick={() =>
                setLignes((tous) => [
                  ...tous,
                  {
                    code: `RUBRIQUE_${tous.length + 1}`,
                    libelle: '',
                    points_max: 5,
                    section: '',
                  },
                ])
              }
            >
              + Ajouter une rubrique
            </button>
            <span className="ml-auto text-sm font-medium text-ink-900">
              Total : <span className="tabular-nums">{total}</span> points
            </span>
          </div>

          {erreur && <Callout tone="danger">{erreur}</Callout>}

          <Field label="" hint="Revenir à la grille du cabinet efface la grille propre à ce poste. Les fiches déjà saisies gardent la grille sur laquelle elles ont été notées.">
            <div className="flex flex-wrap justify-end gap-2">
              {!grille.data?.par_defaut && (
                <button
                  type="button"
                  className="btn-ghost text-xs"
                  disabled={enregistrer.isPending}
                  onClick={() => enregistrer.mutate(false)}
                >
                  Revenir à la grille du cabinet
                </button>
              )}
              <button type="button" className="btn-ghost" onClick={onClose}>
                Annuler
              </button>
              <button
                type="button"
                className="btn-primary"
                disabled={
                  enregistrer.isPending ||
                  lignes.length === 0 ||
                  lignes.some((l) => !l.libelle.trim())
                }
                onClick={() => enregistrer.mutate(true)}
              >
                {enregistrer.isPending && <Spinner />}
                Enregistrer
              </button>
            </div>
          </Field>
        </div>
      )}
    </Modal>
  )
}
