import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { recrutementApi } from '@/lib/api'
import { Callout, ErrorState, Spinner } from '@/components/ui'
import { formatDateTime } from '@/lib/format'
import type { Elimination, Provenance } from '@/types'

const LIBELLE_PIECE: Record<string, string> = {
  LETTRE_MOTIVATION: 'Lettre de motivation',
  CV: 'CV détaillé',
  COPIE_DIPLOMES: 'Copie des diplômes',
  ATTESTATIONS_TRAVAIL: 'Attestations de travail',
  PIECE_IDENTITE: "Pièce d'identité",
  CERTIFICAT_NATIONALITE: 'Certificat de nationalité',
}

const LIBELLE_PROVENANCE: Record<Provenance, string> = {
  DECLARE: 'Déclaré par le candidat',
  EXTRAIT_IA: 'Extrait automatiquement — à confirmer',
  VERIFIE_RH: 'Vérifié',
  SAISI_RH: 'Saisi par les RH',
}

function MotifCard({
  motif,
  onLever,
  enCours,
}: {
  motif: Elimination
  onLever: (motif: string, justification: string) => void
  enCours: boolean
}) {
  const [ouvert, setOuvert] = useState(false)
  const [justification, setJustification] = useState('')
  const leve = motif.leve_le !== null

  return (
    <div
      className={`rounded-lg border px-3 py-2.5 ${
        leve
          ? 'border-ink-200 bg-ink-50'
          : motif.sur_donnee_non_verifiee
            ? 'border-amber-200 bg-amber-50'
            : 'border-red-200 bg-red-50'
      }`}
    >
      <div className="flex items-start gap-2">
        <p
          className={`flex-1 text-sm font-medium ${
            leve ? 'text-ink-500 line-through' : 'text-ink-900'
          }`}
        >
          {motif.libelle}
        </p>
        {!leve && (
          <button
            type="button"
            className="text-xs font-medium text-ink-600 hover:underline"
            onClick={() => setOuvert((o) => !o)}
          >
            Lever
          </button>
        )}
      </div>

      <p className="mt-1 text-xs text-ink-600">
        Attendu : {motif.attendu} · Constaté : {motif.constate}
      </p>

      {motif.justification_poste && (
        <p className="mt-1 text-xs italic text-ink-500">
          Condition de l'avis : {motif.justification_poste}
        </p>
      )}

      {motif.sur_donnee_non_verifiee && !leve && (
        <p className="mt-1.5 text-xs font-medium text-amber-800">
          Fondé sur une donnée non confirmée — n'élimine pas tant qu'elle n'est pas vérifiée.
        </p>
      )}

      {leve && <p className="mt-1 text-xs text-ink-500">Levé : {motif.leve_motif}</p>}

      {ouvert && !leve && (
        <div className="mt-2 space-y-2">
          <textarea
            className="input min-h-[3.5rem] text-sm"
            value={justification}
            onChange={(e) => setJustification(e.target.value)}
            placeholder="Pourquoi ce motif ne s'applique pas…"
          />
          <button
            type="button"
            className="btn-primary w-full py-1.5 text-xs"
            disabled={!justification.trim() || enCours}
            onClick={() => onLever(motif.motif, justification)}
          >
            {enCours && <Spinner />}
            Confirmer la levée
          </button>
        </div>
      )}
    </div>
  )
}

