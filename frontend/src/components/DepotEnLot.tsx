import { useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { recrutementApi } from '@/lib/api'
import { PIECES } from '@/lib/pieces'
import { Callout, Spinner } from '@/components/ui'

/**
 * Déposer des dossiers déjà en main — une boîte email vidée à la main.
 *
 * Un candidat envoie rarement un seul fichier : il joint son CV, sa lettre,
 * ses diplômes. Traiter chaque fichier comme une candidature produisait quatre
 * dossiers vides à recoller, et une grille où la même personne apparaissait
 * quatre fois.
 *
 * L'écran propose donc un découpage — à partir des noms de fichiers, ou du
 * classement en sous-dossiers quand il y en a un — et **le fait valider avant
 * d'écrire**. C'est le point important : un regroupement erroné mélangerait
 * les pièces de deux personnes, ce qui est bien pire qu'un dossier en trop, et
 * ne se rattrape qu'en rouvrant chaque dossier.
 */

/** Ce que l'écran manipule : un fichier, son dossier, son type. */
interface Ligne {
  fichier: File
  chemin: string
  groupe: string
  type: string | null
}

export default function DepotEnLot({ posteId }: { posteId: string }) {
  const queryClient = useQueryClient()
  const fichierRef = useRef<HTMLInputElement>(null)
  const dossierRef = useRef<HTMLInputElement>(null)
  const [depouiller, setDepouiller] = useState(false)
  const [lignes, setLignes] = useState<Ligne[]>([])
  const [compte, setCompte] = useState<string | null>(null)
  const [details, setDetails] = useState<string[]>([])
  const [erreur, setErreur] = useState<string | null>(null)

  const preparer = useMutation({
    mutationFn: async (fichiers: File[]) => {
      // Le chemin relatif n'existe que sur une sélection de répertoire ; il
      // porte alors un classement fait par quelqu'un, qui prime sur les noms.
      const chemins = fichiers.map(
        (f) => (f as File & { webkitRelativePath?: string }).webkitRelativePath ?? '',
      )
      const noms = fichiers.map((f) => f.name)
      // Une archive n'est pas découpable ici : le serveur l'ouvre au dépôt.
      const archives = fichiers.filter((f) => f.name.toLowerCase().endsWith('.zip'))
      const reste = fichiers.filter((f) => !f.name.toLowerCase().endsWith('.zip'))

      const proposees: Ligne[] = archives.map((f) => ({
        fichier: f,
        chemin: '',
        // Le nom de l'archive nomme le dossier — « Dossier_KODJO.zip » —, et
        // reste corrigeable. Le laisser vide affichait un champ blanc qui se
        // lit comme un oubli.
        groupe: f.name.replace(/\.zip$/i, ''),
        type: null,
      }))
      if (reste.length === 0) return proposees

      const indices = fichiers
        .map((f, i) => ({ f, i }))
        .filter(({ f }) => !f.name.toLowerCase().endsWith('.zip'))
      const { dossiers } = await recrutementApi.apercuDepot(
        posteId,
        indices.map(({ i }) => noms[i]),
        indices.map(({ i }) => chemins[i]),
      )
      for (const dossier of dossiers) {
        for (const piece of dossier.pieces) {
          const source = indices[piece.index]
          proposees.push({
            fichier: source.f,
            chemin: chemins[source.i],
            groupe: dossier.libelle,
            type: piece.type_piece,
          })
        }
      }
      return proposees
    },
    onSuccess: (proposees) => {
      setErreur(null)
      setCompte(null)
      setDetails([])
      setLignes(proposees)
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Lecture impossible'),
  })

  const deposer = useMutation({
    mutationFn: () =>
      recrutementApi.depotMultiple(
        posteId,
        lignes.map((l) => l.fichier),
        depouiller,
        {
          groupes: lignes.map((l) => l.groupe),
          types: lignes.map((l) => l.type),
          chemins: lignes.map((l) => l.chemin),
        },
      ),
    onSuccess: (r) => {
      const parts = [`${r.deposes} dossier(s) déposé(s)`]
      if (r.pieces) parts.push(`${r.pieces} pièce(s)`)
      if (r.doublons_ignores) parts.push(`${r.doublons_ignores} doublon(s) ignoré(s)`)
      if (r.refuses) parts.push(`${r.refuses} refusé(s)`)
      setCompte(parts.join(' · '))
      setDetails(r.resultats.filter((x) => !x.accepte).map((x) => `${x.fichier} — ${x.erreur}`))
      setLignes([])
      void queryClient.invalidateQueries({ queryKey: ['grille', posteId] })
      void queryClient.invalidateQueries({ queryKey: ['candidatures', posteId] })
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Dépôt impossible'),
  })

  const choisir = (fichiers: File[]) => {
    if (fichiers.length) preparer.mutate(fichiers)
  }

  // L'ordre des groupes suit celui des fichiers : le premier vu ouvre le sien.
  const groupes = [...new Set(lignes.map((l) => l.groupe))]
  const renommer = (ancien: string, nouveau: string) =>
    setLignes((tous) =>
      tous.map((l) => (l.groupe === ancien ? { ...l, groupe: nouveau } : l)),
    )

  return (
    <section className="card p-4">
      <h2 className="mb-1 text-sm font-semibold text-ink-900">Déposer des dossiers</h2>
      <p className="mb-3 text-xs text-ink-500">
        Pour les CV déjà reçus par ailleurs. Les fichiers d&apos;une même personne sont regroupés
        en un seul dossier — vérifiez le découpage avant de valider. Un dossier par sous-répertoire
        ou une archive <code className="rounded bg-ink-100 px-1">.zip</code> par candidat sont
        reconnus tels quels.
      </p>

      <label className="mb-3 flex items-center gap-2 text-xs text-ink-700">
        <input
          type="checkbox"
          checked={depouiller}
          onChange={(e) => setDepouiller(e.target.checked)}
        />
        Dépouiller aussitôt (lecture assistée des CV — plus lent)
      </label>

      <input
        ref={fichierRef}
        type="file"
        multiple
        accept=".pdf,.docx,.doc,.zip"
        className="hidden"
        onChange={(e) => {
          choisir(Array.from(e.target.files ?? []))
          e.target.value = ''
        }}
      />
      <input
        ref={dossierRef}
        type="file"
        multiple
        // @ts-expect-error — attribut non standard, mais supporté partout où
        // l'application tourne. C'est lui qui donne `webkitRelativePath`.
        webkitdirectory=""
        directory=""
        className="hidden"
        onChange={(e) => {
          choisir(Array.from(e.target.files ?? []))
          e.target.value = ''
        }}
      />

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="btn-ghost flex-1"
          disabled={preparer.isPending || deposer.isPending}
          onClick={() => fichierRef.current?.click()}
        >
          {preparer.isPending && <Spinner />}
          Choisir des fichiers…
        </button>
        <button
          type="button"
          className="btn-ghost flex-1"
          disabled={preparer.isPending || deposer.isPending}
          onClick={() => dossierRef.current?.click()}
        >
          Choisir un répertoire…
        </button>
      </div>

      {erreur && (
        <div className="mt-3">
          <Callout tone="danger">{erreur}</Callout>
        </div>
      )}

      {lignes.length > 0 && (
        <div className="mt-4">
          <p className="text-sm font-medium text-ink-800">
            {groupes.length} dossier(s) proposé(s) pour {lignes.length} fichier(s)
          </p>
          <p className="mt-0.5 text-xs text-ink-500">
            Corrigez ce qui doit l&apos;être : le nom d&apos;un dossier, le type d&apos;une pièce,
            ou le dossier auquel un fichier appartient. Rien n&apos;est écrit avant que vous
            validiez.
          </p>

          <div className="mt-3 space-y-3">
            {groupes.map((groupe) => (
              <div key={groupe} className="rounded-lg bg-ink-50 p-3">
                <input
                  className="input py-1 text-sm font-medium"
                  value={groupe}
                  aria-label={`Nom du dossier — ${groupe || 'sans nom'}`}
                  placeholder="Nom du candidat"
                  onChange={(e) => renommer(groupe, e.target.value)}
                />
                <ul className="mt-2 space-y-1.5">
                  {lignes
                    .map((ligne, index) => ({ ligne, index }))
                    .filter(({ ligne }) => ligne.groupe === groupe)
                    .map(({ ligne, index }) => (
                      <li key={index} className="flex flex-wrap items-center gap-2">
                        <span
                          className="min-w-0 flex-1 truncate text-xs text-ink-700"
                          title={ligne.fichier.name}
                        >
                          {ligne.fichier.name}
                        </span>
                        {ligne.fichier.name.toLowerCase().endsWith('.zip') ? (
                          <span className="text-xs text-ink-500">
                            archive — ouverte au dépôt
                          </span>
                        ) : (
                          <>
                            <select
                              className="input w-auto py-1 text-xs"
                              value={ligne.type ?? ''}
                              aria-label={`Type — ${ligne.fichier.name}`}
                              onChange={(e) =>
                                setLignes((tous) =>
                                  tous.map((l, i) =>
                                    i === index ? { ...l, type: e.target.value || null } : l,
                                  ),
                                )
                              }
                            >
                              <option value="">à déterminer</option>
                              {PIECES.map(([code, libelle]) => (
                                <option key={code} value={code}>
                                  {libelle}
                                </option>
                              ))}
                            </select>
                            <select
                              className="input w-auto py-1 text-xs"
                              value={ligne.groupe}
                              aria-label={`Dossier — ${ligne.fichier.name}`}
                              onChange={(e) =>
                                setLignes((tous) =>
                                  tous.map((l, i) =>
                                    i === index ? { ...l, groupe: e.target.value } : l,
                                  ),
                                )
                              }
                            >
                              {groupes.map((g) => (
                                <option key={g} value={g}>
                                  {g || 'sans nom'}
                                </option>
                              ))}
                            </select>
                          </>
                        )}
                        <button
                          type="button"
                          className="text-xs text-red-700 hover:underline"
                          aria-label={`Retirer ${ligne.fichier.name}`}
                          onClick={() =>
                            setLignes((tous) => tous.filter((_, i) => i !== index))
                          }
                        >
                          ×
                        </button>
                      </li>
                    ))}
                </ul>
              </div>
            ))}
          </div>

          <div className="mt-3 flex flex-wrap justify-end gap-2">
            <button type="button" className="btn-ghost" onClick={() => setLignes([])}>
              Annuler
            </button>
            <button
              type="button"
              className="btn-primary"
              disabled={deposer.isPending}
              onClick={() => deposer.mutate()}
            >
              {deposer.isPending && <Spinner />}
              Déposer {groupes.length} dossier(s)
            </button>
          </div>
        </div>
      )}

      {compte && <p className="mt-3 text-sm font-medium text-ink-800">{compte}</p>}
      {details.length > 0 && (
        <ul className="mt-2 list-disc space-y-0.5 pl-4 text-xs text-ink-600">
          {details.map((d) => (
            <li key={d}>{d}</li>
          ))}
        </ul>
      )}
    </section>
  )
}
