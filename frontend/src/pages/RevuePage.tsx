import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { recrutementApi } from '@/lib/api'
import { useAnnulable } from '@/lib/annulable'
import { LIBELLE_SOURCE } from '@/lib/interface'
import { RAISONS_DE_LEVEE, libellePiece } from '@/lib/pieces'
import { formatDate, formatMois } from '@/lib/format'
import { Callout, ErrorState, PageLoader, Spinner } from '@/components/ui'
import CandidatureDrawer from '@/components/CandidatureDrawer'
import SyntheseDossier from '@/components/SyntheseDossier'
import type { Candidature, CandidatureListItem, Provenance } from '@/types'

/**
 * La revue des dossiers d'un poste, l'un après l'autre.
 *
 * Le geste réel : lire le CV, vérifier que ce que l'application en a tiré est
 * juste, confirmer, passer au suivant. Le panneau latéral obligeait à le faire
 * de mémoire — le CV s'ouvrait dans un autre onglet, et le parcours extrait se
 * trouvait tout en bas, sous cinq blocs d'explications. Ici le document est à
 * gauche, ce qu'il faut vérifier à droite, et une seule action principale.
 *
 * Rien n'est retiré : le dossier complet — pièces, entretien, courriel,
 * changement de poste, suppression — s'ouvre d'un clic (touche E).
 */

const TOUCHES = 'J / K : suivant / précédent · C : confirmer · E : dossier complet'

function duree(debut: string, fin: string | null): string {
  const d = new Date(debut)
  const f = fin ? new Date(fin) : new Date()
  const mois = Math.max(0, (f.getFullYear() - d.getFullYear()) * 12 + f.getMonth() - d.getMonth())
  if (mois < 12) return `${mois} mois`
  const ans = Math.floor(mois / 12)
  const reste = mois % 12
  return `${ans} an${ans > 1 ? 's' : ''}${reste ? ` et ${reste} mois` : ''}`
}

function Propose({ provenance }: { provenance: Provenance }) {
  if (provenance !== 'EXTRAIT_IA') return null
  return (
    <span
      className="ml-1.5 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-800"
      title="Lu automatiquement dans le document : à comparer avant de confirmer"
    >
      à vérifier
    </span>
  )
}

// Le CV d'abord : c'est lui qu'on relit contre la fiche de droite.
const ORDRE_DES_PIECES: Record<string, number> = {
  CV: 0,
  COPIE_DIPLOMES: 1,
  ATTESTATIONS_TRAVAIL: 2,
  LETTRE_MOTIVATION: 3,
}