export default function CandidatureDrawer({
  candidatureId,
  posteId,
  onClose,
}: {
  candidatureId: string
  posteId: string
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const fichierRef = useRef<HTMLInputElement>(null)
  const [typePiece, setTypePiece] = useState('CV')
  const [erreur, setErreur] = useState<string | null>(null)
  const [compteRendu, setCompteRendu] = useState<string | null>(null)
  const [avertissements, setAvertissements] = useState<string[]>([])

  const candidature = useQuery({
    queryKey: ['candidature', candidatureId],
    queryFn: () => recrutementApi.candidature(candidatureId),
  })

  const rafraichir = () => {
    void queryClient.invalidateQueries({ queryKey: ['candidature', candidatureId] })
    void queryClient.invalidateQueries({ queryKey: ['grille', posteId] })
  }

  const lever = useMutation({
    mutationFn: ({ motif, justification }: { motif: string; justification: string }) =>
      recrutementApi.leverMotif(candidatureId, motif, justification),
    onSuccess: rafraichir,
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Levée impossible'),
  })

  const verifier = useMutation({
    mutationFn: () =>
      recrutementApi.verifier(candidatureId, {
        etat_civil: true,
        diplomes: true,
        experiences: true,
      }),
    onSuccess: rafraichir,
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Vérification impossible'),
  })

  const depouiller = useMutation({
    mutationFn: () => recrutementApi.depouiller(candidatureId),
    onSuccess: (resultat) => {
      const parts: string[] = []
      if (resultat.diplomes) parts.push(`${resultat.diplomes} diplôme(s)`)
      if (resultat.experiences) parts.push(`${resultat.experiences} expérience(s)`)
      setCompteRendu(
        parts.length
          ? `Proposé : ${parts.join(', ')}. À relire avant confirmation.`
          : "Rien n'a pu être lu dans les pièces.",
      )
      setAvertissements(resultat.avertissements)
      rafraichir()
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Dépouillement impossible'),
  })

  const joindre = useMutation({
    mutationFn: (fichier: File) =>
      recrutementApi.joindrePiece(candidatureId, typePiece, fichier),
    onSuccess: () => {
      setErreur(null)
      rafraichir()
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Dépôt impossible'),
  })

  const ouvrirPiece = async (pieceId: string) => {
    try {
      const url = await recrutementApi.pieceObjectUrl(candidatureId, pieceId)
      window.open(url, '_blank', 'noopener')
      // L'onglet a chargé le blob : l'URL peut être libérée sans le casser.
      setTimeout(() => URL.revokeObjectURL(url), 60_000)
    } catch (e) {
      setErreur(e instanceof Error ? e.message : 'Pièce indisponible')
    }
  }

  const c = candidature.data

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-ink-900/40" onClick={onClose}>
      <aside
        className="h-full w-full max-w-xl overflow-y-auto bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="sticky top-0 flex items-center gap-3 border-b border-ink-200 bg-white px-5 py-3">
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold text-ink-900">
              {c ? `${c.candidat.nom.toUpperCase()} ${c.candidat.prenom}` : 'Chargement…'}
            </p>
            {c && (
              <p className="truncate text-xs text-ink-500">
                {c.candidat.email ?? 'sans email'} · reçue le{' '}
                {formatDateTime(c.recue_le, 'fr')} · {c.source.toLowerCase()}
              </p>
            )}
          </div>
          <button type="button" className="btn-ghost px-2 py-1 text-xs" onClick={onClose}>
            Fermer
          </button>
        </header>

        {candidature.isLoading && (
          <div className="flex justify-center py-16">
            <Spinner className="h-6 w-6" />
          </div>
        )}
        {candidature.isError && (
          <div className="p-5">
            <ErrorState error={candidature.error} onRetry={() => candidature.refetch()} />
          </div>
        )}

        {c && (
          <div className="space-y-6 p-5">
            {erreur && <Callout tone="danger">{erreur}</Callout>}

            {c.statut === 'A_VERIFIER' && (
              <Callout tone="warning">
                <p className="font-medium">Dossier à vérifier</p>
                <p className="mt-1">
                  Les données de ce dossier ont été proposées automatiquement. Tant qu'un
                  relecteur ne les a pas confirmées, il ne peut ni être éliminé, ni rejoindre la
                  présélection.
                </p>
                {compteRendu && <p className="mt-2 font-medium">{compteRendu}</p>}
                {avertissements.length > 0 && (
                  <ul className="mt-2 list-disc space-y-0.5 pl-4 text-xs">
                    {avertissements.map((a) => (
                      <li key={a}>{a}</li>
                    ))}
                  </ul>
                )}
                <div className="mt-3 flex flex-wrap gap-2">
                  {c.candidat.diplomes.length === 0 && c.candidat.experiences.length === 0 && (
                    <button
                      type="button"
                      className="btn-ghost py-1.5 text-xs"
                      disabled={depouiller.isPending}
                      onClick={() => depouiller.mutate()}
                    >
                      {depouiller.isPending && <Spinner />}
                      Dépouiller le dossier
                    </button>
                  )}
                  <button
                    type="button"
                    className="btn-primary py-1.5 text-xs"
                    disabled={verifier.isPending}
                    onClick={() => verifier.mutate()}
                  >
                    {verifier.isPending && <Spinner />}
                    Confirmer les données
                  </button>
                </div>
              </Callout>
            )}

            {c.notation && (
              <section>
                <div className="mb-2 flex items-baseline gap-2">
                  <h3 className="text-sm font-semibold text-ink-900">Notation</h3>
                  <span className="ml-auto text-lg font-semibold tabular-nums text-ink-900">
                    {c.notation.note_manuelle ?? c.notation.total}
                    <span className="text-ink-400">/{c.notation.total_max}</span>
                  </span>
                </div>
                {c.notation.note_manuelle !== null && (
                  <p className="mb-2 text-xs italic text-ink-500">
                    Note saisie manuellement ({c.notation.total} calculé) —{' '}
                    {c.notation.note_manuelle_motif}
                  </p>
                )}
                <div className="space-y-1.5">
                  {c.notation.lignes.map((ligne) => (
                    <div key={ligne.code} className="rounded-lg bg-ink-50 px-3 py-2">
                      <div className="flex items-baseline gap-2">
                        <p className="flex-1 text-sm font-medium text-ink-800">{ligne.libelle}</p>
                        <span className="text-sm font-semibold tabular-nums text-ink-900">
                          {ligne.points}
                          <span className="text-ink-400">/{ligne.points_max}</span>
                        </span>
                      </div>
                      {ligne.detail && (
                        <p className="mt-0.5 text-xs text-ink-500">{ligne.detail}</p>
                      )}
                    </div>
                  ))}
                </div>
              </section>
            )}

            {c.eliminations.length > 0 && (
              <section>
                <h3 className="mb-2 text-sm font-semibold text-ink-900">Motifs d'élimination</h3>
                <div className="space-y-2">
                  {c.eliminations.map((motif) => (
                    <MotifCard
                      key={motif.id}
                      motif={motif}
                      enCours={lever.isPending}
                      onLever={(m, j) => lever.mutate({ motif: m, justification: j })}
                    />
                  ))}
                </div>
              </section>
            )}

            <section>
              <h3 className="mb-2 text-sm font-semibold text-ink-900">Pièces du dossier</h3>
              <div className="space-y-1.5">
                {c.pieces.length === 0 && (
                  <p className="text-sm text-ink-500">Aucune pièce enregistrée.</p>
                )}
                {c.pieces.map((piece) => (
                  <div
                    key={piece.id}
                    className="flex items-center gap-2 rounded-lg border border-ink-200 px-3 py-2"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm text-ink-800">
                        {LIBELLE_PIECE[piece.type_piece] ?? piece.type_piece}
                      </p>
                      <p className="truncate text-xs text-ink-500">
                        {piece.nom_fichier ?? 'reçue, fichier non classé'}
                      </p>
                    </div>
                    {piece.nom_fichier && (
                      <button
                        type="button"
                        className="text-xs font-medium text-ink-600 hover:underline"
                        onClick={() => void ouvrirPiece(piece.id)}
                      >
                        Ouvrir
                      </button>
                    )}
                  </div>
                ))}
              </div>

              <div className="mt-3 flex items-center gap-2">
                <select
                  className="input w-auto text-sm"
                  value={typePiece}
                  onChange={(e) => setTypePiece(e.target.value)}
                  aria-label="Type de pièce"
                >
                  {Object.entries(LIBELLE_PIECE).map(([code, libelle]) => (
                    <option key={code} value={code}>
                      {libelle}
                    </option>
                  ))}
                </select>
                <input
                  ref={fichierRef}
                  type="file"
                  accept=".pdf,.docx,.doc"
                  className="hidden"
                  onChange={(e) => {
                    const fichier = e.target.files?.[0]
                    if (fichier) joindre.mutate(fichier)
                    e.target.value = ''
                  }}
                />
                <button
                  type="button"
                  className="btn-ghost text-sm"
                  disabled={joindre.isPending}
                  onClick={() => fichierRef.current?.click()}
                >
                  {joindre.isPending && <Spinner />}
                  Joindre un fichier
                </button>
              </div>
            </section>

            <section>
              <h3 className="mb-2 text-sm font-semibold text-ink-900">Profil déclaré</h3>
              <p className="mb-2 text-xs text-ink-500">
                {LIBELLE_PROVENANCE[c.candidat.provenance]}
              </p>
              <dl className="space-y-1 text-sm">
                {c.candidat.diplomes.map((d) => (
                  <div key={d.id} className="rounded-lg bg-ink-50 px-3 py-2">
                    <p className="text-ink-800">
                      {d.intitule} — BAC+{d.niveau}
                    </p>
                    <p className="text-xs text-ink-500">
                      {d.domaine}
                      {d.etablissement ? ` · ${d.etablissement}` : ''}
                      {d.annee ? ` · ${d.annee}` : ''}
                    </p>
                  </div>
                ))}
                {c.candidat.experiences.map((e) => (
                  <div key={e.id} className="rounded-lg bg-ink-50 px-3 py-2">
                    <p className="text-ink-800">
                      {e.poste} — {e.employeur}
                    </p>
                    <p className="text-xs text-ink-500">
                      {e.debut} → {e.fin ?? 'en cours'}
                      {e.pays ? ` · ${e.pays}` : ''}
                    </p>
                  </div>
                ))}
                {c.candidat.diplomes.length === 0 && c.candidat.experiences.length === 0 && (
                  <p className="text-sm text-ink-500">
                    Aucun diplôme ni expérience saisis. Le dossier attend d'être dépouillé.
                  </p>
                )}
              </dl>
            </section>
          </div>
        )}
      </aside>
    </div>
  )
}
