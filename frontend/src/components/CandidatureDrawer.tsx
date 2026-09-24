import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, rapportsApi, recrutementApi } from '@/lib/api'
import { LIBELLE_PIECE, libellePiece } from '@/lib/pieces'
import { Callout, ErrorState, Spinner } from '@/components/ui'
import EnvoyerAuxCandidats from '@/components/EnvoyerAuxCandidats'
import { formatDateTime, formatMois } from '@/lib/format'
import type { Elimination, Provenance } from '@/types'

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

/**
 * L'appréciation humaine de la consistance du dossier.
 *
 * Le barème du cabinet note la consistance sur 3 points : complétude et
 * cohérence chronologique se constatent, la motivation et l'expression écrite
 * se lisent. Ce dernier point n'est donc ni calculé ni proposé par un modèle —
 * il demande qu'un recruteur ouvre le dossier, et une raison écrite, pour
 * rester opposable à un candidat qui conteste.
 */
function Appreciation({
  candidatureId,
  valeur,
  motifActuel,
  plafond,
  onFait,
}: {
  candidatureId: string
  valeur: number | null
  motifActuel: string | null
  plafond: number
  onFait: () => void
}) {
  const [note, setNote] = useState(valeur === null ? '' : String(valeur))
  const [motif, setMotif] = useState(motifActuel ?? '')
  const [erreur, setErreur] = useState<string | null>(null)

  const enregistrer = useMutation({
    mutationFn: () =>
      recrutementApi.apprecier(candidatureId, note === '' ? null : Number(note), motif),
    onSuccess: () => {
      setErreur(null)
      onFait()
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Enregistrement impossible'),
  })

  return (
    <div className="rounded-lg border border-ink-200 p-3">
      <p className="text-sm font-medium text-ink-800">
        Appréciation du dossier
        {valeur === null && (
          <span className="ml-1.5 rounded bg-sky-100 px-1.5 py-0.5 text-[10px] font-medium text-sky-800">
            à porter
          </span>
        )}
      </p>
      <p className="mt-0.5 text-xs text-ink-500">
        Motivation et expression écrite, jusqu'à {plafond} point(s). Le reste de la consistance
        — complétude et cohérence du parcours — est déjà calculé.
      </p>

      <div className="mt-2 flex flex-wrap items-start gap-2">
        <input
          type="number"
          min={0}
          max={plafond}
          step={0.5}
          className="input w-20"
          value={note}
          aria-label="Points d'appréciation"
          onChange={(e) => setNote(e.target.value)}
        />
        <input
          className="input min-w-0 flex-1"
          value={motif}
          placeholder="Lettre argumentée, expression soignée…"
          aria-label="Motif de l'appréciation"
          onChange={(e) => setMotif(e.target.value)}
        />
        <button
          type="button"
          className="btn-ghost px-3 py-1.5 text-xs"
          disabled={enregistrer.isPending}
          onClick={() => enregistrer.mutate()}
        >
          {enregistrer.isPending && <Spinner />}
          Enregistrer
        </button>
      </div>

      {erreur && <p className="mt-2 text-xs text-red-700">{erreur}</p>}
    </div>
  )
}

/**
 * L'entretien structuré : les 70 points de la seconde étape.
 *
 * Rien n'est calculé ici. Ces points sont un jugement porté par un jury en
 * séance, et l'assistance automatique n'y a aucune part. Le panneau se borne à
 * les recueillir, à borner chaque note par son maximum et à additionner.
 *
 * La grille entière est affichée d'emblée, critères non notés compris : un
 * jury doit voir ce qu'il lui reste à faire. Tant qu'un critère manque, la note
 * sur 100 est annoncée comme partielle — un acquis en cours de séance ne se lit
 * pas comme un résultat.
 */
function PanneauEntretien({
  candidatureId,
  onFait,
}: {
  candidatureId: string
  onFait: () => void
}) {
  const fiche = useQuery({
    queryKey: ['entretien', candidatureId],
    queryFn: () => recrutementApi.entretien(candidatureId),
  })

  const [jure, setJure] = useState('')
  const [notes, setNotes] = useState<Record<string, string>>({})
  const [commentaires, setCommentaires] = useState<Record<string, string>>({})
  const [date, setDate] = useState('')
  const [jury, setJury] = useState('')
  const [observations, setObservations] = useState('')
  const [erreur, setErreur] = useState<string | null>(null)
  const [ouvert, setOuvert] = useState(false)

  const f = fiche.data
  const enCours = f?.fiches.find((x) => x.jure === jure)

  // Le formulaire part de l'état du serveur, jamais d'une valeur inventée. Il
  // se recharge à chaque changement de juré : c'est ainsi qu'on corrige une
  // fiche déjà saisie sans toucher à celles des autres.
  useEffect(() => {
    if (!f) return
    setJury(f.jury ?? '')
    const source = f.fiches.find((x) => x.jure === jure)
    const lignes = source?.lignes ?? f.grille
    setNotes(
      Object.fromEntries(
        lignes.map((l) => [l.code, l.points === null || l.points === undefined ? '' : String(l.points)]),
      ),
    )
    setCommentaires(Object.fromEntries(lignes.map((l) => [l.code, l.commentaire ?? ''])))
    setDate(source?.date_entretien ?? '')
    setObservations(source?.observations ?? '')
    if (f.existe) setOuvert(true)
  }, [f, jure])

  const enregistrer = useMutation({
    mutationFn: () =>
      recrutementApi.saisirEntretien(candidatureId, {
        jure: jure.trim() || 'Jury',
        lignes: (fiche.data?.grille ?? []).map((l) => ({
          code: l.code,
          points:
            notes[l.code] === '' || notes[l.code] === undefined ? null : Number(notes[l.code]),
          commentaire: commentaires[l.code] ?? '',
        })),
        date_entretien: date || null,
        jury,
        observations,
      }),
    onSuccess: () => {
      setErreur(null)
      void fiche.refetch()
      onFait()
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Enregistrement impossible'),
  })

  const effacer = useMutation({
    mutationFn: (cible: string | undefined) =>
      recrutementApi.effacerEntretien(candidatureId, cible),
    onSuccess: () => {
      setErreur(null)
      setJure('')
      void fiche.refetch()
      onFait()
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Effacement impossible'),
  })

  if (fiche.isLoading) return <Spinner />
  if (fiche.isError) return <ErrorState error={fiche.error} onRetry={() => fiche.refetch()} />
  if (!f) return null

  // Total de ce qui est actuellement à l'écran, pour que le juré voie où il en
  // est sans attendre un aller-retour serveur.
  const totalSaisi = f.grille.reduce(
    (somme, l) => somme + (notes[l.code] ? Number(notes[l.code]) : 0),
    0,
  )
  const tousNotes = f.grille.every((l) => notes[l.code] !== '' && notes[l.code] !== undefined)
  // En tête, la note qui compte : la moyenne du panel tant qu'aucune fiche
  // n'est ouverte, le brouillon en cours dès qu'un juré est choisi. Afficher
  // « 0/70 » au-dessus de « moyenne 59/70 » se lisait comme une contradiction.
  const enSaisie = jure.trim().length > 0
  const noteAffichee = enSaisie ? totalSaisi : f.total

  if (!ouvert) {
    return (
      <button
        type="button"
        className="btn-ghost w-full justify-center py-2 text-xs"
        onClick={() => setOuvert(true)}
      >
        Saisir l&apos;entretien ({f.total_max} points)
      </button>
    )
  }

  return (
    <div className="rounded-lg border border-ink-200 p-3">
      <div className="flex flex-wrap items-baseline gap-2">
        <p className="text-sm font-medium text-ink-800">
          Entretien
          {enSaisie && (
            <span className="ml-1 font-normal text-ink-500">— fiche en cours</span>
          )}
        </p>
        <span className="ml-auto text-sm font-semibold tabular-nums text-ink-900">
          {Number.isInteger(noteAffichee) ? noteAffichee : noteAffichee.toFixed(2)}
          <span className="text-ink-400">/{f.total_max}</span>
        </span>
      </div>
      <p className="mt-0.5 text-xs text-ink-500">
        Points attribués par le jury. Rien n&apos;est calculé ni proposé ici.
        {enSaisie && !tousNotes
          ? " Tant qu'un critère manque, la note sur 100 reste partielle."
          : ''}
      </p>

      {/* Les fiches déjà saisies. La note retenue est leur moyenne : le
          cabinet fait siéger un panel, et chacun note de son côté. */}
      {f.fiches.length > 0 && (
        <div className="mt-3 rounded-lg bg-ink-50 p-2">
          <p className="text-xs font-medium text-ink-700">
            {f.fiches.length} fiche{f.fiches.length > 1 ? 's' : ''} — moyenne{' '}
            <span className="tabular-nums">
              {f.total.toFixed(2)}/{f.total_max}
            </span>
            {f.ecart_jures !== null && f.ecart_jures > 0 && (
              <span className="ml-1 font-normal text-ink-500">
                (écart entre jurés : {f.ecart_jures.toFixed(1)} pt)
              </span>
            )}
          </p>
          <ul className="mt-1.5 space-y-1">
            {f.fiches.map((fj) => (
              <li key={fj.jure} className="flex items-center gap-2 text-xs">
                <button
                  type="button"
                  className={`min-w-0 flex-1 truncate text-left ${
                    fj.jure === jure ? 'font-medium text-brand-700' : 'text-ink-700 hover:underline'
                  }`}
                  onClick={() => setJure(fj.jure === jure ? '' : fj.jure)}
                >
                  {fj.jure}
                </button>
                <span className="tabular-nums text-ink-600">
                  {fj.total.toFixed(1)}/{f.total_max}
                </span>
                {!fj.complet && <span className="text-amber-700">partielle</span>}
                <button
                  type="button"
                  className="text-red-700 hover:underline"
                  disabled={effacer.isPending}
                  onClick={() => effacer.mutate(fj.jure)}
                  aria-label={`Effacer la fiche de ${fj.jure}`}
                >
                  Effacer
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <input
        className="input mt-3"
        value={jure}
        placeholder="Nom du juré qui note"
        aria-label="Juré"
        onChange={(e) => setJure(e.target.value)}
      />
      <p className="mt-1 text-xs text-ink-500">
        {enCours
          ? `Vous corrigez la fiche de ${enCours.jure}.`
          : 'Une fiche par juré. Enregistrer ne touche pas à celles des autres.'}
      </p>

      <div className="mt-3 space-y-2">
        {f.grille.map((l) => (
          <div key={l.code} className="rounded-lg bg-ink-50 px-3 py-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="min-w-0 flex-1 text-sm text-ink-800">
                {l.libelle}
                {l.section && <span className="ml-1 text-xs text-ink-400">· {l.section}</span>}
              </span>
              <input
                type="number"
                min={0}
                max={l.points_max}
                step={0.5}
                className="input w-20 py-1"
                value={notes[l.code] ?? ''}
                aria-label={l.libelle}
                onChange={(e) => setNotes((n) => ({ ...n, [l.code]: e.target.value }))}
              />
              <span className="w-10 text-xs text-ink-400">/{l.points_max}</span>
            </div>
            <input
              className="input mt-1.5 py-1 text-xs"
              value={commentaires[l.code] ?? ''}
              placeholder="Ce qui a été observé…"
              aria-label={`Commentaire — ${l.libelle}`}
              onChange={(e) => setCommentaires((c) => ({ ...c, [l.code]: e.target.value }))}
            />
          </div>
        ))}
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <input
          type="date"
          className="input"
          value={date}
          aria-label="Date de l'entretien"
          onChange={(e) => setDate(e.target.value)}
        />
        <input
          className="input"
          value={jury}
          placeholder="Composition du jury"
          aria-label="Jury"
          onChange={(e) => setJury(e.target.value)}
        />
      </div>
      <textarea
        className="input mt-2"
        rows={2}
        value={observations}
        placeholder="Observations générales…"
        aria-label="Observations"
        onChange={(e) => setObservations(e.target.value)}
      />

      {f.existe && (
        <div className="mt-3 rounded-lg bg-ink-50 px-3 py-2 text-xs text-ink-600">
          Présélection {f.preselection_sur_cent}/100 + entretien {f.entretien_sur_cent}/100 ={' '}
          <strong className="text-ink-900">{f.note_finale_sur_cent}/100</strong>
          {!f.complet && ' — partiel, tous les critères ne sont pas notés.'}
        </div>
      )}

      {erreur && <p className="mt-2 text-xs text-red-700">{erreur}</p>}

      <div className="mt-3 flex flex-wrap justify-end gap-2">
        {f.fiches.length > 0 && (
          <button
            type="button"
            className="btn-ghost px-3 py-1.5 text-xs text-red-700 hover:bg-red-50"
            disabled={effacer.isPending}
            onClick={() => effacer.mutate(undefined)}
          >
            Effacer toutes les fiches
          </button>
        )}
        <button
          type="button"
          className="btn-ghost px-3 py-1.5 text-xs"
          disabled={enregistrer.isPending}
          onClick={() => enregistrer.mutate()}
        >
          {enregistrer.isPending && <Spinner />}
          {enCours ? 'Mettre à jour cette fiche' : 'Enregistrer cette fiche'}
        </button>
      </div>
    </div>
  )
}

/**
 * La suppression d'un dossier, dépliée sous le reste.
 *
 * Repliée par défaut et sans couleur d'alerte tant qu'on ne l'ouvre pas : le
 * geste est rare, et une zone rouge permanente en bas d'un tiroir consulté
 * vingt fois par jour finit par ne plus rien signifier. Le motif est exigé
 * avant le bouton, pas après — c'est ce que le journal gardera du dossier.
 */
function SupprimerDossier({
  candidatureId,
  nom,
  onSupprime,
}: {
  candidatureId: string
  nom: string
  onSupprime: (compteRendu: string) => void
}) {
  const [ouvert, setOuvert] = useState(false)
  const [motif, setMotif] = useState('')
  const [erreur, setErreur] = useState<string | null>(null)
  // Renseigné quand le serveur a retenu le dossier : il faut alors redemander
  // en connaissance de cause.
  const [aConfirmer, setAConfirmer] = useState(false)

  const supprimer = useMutation({
    mutationFn: (confirmer: boolean) =>
      recrutementApi.supprimerCandidature(candidatureId, motif.trim(), confirmer),
    onSuccess: (r) => {
      const parts = [`Dossier de ${nom} supprimé`]
      if (r.pieces_supprimees) parts.push(`${r.pieces_supprimees} pièce(s) effacée(s)`)
      if (r.profil_supprime) parts.push('profil retiré du vivier')
      if (r.courriels_conserves)
        parts.push(`${r.courriels_conserves} courriel(s) conservés comme preuve d'envoi`)
      onSupprime(`${parts.join(' · ')}.`)
    },
    onError: (e) => {
      const message = e instanceof Error ? e.message : 'Suppression impossible'
      setErreur(message)
      // 409 : le refus porte sur ce que le dossier contient, pas sur une
      // panne. C'est le seul cas où insister a un sens.
      setAConfirmer(e instanceof ApiError && e.status === 409)
    },
  })

  if (!ouvert) {
    return (
      <div className="border-t border-ink-100 pt-4">
        <button
          type="button"
          className="text-xs font-medium text-ink-500 hover:text-red-700 hover:underline"
          onClick={() => setOuvert(true)}
        >
          Supprimer ce dossier
        </button>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-red-200 bg-red-50/60 p-4">
      <p className="text-sm font-semibold text-red-900">Supprimer ce dossier</p>
      <p className="mt-1 text-xs text-ink-600">
        Pour un dossier entré par erreur — mauvais fichier, saisie en double, mauvais poste. Le
        dossier, ses pièces et sa notation disparaissent. Le journal garde le nom, le poste, la
        note et le motif ci-dessous. Les courriels déjà partis sont conservés : ils valent preuve
        d&apos;envoi.
      </p>
      <textarea
        className="input mt-3 text-sm"
        rows={2}
        value={motif}
        placeholder="Motif — ex. : dossier déposé deux fois, celui-ci est le doublon"
        onChange={(e) => {
          setMotif(e.target.value)
          setErreur(null)
          setAConfirmer(false)
        }}
      />
      {erreur && (
        <div className="mt-2">
          <Callout tone="danger">{erreur}</Callout>
        </div>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="rounded-lg bg-red-700 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-red-800 disabled:opacity-50"
          disabled={motif.trim().length < 3 || supprimer.isPending}
          onClick={() => supprimer.mutate(aConfirmer)}
        >
          {supprimer.isPending && <Spinner />}
          {aConfirmer ? 'Supprimer quand même' : 'Supprimer définitivement'}
        </button>
        <button
          type="button"
          className="btn-ghost px-3 py-1.5 text-xs"
          onClick={() => {
            setOuvert(false)
            setMotif('')
            setErreur(null)
            setAConfirmer(false)
          }}
        >
          Annuler
        </button>
        {motif.trim().length < 3 && (
          <span className="text-xs text-ink-500">Le motif est obligatoire.</span>
        )}
      </div>
    </div>
  )
}

export default function CandidatureDrawer({
  candidatureId,
  posteId,
  onClose,
  onSupprime,
}: {
  candidatureId: string
  posteId: string
  onClose: () => void
  onSupprime?: (compteRendu: string) => void
}) {
  const queryClient = useQueryClient()
  const fichierRef = useRef<HTMLInputElement>(null)
  const [typePiece, setTypePiece] = useState('CV')
  const [erreur, setErreur] = useState<string | null>(null)
  const [compteRendu, setCompteRendu] = useState<string | null>(null)
  const [avertissements, setAvertissements] = useState<string[]>([])
  // La pièce dont le retrait attend un second clic.
  const [pieceARetirer, setPieceARetirer] = useState<string | null>(null)
  // Fenêtre d'envoi ouverte sur ce seul dossier.
  const [ecrire, setEcrire] = useState(false)

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
      const remplacement = resultat.remplacees
        ? ` ${resultat.remplacees} proposition(s) précédente(s) remplacée(s).`
        : ''
      // L'adresse lue dans le CV est ce qui rend le dossier joignable : elle
      // mérite d'être annoncée, pas découverte au moment d'un envoi raté.
      if (resultat.email_trouve) {
        parts.push(`adresse relevée : ${resultat.email_trouve}`)
      }
      setCompteRendu(
        parts.length
          ? `Proposé : ${parts.join(', ')}. À relire avant confirmation.${remplacement}`
          : "Rien n'a pu être lu dans les pièces.",
      )
      setAvertissements(resultat.avertissements)
      rafraichir()
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Dépouillement impossible'),
  })

  /**
   * Joindre des pièces au dossier.
   *
   * Un seul fichier part avec le type choisi au-dessus — c'est le geste
   * délibéré. Plusieurs fichiers, ou une archive, passent par le rattachement
   * en lot : leur type est alors déduit de leur nom, parce qu'imposer un seul
   * type à un lot hétérogène le classerait faux.
   */
  const joindre = useMutation({
    mutationFn: (fichiers: File[]) =>
      fichiers.length === 1 && !fichiers[0].name.toLowerCase().endsWith('.zip')
        ? recrutementApi.joindrePiece(candidatureId, typePiece, fichiers[0])
        : recrutementApi.joindrePieces(candidatureId, fichiers),
    onSuccess: () => {
      setErreur(null)
      rafraichir()
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Dépôt impossible'),
  })

  /**
   * Retirer une pièce déposée par erreur.
   *
   * Le fichier part, et le dossier est réévalué : une pièce manquante peut
   * rouvrir un motif d'élimination qu'elle levait. Le geste est fréquent — un
   * CV rattaché au mauvais candidat lors d'un dépôt en lot — et ne justifie
   * pas de supprimer tout le dossier.
   */
  const retirer = useMutation({
    mutationFn: (pieceId: string) => recrutementApi.retirerPiece(candidatureId, pieceId),
    onSuccess: () => {
      setErreur(null)
      setPieceARetirer(null)
      rafraichir()
    },
    onError: (e) => {
      setPieceARetirer(null)
      setErreur(e instanceof Error ? e.message : 'Retrait impossible')
    },
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

  // Le dossier porte-t-il déjà des lignes proposées par l'extraction ? Le
  // bouton dit alors « relancer » plutôt que « dépouiller » : le geste est le
  // même, mais il remplace au lieu d'ajouter, et l'écran ne doit pas le taire.
  const aDesPropositions =
    (c?.candidat.diplomes ?? []).some((d) => d.provenance === 'EXTRAIT_IA') ||
    (c?.candidat.experiences ?? []).some((e) => e.provenance === 'EXTRAIT_IA')

  return (
    // Le voile s'estompe, le tiroir vient du bord droit : le dossier se lit
    // comme un détail ouvert par-dessus la grille, pas comme un autre écran.
    <div
      className="fixed inset-0 z-50 flex animate-fade-in justify-end bg-ink-900/40"
      onClick={onClose}
    >
      <aside
        className="h-full w-full max-w-xl animate-slide-in overflow-y-auto bg-white shadow-drawer"
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
          {/* Écrire à une personne, et non à une portée. Le geste courant est
              individuel — réclamer une pièce, convoquer, répondre à une
              relance — et il n'existait que sous forme d'envoi groupé depuis
              la grille, ce qui obligeait à passer par une liste pour écrire à
              quelqu'un qu'on avait déjà sous les yeux. */}
          {c && (
            <button
              type="button"
              className="btn-ghost px-2 py-1 text-xs"
              disabled={!c.candidat.email}
              title={
                c.candidat.email
                  ? `Écrire à ${c.candidat.email}`
                  : "Ce dossier n'a pas d'adresse email : le dépouillement peut la lire dans le CV."
              }
              onClick={() => setEcrire(true)}
            >
              Écrire
            </button>
          )}
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
                  {/* Le bouton n'apparaissait que sur un dossier entièrement
                      vide : un dossier mal lu la première fois ne pouvait plus
                      l'être autrement qu'en le supprimant et en le redéposant.
                      Un second passage remplace ce que le premier avait
                      proposé, et rien d'autre — ce qui est saisi ou confirmé
                      arrête le dépouillement, qui le dit alors. */}
                  <button
                    type="button"
                    className="btn-ghost py-1.5 text-xs"
                    disabled={depouiller.isPending}
                    onClick={() => depouiller.mutate()}
                  >
                    {depouiller.isPending && <Spinner />}
                    {aDesPropositions ? 'Relancer le dépouillement' : 'Dépouiller le dossier'}
                  </button>
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
                <p className="mb-2 text-xs text-ink-500">
                  La présélection compte pour 30 % de la note finale ; les entretiens portent
                  les 70 % restants.
                </p>
                <div className="mb-2">
                  <Appreciation
                    candidatureId={candidatureId}
                    valeur={c.appreciation_consistance}
                    motifActuel={c.appreciation_motif}
                    plafond={c.appreciation_max}
                    onFait={rafraichir}
                  />
                </div>
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

                <div className="mt-3">
                  <PanneauEntretien candidatureId={candidatureId} onFait={rafraichir} />
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
                        {/* Le nom donné par le candidat l'emporte : « Lettre de
                            recommandation — BOAD » en dit plus que « Autre
                            document », qui est tout ce que le code exprime. */}
                        {libellePiece(piece.type_piece, piece.intitule_libre)}
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
                    {/* Deux temps plutôt qu'une boîte de dialogue : le reste
                        de l'application demande confirmation sur place, et un
                        clic mal placé effacerait un fichier. */}
                    <button
                      type="button"
                      className={`text-xs font-medium hover:underline disabled:opacity-50 ${
                        pieceARetirer === piece.id
                          ? 'text-red-700'
                          : 'text-ink-400 hover:text-red-700'
                      }`}
                      disabled={retirer.isPending}
                      title="Retirer cette pièce du dossier — le fichier est effacé et le dossier réévalué"
                      onClick={() => {
                        if (pieceARetirer === piece.id) retirer.mutate(piece.id)
                        else setPieceARetirer(piece.id)
                      }}
                    >
                      {pieceARetirer === piece.id ? 'Confirmer le retrait' : 'Retirer'}
                    </button>
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
                  multiple
                  accept=".pdf,.docx,.doc,.zip"
                  className="hidden"
                  onChange={(e) => {
                    const fichiers = Array.from(e.target.files ?? [])
                    if (fichiers.length) joindre.mutate(fichiers)
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
                  Joindre des fichiers
                </button>
              </div>
              <p className="mt-1.5 text-xs text-ink-500">
                Un seul fichier prend le type choisi ci-dessus. Plusieurs fichiers — ou une
                archive <code className="rounded bg-ink-100 px-1">.zip</code> — sont classés
                d&apos;après leur nom.
              </p>

              <div className="mt-3 border-t border-ink-100 pt-3">
                <p className="text-sm font-medium text-ink-800">CV à en-tête du cabinet</p>
                <p className="mt-0.5 text-xs text-ink-500">
                  Reconstitué depuis le parcours du dossier, pour livrer au client des
                  dossiers de présentation uniforme. Refusé tant que le parcours n&apos;a pas
                  été relu.
                </p>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  {(['docx', 'pdf'] as const).map((f) => (
                    <button
                      key={f}
                      type="button"
                      className="btn-ghost px-3 py-1.5 text-xs"
                      onClick={() =>
                        rapportsApi
                          .cvMaison(candidatureId, { format: f })
                          .catch((e) =>
                            setErreur(e instanceof Error ? e.message : 'Export impossible'),
                          )
                      }
                    >
                      {f === 'docx' ? 'Word' : 'PDF'}
                    </button>
                  ))}
                  <button
                    type="button"
                    className="btn-ghost px-3 py-1.5 text-xs"
                    title="Sans email, téléphone ni adresse — pour comparer les parcours."
                    onClick={() =>
                      rapportsApi
                        .cvMaison(candidatureId, { format: 'docx', avecCoordonnees: false })
                        .catch((e) =>
                          setErreur(e instanceof Error ? e.message : 'Export impossible'),
                        )
                    }
                  >
                    Word, anonymisé
                  </button>
                </div>
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
                      {formatMois(e.debut, 'fr')} → {e.fin ? formatMois(e.fin, 'fr') : 'en cours'}
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

            <SupprimerDossier
              candidatureId={candidatureId}
              nom={`${c.candidat.nom.toUpperCase()} ${c.candidat.prenom}`}
              onSupprime={(compteRendu) => {
                void queryClient.invalidateQueries({ queryKey: ['grille', posteId] })
                void queryClient.invalidateQueries({ queryKey: ['candidatures', posteId] })
                void queryClient.invalidateQueries({ queryKey: ['vivier'] })
                onSupprime?.(compteRendu)
                onClose()
              }}
            />
          </div>
        )}
      </aside>

      {/* La même fenêtre que depuis la grille, sur un seul dossier : le texte
          est montré avant de partir, et l'envoi passe par le même chemin —
          rien de particulier n'est fait pour un destinataire unique. */}
      {ecrire && c && (
        <EnvoyerAuxCandidats
          candidatureIds={[candidatureId]}
          onClose={() => setEcrire(false)}
        />
      )}
    </div>
  )
}
