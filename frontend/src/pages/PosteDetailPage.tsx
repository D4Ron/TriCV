import { useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { recrutementApi } from '@/lib/api'
import {
  Callout,
  CopyField,
  EmptyState,
  ErrorState,
  Field,
  Modal,
  PageLoader,
  Spinner,
} from '@/components/ui'
import CandidatureDrawer from '@/components/CandidatureDrawer'
import type { Avis, LigneGrille, Poste } from '@/types'

type Onglet = 'preselection' | 'sous_seuil' | 'elimination' | 'a_verifier'

const NIVEAUX: Record<number, string> = {
  0: 'BAC',
  1: 'BAC+1',
  2: 'BAC+2',
  3: 'BAC+3 (Licence)',
  4: 'BAC+4 (Maîtrise, Master 1)',
  5: 'BAC+5 (Master, Ingénieur)',
  8: 'BAC+8 (Doctorat)',
}

const LIBELLE_PIECE: Record<string, string> = {
  LETTRE_MOTIVATION: 'Lettre de motivation',
  CV: 'CV détaillé',
  COPIE_DIPLOMES: 'Copie des diplômes',
  ATTESTATIONS_TRAVAIL: 'Attestations de travail',
  PIECE_IDENTITE: "Pièce d'identité",
  CERTIFICAT_NATIONALITE: 'Certificat de nationalité',
}

const LIBELLE_TYPE_AVIS: Record<string, string> = {
  NATIONAL: 'Avis national',
  INTERNATIONAL: 'Avis international',
  GRE_A_GRE: 'Gré à gré',
}

const LIBELLE_STATUT_AVIS: Record<string, string> = {
  BROUILLON: 'Brouillon',
  PUBLIE: 'Publié',
  CLOTURE: 'Clôturé',
}

function Statistique({
  valeur,
  libelle,
  ton,
  actif,
  onClick,
}: {
  valeur: number
  libelle: string
  ton: string
  actif?: boolean
  onClick?: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!onClick}
      className={`card px-4 py-3 text-left transition-colors ${
        onClick ? 'hover:border-ink-300' : ''
      } ${actif ? 'border-ink-900' : ''}`}
    >
      <p className={`text-2xl font-semibold tabular-nums ${ton}`}>{valeur}</p>
      <p className="mt-0.5 text-xs text-ink-500">{libelle}</p>
    </button>
  )
}