/** Le document du candidat, affiché dans la page plutôt que dans un autre onglet. */
function Document({ candidature }: { candidature: Candidature }) {
  const pieces = candidature.pieces
    .filter((p) => p.nom_fichier)
    .sort((a, b) => (ORDRE_DES_PIECES[a.type_piece] ?? 9) - (ORDRE_DES_PIECES[b.type_piece] ?? 9))
  const [actif, setActif] = useState(pieces[0]?.id ?? null)
  const [url, setUrl] = useState<string | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  const piece = pieces.find((p) => p.id === actif) ?? null
  const nomFichier = (piece?.nom_fichier ?? '').toLowerCase()
  const estPdf = nomFichier.endsWith('.pdf')
  // Les photos de diplômes ou de pièces d'identité, prises au téléphone.
  const estImage = /\.(jpe?g|png|webp)$/.test(nomFichier)

  useEffect(() => {
    setActif(pieces[0]?.id ?? null)
    // Un autre dossier : on repart de sa première pièce.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candidature.id])

  useEffect(() => {
    let annule = false
    let cree: string | null = null
    setUrl(null)
    setErreur(null)
    if (!actif) return undefined
    recrutementApi
      .pieceObjectUrl(candidature.id, actif)
      .then((u) => {
        cree = u
        if (!annule) setUrl(u)
      })
      .catch((e) => !annule && setErreur(e instanceof Error ? e.message : 'Pièce indisponible'))
    return () => {
      annule = true
      if (cree) URL.revokeObjectURL(cree)
    }
  }, [actif, candidature.id])

  if (pieces.length === 0) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-sm text-ink-500">
        Aucune pièce dans ce dossier.
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex gap-1 overflow-x-auto border-b border-ink-200 px-2 pt-2">
        {pieces.map((p) => (
          <button
            key={p.id}
            type="button"
            onClick={() => setActif(p.id)}
            className={`-mb-px shrink-0 rounded-t-md border px-3 py-1.5 text-xs ${
              p.id === actif
                ? 'border-ink-200 border-b-white bg-white font-medium text-ink-900'
                : 'border-transparent text-ink-500 hover:text-ink-800'
            }`}
            title={p.nom_fichier ?? undefined}
          >
            {libellePiece(p.type_piece, p.intitule_libre)}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 bg-ink-50">
        {erreur && <p className="p-4 text-sm text-red-700">{erreur}</p>}
        {!erreur && !url && (
          <div className="flex h-full items-center justify-center">
            <Spinner />
          </div>
        )}
        {url && estPdf && (
          <iframe title={piece?.nom_fichier ?? 'document'} src={url} className="h-full w-full bg-white" />
        )}
        {url && estImage && (
          <div className="h-full overflow-auto bg-white p-2">
            <img src={url} alt={piece?.nom_fichier ?? 'document'} className="mx-auto max-w-full" />
          </div>
        )}
        {url && !estPdf && !estImage && (
          <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center text-sm text-ink-600">
            <p>Ce document ({piece?.nom_fichier}) ne s&apos;affiche pas dans la page.</p>
            <a href={url} download={piece?.nom_fichier ?? undefined} className="btn-secondary">
              L&apos;ouvrir
            </a>
          </div>
        )}
      </div>
    </div>
  )
}

/** Ce qu'il faut vérifier contre le document, et les décisions. */
function Verification({
  candidature,
  onConfirme,
  onDossierComplet,
  onSale,
}: {
  candidature: Candidature
  onConfirme: () => void
  onDossierComplet: () => void
  onSale: (sale: boolean) => void
}) {
  const queryClient = useQueryClient()
  const c = candidature
  const a = c.candidat
  const annulable = useAnnulable()
  const [erreur, setErreur] = useState<string | null>(null)
  const [justifs, setJustifs] = useState<Record<string, string>>({})
  const [appreciation, setAppreciation] = useState(
    c.appreciation_consistance === null ? '' : String(c.appreciation_consistance),
  )
  const [appreciationMotif, setAppreciationMotif] = useState(c.appreciation_motif ?? '')

  const sale =
    appreciation !== (c.appreciation_consistance === null ? '' : String(c.appreciation_consistance)) ||
    appreciationMotif !== (c.appreciation_motif ?? '')
  useEffect(() => onSale(sale), [sale, onSale])

  const rafraichir = () => {
    void queryClient.invalidateQueries({ queryKey: ['candidature', c.id] })
    void queryClient.invalidateQueries({ queryKey: ['candidatures'] })
    void queryClient.invalidateQueries({ queryKey: ['grille'] })
  }

  const confirmer = useMutation({
    mutationFn: () =>
      recrutementApi.verifier(c.id, { etat_civil: true, diplomes: true, experiences: true }),
    onSuccess: () => {
      rafraichir()
      onConfirme()
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Confirmation impossible'),
  })
  const depouiller = useMutation({
    mutationFn: () => recrutementApi.depouiller(c.id),
    onSuccess: rafraichir,
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Lecture impossible'),
  })
  const lever = useMutation({
    mutationFn: (p: { motif: string; justification: string }) =>
      recrutementApi.leverMotif(c.id, p.motif, p.justification),
    onSuccess: rafraichir,
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Levée impossible'),
  })
  const compter = useMutation({
    mutationFn: (p: { experience: string; domaine: string; compte: boolean }) =>
      recrutementApi.compterExperience(c.id, p.experience, p.domaine, p.compte),
    onSuccess: rafraichir,
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Modification impossible'),
  })
  const apprecier = useMutation({
    mutationFn: () =>
      recrutementApi.apprecier(
        c.id,
        appreciation.trim() === '' ? null : Number(appreciation.replace(',', '.')),
        appreciationMotif.trim(),
      ),
    onSuccess: rafraichir,
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Appréciation refusée'),
  })

  const aConfirmer =
    (a.provenance === 'EXTRAIT_IA' ? 1 : 0) +
    a.diplomes.filter((d) => d.provenance === 'EXTRAIT_IA').length +
    a.experiences.filter((e) => e.provenance === 'EXTRAIT_IA').length
  const rienDeLu = a.diplomes.length === 0 && a.experiences.length === 0
  const motifs = c.eliminations.filter((e) => !e.leve_le)
  const n = c.notation

  const confirmerAvecGarde = () => {
    if (rienDeLu) {
      if (!window.confirm("Aucun diplôme ni aucune expérience n'est saisi. Confirmer quand même ?")) return
    }
    confirmer.mutate()
  }

  // C : confirmer, depuis le clavier. Exposé au parent par un évènement.
  useEffect(() => {
    const ecouter = () => confirmerAvecGarde()
    window.addEventListener('revue:confirmer', ecouter)
    return () => window.removeEventListener('revue:confirmer', ecouter)
  })

  return (
    <div className="space-y-4">
      {/* Le résumé : tout ce qu'il faut savoir avant de lire le reste. */}
      <div className="rounded-lg border border-ink-200 bg-white p-3">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="text-lg font-semibold tabular-nums text-ink-900">
            {n ? `${n.total}/${n.total_max}` : '—'}
          </span>
          <span className="text-sm text-ink-700">
            {aConfirmer > 0
              ? `${aConfirmer} élément(s) à vérifier`
              : c.statut === 'A_VERIFIER'
                ? 'Rien de proposé à vérifier'
                : 'Données confirmées'}
            {motifs.length > 0 && ` · ${motifs.length} motif(s) d'élimination`}
          </span>
        </div>
        {n && (
          <details className="mt-1 text-xs text-ink-600">
            <summary className="cursor-pointer text-ink-500">Pourquoi {n.total} ?</summary>
            <ul className="mt-1.5 space-y-1">
              {n.lignes.map((l) => (
                <li key={l.code}>
                  <span className="font-medium text-ink-800">
                    {l.libelle} {l.points}/{l.points_max}
                  </span>
                  {l.detail ? ` — ${l.detail}` : ''}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>

      <SyntheseDossier synthese={c.synthese} />

      {erreur && <Callout tone="danger">{erreur}</Callout>}

      {rienDeLu ? (
        <Callout tone="warning">
          Le document n&apos;a pas encore été lu.{' '}
          <button
            type="button"
            className="font-medium underline"
            disabled={depouiller.isPending}
            onClick={() => depouiller.mutate()}
          >
            {depouiller.isPending ? 'Lecture…' : 'Le lire automatiquement'}
          </button>{' '}
          ou saisissez le parcours dans le dossier complet.
        </Callout>
      ) : null}

      <section>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">Identité</h3>
        <dl className="mt-1.5 grid grid-cols-[auto,1fr] gap-x-3 gap-y-0.5 text-sm">
          {[
            ['Nom', `${a.nom.toUpperCase()} ${a.prenom}`],
            ['Email', a.email],
            ['Téléphone', a.telephone],
            ['Naissance', a.date_naissance ? formatDate(a.date_naissance, 'fr') : null],
            ['Nationalité', a.nationalites.join(', ') || null],
          ]
            .filter(([, v]) => v)
            .map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-ink-500">{k}</dt>
                <dd className="text-ink-900">{v}</dd>
              </div>
            ))}
        </dl>
        {a.provenance === 'EXTRAIT_IA' && (
          <p className="mt-1 text-xs text-amber-800">Identité devinée — à comparer au document.</p>
        )}
      </section>

      <section>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
          Formation ({a.diplomes.length})
        </h3>
        <ul className="mt-1.5 space-y-1 text-sm">
          {a.diplomes.map((d) => (
            <li key={d.id}>
              <span className="font-medium text-ink-900">{d.intitule}</span>
              <Propose provenance={d.provenance} />
              <span className="block text-xs text-ink-500">
                {[d.etablissement, d.domaine, d.annee].filter(Boolean).join(' · ')}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
          Expérience ({a.experiences.length})
        </h3>
        <ul className="mt-1.5 space-y-1 text-sm">
          {a.experiences.map((e) => (
            <li key={e.id}>
              <span className="font-medium text-ink-900">{e.poste}</span>
              <span className="text-ink-700"> — {e.employeur}</span>
              <Propose provenance={e.provenance} />
              <span className="block text-xs text-ink-500">
                {formatMois(e.debut, 'fr')} → {e.fin ? formatMois(e.fin, 'fr') : 'en poste'} ·{' '}
                {duree(e.debut, e.fin)}
                {e.pays ? ` · ${e.pays}` : ''}
              </span>
              {(c.synthese?.domaines_specifiques.length ?? 0) > 0 && (
                <span className="mt-0.5 flex flex-wrap gap-1">
                  {c.synthese?.domaines_specifiques.map((domaine) => {
                    const compte = (e.domaines ?? []).includes(domaine)
                    return (
                      <button
                        key={domaine}
                        type="button"
                        aria-pressed={compte}
                        disabled={compter.isPending}
                        title={
                          compte
                            ? `Compté dans l'expérience en ${domaine}. Cliquer pour le retirer.`
                            : `Compter cette expérience en ${domaine}.`
                        }
                        className={`rounded-full border px-2 py-0.5 text-xs ${
                          compte
                            ? 'border-emerald-300 bg-emerald-50 text-emerald-800'
                            : 'border-ink-200 text-ink-500 hover:border-ink-400'
                        }`}
                        onClick={() =>
                          compter.mutate({ experience: e.id, domaine, compte: !compte })
                        }
                      >
                        {compte ? '✓' : '+'} {domaine}
                      </button>
                    )
                  })}
                </span>
              )}
            </li>
          ))}
        </ul>
      </section>

      {c.statut === 'A_VERIFIER' || aConfirmer > 0 ? (
        <button
          type="button"
          className="btn-primary w-full justify-center"
          disabled={confirmer.isPending}
          onClick={confirmerAvecGarde}
        >
          {confirmer.isPending && <Spinner />}
          Confirmer et passer au suivant <kbd className="ml-1 text-xs opacity-70">C</kbd>
        </button>
      ) : (
        <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          Données confirmées. <kbd className="text-xs">J</kbd> pour le dossier suivant.
        </p>
      )}

      {motifs.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
            Motifs d&apos;élimination
          </h3>
          <ul className="mt-1.5 space-y-2">
            {motifs.map((m) => (
              <li key={m.id} className="rounded-lg border border-amber-200 bg-amber-50/60 p-2.5 text-sm">
                <p className="font-medium text-ink-900">{m.libelle}</p>
                <p className="text-xs text-ink-600">
                  Attendu : {m.attendu ?? '—'} · Constaté : {m.constate ?? '—'}
                </p>
                {m.indice && (
                  <p className="text-xs font-medium text-ink-800">À regarder : {m.indice}</p>
                )}
                {m.sur_donnee_non_verifiee && (
                  <p className="text-xs text-amber-800">
                    {m.indice
                      ? 'Le dossier pourrait le contredire : il n\u2019élimine pas tant que personne n\u2019a relu.'
                      : 'Repose sur une donnée non confirmée : il n\u2019élimine pas encore.'}
                  </p>
                )}
                {/* L'erreur vient souvent du système : un clic suffit. */}
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {RAISONS_DE_LEVEE.map((raison) => (
                    <button
                      key={raison}
                      type="button"
                      className="rounded-full border border-ink-200 bg-white px-2 py-0.5 text-[11px] text-ink-700 hover:border-brand-400"
                      onClick={() =>
                        annulable.programmer(`Levée du motif « ${m.libelle} »…`, () =>
                          lever.mutate({ motif: m.motif, justification: raison }),
                        )
                      }
                    >
                      {raison}
                    </button>
                  ))}
                </div>
                <div className="mt-1.5 flex gap-1.5">
                  <input
                    className="input py-1 text-xs"
                    placeholder="Autre raison (journalisée)"
                    value={justifs[m.motif] ?? ''}
                    onChange={(e) => setJustifs((j) => ({ ...j, [m.motif]: e.target.value }))}
                  />
                  <button
                    type="button"
                    className="btn-ghost shrink-0 px-2.5 py-1 text-xs"
                    disabled={(justifs[m.motif] ?? '').trim().length < 3}
                    onClick={() =>
                      annulable.programmer(`Levée du motif « ${m.libelle} »…`, () =>
                        lever.mutate({ motif: m.motif, justification: justifs[m.motif].trim() }),
                      )
                    }
                  >
                    Lever
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
          Appréciation (motivation, expression écrite)
        </h3>
        <div className="mt-1.5 flex gap-1.5">
          <input
            className="input w-20 py-1 text-sm"
            inputMode="decimal"
            placeholder={`/${c.appreciation_max}`}
            value={appreciation}
            onChange={(e) => setAppreciation(e.target.value)}
          />
          <input
            className="input py-1 text-sm"
            placeholder="Lettre argumentée, expression soignée…"
            value={appreciationMotif}
            onChange={(e) => setAppreciationMotif(e.target.value)}
          />
          <button
            type="button"
            className={`shrink-0 px-2.5 py-1 text-xs ${sale ? 'btn-secondary' : 'btn-ghost'}`}
            disabled={!sale || apprecier.isPending}
            onClick={() => apprecier.mutate()}
          >
            Enregistrer
          </button>
        </div>
        {sale && <p className="mt-1 text-xs text-amber-800">Non enregistré.</p>}
      </section>

      <button type="button" className="btn-ghost w-full justify-center text-xs" onClick={onDossierComplet}>
        Dossier complet — pièces, entretien, courriel, changer de poste… <kbd className="ml-1 opacity-70">E</kbd>
      </button>
      {annulable.bandeau}
    </div>
  )
}

export default function RevuePage() {
  const { posteId = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const [seulementARelire, setSeulementARelire] = useState(params.get('tous') !== '1')
  const [complet, setComplet] = useState(false)
  const sale = useRef(false)
  const surSale = useCallback((v: boolean) => {
    sale.current = v
  }, [])

  const poste = useQuery({ queryKey: ['poste', posteId], queryFn: () => recrutementApi.poste(posteId) })
  const liste = useQuery({
    queryKey: ['candidatures', posteId, 'revue'],
    queryFn: () => recrutementApi.candidatures(posteId, { page_size: 200 }),
  })

  // Les dossiers à relire d'abord, puis les autres par note.
  const file = useMemo(() => {
    const items = [...(liste.data?.items ?? [])]
    items.sort(
      (x, y) =>
        Number(y.a_verifier) - Number(x.a_verifier) || (y.note ?? -1) - (x.note ?? -1),
    )
    return seulementARelire ? items.filter((i) => i.a_verifier) : items
  }, [liste.data, seulementARelire])
  const aRelire = (liste.data?.items ?? []).filter((i) => i.a_verifier).length

  const courantId = params.get('c') ?? file[0]?.id ?? null
  const index = file.findIndex((i) => i.id === courantId)
  const candidature = useQuery({
    queryKey: ['candidature', courantId],
    queryFn: () => recrutementApi.candidature(courantId!),
    enabled: Boolean(courantId),
  })

  const aller = useCallback(
    (item: CandidatureListItem | undefined) => {
      if (!item) return
      if (sale.current && !window.confirm("L'appréciation n'est pas enregistrée. Passer quand même ?"))
        return
      sale.current = false
      const p = new URLSearchParams(params)
      p.set('c', item.id)
      setParams(p, { replace: true })
    },
    [params, setParams],
  )

  const suivant = useCallback(() => aller(file[index + 1]), [aller, file, index])
  const precedent = useCallback(() => aller(file[index - 1]), [aller, file, index])

  useEffect(() => {
    const touche = (e: KeyboardEvent) => {
      const cible = e.target as HTMLElement
      if (complet || ['INPUT', 'TEXTAREA', 'SELECT'].includes(cible.tagName) || cible.isContentEditable)
        return
      if (e.key === 'j' || e.key === 'ArrowDown') suivant()
      else if (e.key === 'k' || e.key === 'ArrowUp') precedent()
      else if (e.key === 'e') setComplet(true)
      else if (e.key === 'c') window.dispatchEvent(new Event('revue:confirmer'))
      else if (e.key === 'Escape') navigate(`/postes/${posteId}`)
      else return
      e.preventDefault()
    }
    window.addEventListener('keydown', touche)
    return () => window.removeEventListener('keydown', touche)
  }, [complet, navigate, posteId, precedent, suivant])

  useEffect(() => {
    const avant = (e: BeforeUnloadEvent) => {
      if (sale.current) e.preventDefault()
    }
    window.addEventListener('beforeunload', avant)
    return () => window.removeEventListener('beforeunload', avant)
  }, [])

  if (liste.isLoading || poste.isLoading) return <PageLoader />
  if (liste.isError) return <ErrorState error={liste.error} onRetry={() => liste.refetch()} />

  const c = candidature.data
  const apresConfirmation = () => {
    // Au suivant encore à relire ; la liste se recharge, l'actuel en sort.
    const prochain = file.slice(index + 1).find((i) => i.a_verifier) ?? file[index + 1]
    sale.current = false
    if (prochain) aller(prochain)
  }

  return (
    <div className="flex h-[calc(100vh-7rem)] min-h-[34rem] flex-col">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Link to={`/postes/${posteId}`} className="btn-ghost px-2 py-1 text-xs">
          ← {poste.data?.intitule ?? 'Poste'}
        </Link>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-base font-semibold text-ink-900">
            {c ? `${c.candidat.nom.toUpperCase()} ${c.candidat.prenom}` : 'Revue des dossiers'}
          </h1>
          {c && (
            <p className="truncate text-xs text-ink-500">
              {LIBELLE_SOURCE[c.source] ?? c.source} le {formatDate(c.recue_le, 'fr')}
              {c.candidat.email ? ` · ${c.candidat.email}` : ''}
            </p>
          )}
        </div>
        <span className="text-xs tabular-nums text-ink-600">
          {index >= 0 ? `${index + 1} / ${file.length}` : `${file.length}`} · {aRelire} à relire
        </span>
        <label className="flex items-center gap-1.5 text-xs text-ink-600">
          <input
            type="checkbox"
            checked={seulementARelire}
            onChange={(e) => setSeulementARelire(e.target.checked)}
          />
          Seulement à relire
        </label>
        <button type="button" className="btn-ghost px-2 py-1 text-xs" disabled={index <= 0} onClick={precedent}>
          ← Précédent
        </button>
        <button
          type="button"
          className="btn-ghost px-2 py-1 text-xs"
          disabled={index < 0 || index >= file.length - 1}
          onClick={suivant}
        >
          Suivant →
        </button>
      </div>

      {file.length === 0 ? (
        <div className="card mx-auto mt-10 max-w-md p-6 text-center">
          <p className="text-sm font-medium text-ink-900">
            {seulementARelire ? 'Plus rien à relire sur ce poste.' : 'Aucun dossier sur ce poste.'}
          </p>
          <p className="mt-1 text-xs text-ink-500">
            {seulementARelire
              ? 'Tous les dossiers ont été confirmés. Décochez « Seulement à relire » pour les parcourir.'
              : 'Déposez des dossiers ou relevez la boîte.'}
          </p>
          <Link to={`/postes/${posteId}`} className="btn-primary mt-4">
            Retour au poste
          </Link>
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <section className="card min-h-[24rem] overflow-hidden lg:min-h-0">
            {c ? <Document candidature={c} /> : <PageLoader />}
          </section>
          <section className="card min-h-0 overflow-y-auto p-4">
            {candidature.isError && (
              <ErrorState error={candidature.error} onRetry={() => candidature.refetch()} />
            )}
            {c && (
              <Verification
                key={c.id}
                candidature={c}
                onConfirme={apresConfirmation}
                onDossierComplet={() => setComplet(true)}
                onSale={surSale}
              />
            )}
            <p className="mt-4 hidden text-[11px] text-ink-400 lg:block">{TOUCHES}</p>
          </section>
        </div>
      )}

      {complet && courantId && (
        <CandidatureDrawer
          candidatureId={courantId}
          posteId={posteId}
          onClose={() => setComplet(false)}
          onSupprime={() => {
            setComplet(false)
            suivant()
          }}
          onDeplace={() => {
            setComplet(false)
            suivant()
          }}
        />
      )}
    </div>
  )
}