/** Le rappel des exigences : c'est la fiche de poste, pas l'avis publié. */
function FichePoste({ poste }: { poste: Poste }) {
  const lignes: Array<[string, string]> = [
    ['Diplôme exigé', NIVEAUX[poste.niveau_min] ?? `BAC+${poste.niveau_min}`],
    [
      'Domaines acceptés',
      poste.domaines_acceptes.length ? poste.domaines_acceptes.join(', ') : 'tous',
    ],
    ['Expérience générale', `${poste.annees_experience_min} an(s)`],
    [
      'Dont expérience spécifique',
      `${poste.annees_experience_specifique_min} an(s)${
        poste.domaines_experience.length ? ` en ${poste.domaines_experience.join(', ')}` : ''
      }`,
    ],
    [
      'Pièces exigées',
      poste.pieces_requises.map((c) => LIBELLE_PIECE[c] ?? c).join(', ') || 'aucune',
    ],
    [
      'Pièces facultatives',
      poste.pieces_facultatives.map((c) => LIBELLE_PIECE[c] ?? c).join(', ') || 'aucune',
    ],
    ['Formats acceptés', 'PDF ou Word'],
    ['Postes à pourvoir', String(poste.nombre_a_pourvoir)],
  ]

  return (
    <section className="card p-4">
      <h2 className="mb-3 text-sm font-semibold text-ink-900">Fiche de poste</h2>
      <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
        {lignes.map(([cle, valeur]) => (
          <div key={cle} className="min-w-0">
            <dt className="text-xs text-ink-500">{cle}</dt>
            <dd className="truncate text-sm text-ink-800" title={valeur}>
              {valeur}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

function PanneauAvis({ posteId }: { posteId: string }) {
  const queryClient = useQueryClient()
  const [ouvert, setOuvert] = useState(false)
  const [reference, setReference] = useState('')
  const [type, setType] = useState('NATIONAL')
  const [cloture, setCloture] = useState('')
  const [erreur, setErreur] = useState<string | null>(null)

  const avis = useQuery({ queryKey: ['avis', posteId], queryFn: () => recrutementApi.avis(posteId) })

  const rafraichir = () => {
    void queryClient.invalidateQueries({ queryKey: ['avis', posteId] })
    void queryClient.invalidateQueries({ queryKey: ['grille', posteId] })
  }

  const creer = useMutation({
    mutationFn: () =>
      recrutementApi.creerAvis(posteId, {
        reference: reference.trim() || null,
        type_avis: type,
        date_cloture: cloture || null,
      }),
    onSuccess: () => {
      setOuvert(false)
      setReference('')
      setCloture('')
      rafraichir()
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Création impossible'),
  })

  const publier = useMutation({
    mutationFn: (id: string) => recrutementApi.publierAvis(id),
    onSuccess: rafraichir,
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Publication impossible'),
  })

  const cloturer = useMutation({
    mutationFn: (id: string) => recrutementApi.cloturerAvis(id),
    onSuccess: rafraichir,
  })

  return (
    <section className="card p-4">
      <div className="mb-3 flex items-center gap-2">
        <h2 className="text-sm font-semibold text-ink-900">Avis de recrutement</h2>
        <button
          type="button"
          className="btn-ghost ml-auto px-2 py-1 text-xs"
          onClick={() => setOuvert(true)}
        >
          Nouvel avis
        </button>
      </div>

      <p className="mb-3 text-xs text-ink-500">
        L'avis est tiré de la fiche de poste : il reprend le profil recherché et décrit le
        processus que suivront les candidats.
      </p>

      {erreur && (
        <p className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {erreur}
        </p>
      )}

      {avis.data?.length === 0 && (
        <div className="rounded-lg border border-dashed border-ink-300 px-3 py-3">
          <p className="text-sm font-medium text-ink-800">Étape suivante : créer l'avis</p>
          <p className="mt-1 text-xs text-ink-500">
            Sans avis publié, le poste n'a pas de lien de candidature et sa date de clôture — qui
            sert de référence au calcul de l'âge et de l'ancienneté — n'est pas fixée.
          </p>
        </div>
      )}

      <div className="space-y-2">
        {avis.data?.map((a: Avis) => (
          <div key={a.id} className="rounded-lg border border-ink-200 px-3 py-2.5">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium text-ink-900">
                {a.reference || 'sans référence'}
              </span>
              <span className="badge bg-ink-100 text-ink-700">
                {LIBELLE_TYPE_AVIS[a.type_avis]}
              </span>
              <span
                className={`badge ${
                  a.statut === 'PUBLIE'
                    ? 'bg-emerald-100 text-emerald-800'
                    : a.statut === 'CLOTURE'
                      ? 'bg-ink-100 text-ink-500'
                      : 'bg-amber-100 text-amber-800'
                }`}
              >
                {LIBELLE_STATUT_AVIS[a.statut]}
              </span>
              <span className="ml-auto text-xs text-ink-500">
                {a.date_cloture ? `clôture le ${a.date_cloture}` : 'sans date de clôture'}
              </span>
            </div>

            <div className="mt-2 flex flex-wrap items-center gap-2">
              {a.statut === 'BROUILLON' && (
                <button
                  type="button"
                  className="btn-ghost px-2 py-1 text-xs"
                  disabled={publier.isPending}
                  onClick={() => publier.mutate(a.id)}
                >
                  Publier
                </button>
              )}
              {a.statut === 'PUBLIE' && (
                <>
                  <button
                    type="button"
                    className="btn-ghost px-2 py-1 text-xs"
                    onClick={() => cloturer.mutate(a.id)}
                  >
                    Clôturer
                  </button>
                  <div className="w-full">
                    <CopyField
                      label="Lien de candidature"
                      value={`${window.location.origin}/apply/${a.cle_publique}`}
                    />
                  </div>
                </>
              )}
              {a.reference && (
                <p className="w-full text-xs text-ink-500">
                  Les candidatures reçues par email sont rattachées à cet avis si l'objet
                  contient <code className="rounded bg-ink-100 px-1">[{a.reference}]</code>.
                </p>
              )}
            </div>
          </div>
        ))}
      </div>

      {ouvert && (
        <Modal open title="Nouvel avis de recrutement" onClose={() => setOuvert(false)}>
          <div className="space-y-4">
            <Field
              label="Référence"
              htmlFor="avis-ref"
              hint="Sert à rattacher les candidatures reçues par email, via l'objet du message."
            >
              <input
                id="avis-ref"
                className="input"
                value={reference}
                onChange={(e) => setReference(e.target.value)}
                placeholder="AVIS-2026-014"
              />
            </Field>

            <Field label="Type d'avis" htmlFor="avis-type">
              <select
                id="avis-type"
                className="input"
                value={type}
                onChange={(e) => setType(e.target.value)}
              >
                {Object.entries(LIBELLE_TYPE_AVIS).map(([valeur, libelle]) => (
                  <option key={valeur} value={valeur}>
                    {libelle}
                  </option>
                ))}
              </select>
            </Field>

            <Field
              label="Date de clôture"
              htmlFor="avis-cloture"
              hint="Obligatoire pour publier : l'âge et l'ancienneté se calculent à cette date."
            >
              <input
                id="avis-cloture"
                type="date"
                className="input"
                value={cloture}
                onChange={(e) => setCloture(e.target.value)}
              />
            </Field>

            <div className="flex justify-end gap-2">
              <button type="button" className="btn-ghost" onClick={() => setOuvert(false)}>
                Annuler
              </button>
              <button
                type="button"
                className="btn-primary"
                disabled={creer.isPending}
                onClick={() => creer.mutate()}
              >
                {creer.isPending && <Spinner />}
                Créer l'avis
              </button>
            </div>
          </div>
        </Modal>
      )}
    </section>
  )
}

/** Dépôt en lot : le cas où les RH ont déjà les CV dans leur boîte email. */
function DepotEnLot({ posteId }: { posteId: string }) {
  const queryClient = useQueryClient()
  const fichierRef = useRef<HTMLInputElement>(null)
  const [depouiller, setDepouiller] = useState(false)
  const [compte, setCompte] = useState<string | null>(null)
  const [details, setDetails] = useState<string[]>([])

  const deposer = useMutation({
    mutationFn: (fichiers: File[]) =>
      recrutementApi.depotMultiple(posteId, fichiers, depouiller),
    onSuccess: (r) => {
      const parts = [`${r.deposes} dossier(s) déposé(s)`]
      if (r.doublons_ignores) parts.push(`${r.doublons_ignores} doublon(s) ignoré(s)`)
      if (r.refuses) parts.push(`${r.refuses} refusé(s)`)
      setCompte(parts.join(' · '))
      setDetails(
        r.resultats
          .filter((x) => !x.accepte)
          .map((x) => `${x.fichier} — ${x.erreur}`),
      )
      void queryClient.invalidateQueries({ queryKey: ['grille', posteId] })
      void queryClient.invalidateQueries({ queryKey: ['candidatures', posteId] })
    },
    onError: (e) => setCompte(e instanceof Error ? e.message : 'Dépôt impossible'),
  })

  return (
    <section className="card p-4">
      <h2 className="mb-1 text-sm font-semibold text-ink-900">Déposer des dossiers</h2>
      <p className="mb-3 text-xs text-ink-500">
        Pour les CV déjà reçus par ailleurs. Un fichier donne une candidature ; les doublons sont
        signalés et rien n'est éliminé avant relecture.
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
        accept=".pdf,.docx,.doc"
        className="hidden"
        onChange={(e) => {
          const fichiers = Array.from(e.target.files ?? [])
          if (fichiers.length) deposer.mutate(fichiers)
          e.target.value = ''
        }}
      />
      <button
        type="button"
        className="btn-ghost w-full"
        disabled={deposer.isPending}
        onClick={() => fichierRef.current?.click()}
      >
        {deposer.isPending && <Spinner />}
        Choisir des fichiers…
      </button>

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

function TableauGrille({
  lignes,
  onOuvrir,
  colonneMotifs = false,
}: {
  lignes: LigneGrille[]
  onOuvrir: (id: string) => void
  colonneMotifs?: boolean
}) {
  if (lignes.length === 0) return <EmptyState title="Aucun dossier dans cette catégorie" />
  return (
    <div className="card overflow-x-auto">
      <table className="w-full min-w-[52rem] text-sm">
        <thead>
          <tr className="border-b border-ink-200 text-left text-xs uppercase tracking-wide text-ink-500">
            <th className="px-3 py-2 font-medium">Nom</th>
            <th className="px-3 py-2 font-medium">Prénom</th>
            <th className="px-3 py-2 font-medium">Âge</th>
            <th className="px-3 py-2 font-medium">Nationalité</th>
            <th className="px-3 py-2 font-medium">Dernier diplôme</th>
            <th className="px-3 py-2 font-medium">École / Université</th>
            <th className="px-3 py-2 font-medium">Structure / Employeur</th>
            <th className="px-3 py-2 text-right font-medium">
              {colonneMotifs ? 'Motifs' : 'Note'}
            </th>
          </tr>
        </thead>
        <tbody>
          {lignes.map((ligne) => (
            <tr
              key={ligne.candidature_id}
              className="cursor-pointer border-b border-ink-100 last:border-0 hover:bg-ink-50"
              onClick={() => onOuvrir(ligne.candidature_id)}
            >
              <td className="px-3 py-2 font-medium text-ink-900">
                {ligne.nom}
                {ligne.doublons > 0 && (
                  <span
                    className="ml-1.5 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-800"
                    title={`${ligne.doublons} autre(s) dossier(s) reçu(s) de la même adresse email — souvent un envoi corrigé, à comparer avant de trancher`}
                  >
                    renvoi
                  </span>
                )}
              </td>
              <td className="px-3 py-2 text-ink-700">{ligne.prenom}</td>
              <td className="px-3 py-2 tabular-nums text-ink-700">{ligne.age ?? '—'}</td>
              <td className="px-3 py-2 text-ink-700">{ligne.nationalite ?? '—'}</td>
              <td className="px-3 py-2 text-ink-700">{ligne.dernier_diplome ?? '—'}</td>
              <td className="px-3 py-2 text-ink-700">{ligne.ecole_universite ?? '—'}</td>
              <td className="px-3 py-2 text-ink-700">{ligne.structure_employeur ?? '—'}</td>
              <td className="px-3 py-2 text-right">
                {colonneMotifs ? (
                  <span className="text-xs text-red-700">{ligne.motifs.length}</span>
                ) : (
                  <span className="font-semibold tabular-nums text-ink-900">
                    {ligne.note ?? '—'}
                    <span className="text-ink-400">/{ligne.total_max ?? ''}</span>
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ReglerSeuil({
  posteId,
  seuilActuel,
  seuilNominal,
  onClose,
}: {
  posteId: string
  seuilActuel: number
  seuilNominal: number
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [seuil, setSeuil] = useState(seuilActuel)
  const [justification, setJustification] = useState('')
  const [erreur, setErreur] = useState<string | null>(null)
  const abaisse = seuil < seuilNominal

  const enregistrer = useMutation({
    mutationFn: () => recrutementApi.changerSeuil(posteId, seuil, justification),
    onSuccess: async () => {
      await recrutementApi.evaluerPoste(posteId)
      void queryClient.invalidateQueries({ queryKey: ['grille', posteId] })
      void queryClient.invalidateQueries({ queryKey: ['poste', posteId] })
      onClose()
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Enregistrement impossible'),
  })

  return (
    <Modal open title="Seuil de présélection" onClose={onClose}>
      <div className="space-y-4">
        <Field label={`Seuil (nominal : ${seuilNominal})`} htmlFor="seuil">
          <input
            id="seuil"
            type="number"
            step={0.5}
            min={0}
            max={30}
            className="input"
            value={seuil}
            onChange={(e) => setSeuil(Number(e.target.value))}
          />
        </Field>

        {abaisse && (
          <Field
            label="Justification"
            htmlFor="justification"
            hint="Obligatoire, et reprise dans le fichier remis au client."
          >
            <textarea
              id="justification"
              className="input min-h-[5rem]"
              value={justification}
              onChange={(e) => setJustification(e.target.value)}
              placeholder="Poste en tension, trois candidatures reçues."
            />
          </Field>
        )}

        {erreur && (
          <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {erreur}
          </p>
        )}

        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Annuler
          </button>
          <button
            type="button"
            className="btn-primary"
            disabled={(abaisse && !justification.trim()) || enregistrer.isPending}
            onClick={() => enregistrer.mutate()}
          >
            {enregistrer.isPending && <Spinner />}
            Enregistrer
          </button>
        </div>
      </div>
    </Modal>
  )
}

export default function PosteDetailPage() {
  const { posteId = '' } = useParams()
  const queryClient = useQueryClient()
  // Null tant que la grille n'est pas chargée : l'onglet ouvert est alors
  // celui qui contient effectivement des dossiers, plutôt qu'une liste vide.
  const [ongletChoisi, setOnglet] = useState<Onglet | null>(null)
  const [selection, setSelection] = useState<string | null>(null)
  const [seuilOuvert, setSeuilOuvert] = useState(false)
  const [erreur, setErreur] = useState<string | null>(null)

  const poste = useQuery({ queryKey: ['poste', posteId], queryFn: () => recrutementApi.poste(posteId) })
  const grille = useQuery({ queryKey: ['grille', posteId], queryFn: () => recrutementApi.grille(posteId) })
  const aVerifier = useQuery({
    queryKey: ['candidatures', posteId, 'A_VERIFIER'],
    queryFn: () => recrutementApi.candidatures(posteId, { statut: 'A_VERIFIER', page_size: 200 }),
  })

  const reevaluer = useMutation({
    mutationFn: () => recrutementApi.evaluerPoste(posteId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['grille', posteId] })
      void queryClient.invalidateQueries({ queryKey: ['candidatures', posteId] })
    },
  })

  const exporter = useMutation({
    mutationFn: () => recrutementApi.telechargerGrille(posteId),
    onError: (e) => setErreur(e instanceof Error ? e.message : "L'export a échoué"),
  })

  if (poste.isLoading || grille.isLoading) return <PageLoader />
  if (grille.isError) return <ErrorState error={grille.error} onRetry={() => grille.refetch()} />

  const g = grille.data!
  const p = poste.data!

  const onglet =
    ongletChoisi ??
    (g.nombre_preselectionnes > 0
      ? 'preselection'
      : g.nombre_a_verifier > 0
        ? 'a_verifier'
        : g.nombre_elimines > 0
          ? 'elimination'
          : 'preselection')

  const onglets: Array<[Onglet, string, number]> = [
    ['preselection', 'Présélectionnés', g.nombre_preselectionnes],
    ['sous_seuil', 'Sous le seuil', g.non_retenus.length],
    ['elimination', 'Éliminés', g.nombre_elimines],
    ['a_verifier', 'À vérifier', g.nombre_a_verifier],
  ]

  return (
    <div>
      <nav className="flex flex-wrap items-center gap-1 text-xs text-ink-500">
        <Link to="/mandats" className="hover:underline">
          Mandats
        </Link>
        <span>›</span>
        <Link to={`/mandats/${p.mandat_id}`} className="hover:underline">
          {g.mandat_intitule ?? 'Mandat'}
        </Link>
        <span>›</span>
        <span className="text-ink-700">{p.intitule}</span>
      </nav>

      <div className="mb-5 mt-2 flex flex-wrap items-start gap-3">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight text-ink-900">{p.intitule}</h1>
          <p className="mt-1 text-sm text-ink-500">
            {g.client_nom}
            {g.date_reference ? ` · clôture le ${g.date_reference}` : ''}
          </p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <button type="button" className="btn-ghost" onClick={() => setSeuilOuvert(true)}>
            Seuil : {g.seuil}/{g.total_max}
          </button>
          <button
            type="button"
            className="btn-ghost"
            disabled={reevaluer.isPending}
            onClick={() => reevaluer.mutate()}
          >
            {reevaluer.isPending && <Spinner />}
            Recalculer
          </button>
          <button
            type="button"
            className="btn-primary"
            disabled={exporter.isPending || g.nombre_candidatures === 0}
            onClick={() => exporter.mutate()}
          >
            {exporter.isPending && <Spinner />}
            Exporter la grille (Excel)
          </button>
        </div>
      </div>

      {erreur && (
        <div className="mb-5">
          <Callout tone="danger">{erreur}</Callout>
        </div>
      )}

      <div className="mb-5 grid gap-4 lg:grid-cols-2">
        <FichePoste poste={p} />
        <PanneauAvis posteId={posteId} />
      </div>

      <div className="mb-5">
        <DepotEnLot posteId={posteId} />
      </div>

      {p.restriction.justification && (
        <div className="mb-5">
          <Callout tone="warning">
            <strong>Poste restreint.</strong> {p.restriction.justification}
          </Callout>
        </div>
      )}

      {p.seuil_justification && (
        <div className="mb-5">
          <Callout tone="info">
            <strong>Seuil abaissé à {g.seuil}.</strong> {p.seuil_justification}
          </Callout>
        </div>
      )}

      <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Statistique valeur={g.nombre_candidatures} libelle="Candidatures" ton="text-ink-900" />
        <Statistique
          valeur={g.nombre_preselectionnes}
          libelle="Présélectionnés"
          ton="text-emerald-700"
          actif={onglet === 'preselection'}
          onClick={() => setOnglet('preselection')}
        />
        <Statistique
          valeur={g.nombre_elimines}
          libelle="Éliminés"
          ton="text-red-700"
          actif={onglet === 'elimination'}
          onClick={() => setOnglet('elimination')}
        />
        <Statistique
          valeur={g.nombre_a_verifier}
          libelle="À vérifier"
          ton="text-amber-700"
          actif={onglet === 'a_verifier'}
          onClick={() => setOnglet('a_verifier')}
        />
      </div>

      {g.nombre_candidatures === 0 ? (
        <EmptyState
          title="Aucune candidature"
          hint="Publiez un avis avec une référence, puis relevez la boîte email — ou saisissez un dossier à la main."
        />
      ) : (
        <>
          <div className="mb-4 flex gap-1 overflow-x-auto border-b border-ink-200">
            {onglets.map(([cle, libelle, nombre]) => (
              <button
                key={cle}
                type="button"
                onClick={() => setOnglet(cle)}
                className={`-mb-px shrink-0 border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
                  onglet === cle
                    ? 'border-ink-900 text-ink-900'
                    : 'border-transparent text-ink-500 hover:text-ink-800'
                }`}
              >
                {libelle} <span className="tabular-nums text-ink-400">({nombre})</span>
              </button>
            ))}
          </div>

          {onglet === 'preselection' && (
            <TableauGrille lignes={g.preselectionnes} onOuvrir={setSelection} />
          )}
          {onglet === 'sous_seuil' && (
            <TableauGrille lignes={g.non_retenus} onOuvrir={setSelection} />
          )}

          {onglet === 'a_verifier' && (
            <div>
              <div className="mb-3">
                <Callout tone="warning">
                  Ces dossiers reposent sur des données extraites automatiquement. Tant qu'un
                  relecteur ne les a pas confirmées, aucun motif ne peut les éliminer.
                </Callout>
              </div>
              {aVerifier.data?.items.length === 0 ? (
                <EmptyState title="Rien à vérifier" hint="Tous les dossiers ont été relus." />
              ) : (
                <div className="card divide-y divide-ink-100">
                  {aVerifier.data?.items.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => setSelection(item.id)}
                      className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-ink-50"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-ink-900">
                          {item.nom.toUpperCase()} {item.prenom}
                        </p>
                        <p className="truncate text-xs text-ink-500">
                          {item.motifs.length} motif(s) en attente de confirmation
                          {item.doublons > 0 && (
                            <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 font-medium text-amber-800">
                              {item.doublons} doublon(s)
                            </span>
                          )}
                        </p>
                      </div>
                      <span className="text-sm font-semibold tabular-nums text-ink-700">
                        {item.note ?? '—'}
                        <span className="text-ink-400">/{item.total_max ?? ''}</span>
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {onglet === 'elimination' && (
            <div className="space-y-6">
              {g.elimines.length === 0 && <EmptyState title="Aucun dossier éliminé" />}
              {g.elimines.map((groupe) => (
                <section key={groupe.motif}>
                  <h2 className="mb-2 text-sm font-semibold text-ink-900">
                    {groupe.libelle}
                    <span className="ml-2 font-normal text-ink-400">({groupe.lignes.length})</span>
                  </h2>
                  <TableauGrille lignes={groupe.lignes} onOuvrir={setSelection} colonneMotifs />
                </section>
              ))}
            </div>
          )}
        </>
      )}

      {selection && (
        <CandidatureDrawer
          candidatureId={selection}
          posteId={posteId}
          onClose={() => setSelection(null)}
        />
      )}

      {seuilOuvert && (
        <ReglerSeuil
          posteId={posteId}
          seuilActuel={g.seuil}
          seuilNominal={p.seuil_nominal}
          onClose={() => setSeuilOuvert(false)}
        />
      )}
    </div>
  )
}
