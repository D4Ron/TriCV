import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  boiteApi,
  dossiersApi,
  recrutementApi,
  type MessageBoite,
  type MessageBoiteDetail,
  type StatutMessage,
} from '@/lib/api'
import { Callout, EmptyState, ErrorState, Modal, PageLoader, Spinner } from '@/components/ui'
import { estDomainePublic } from '@/lib/interface'

/**
 * La boîte de recrutement, comme dans une messagerie.
 *
 * Le relevé automatique tranche seul, et c'est voulu : il prend tout message
 * porteur d'une pièce lisible, parce qu'un dossier inutile se supprime alors
 * qu'une candidature manquée ne se rattrape pas. Mais il ne montrait ni ce qu'il
 * avait pris, ni ce qu'il avait laissé, ni pourquoi. Ici, chaque message dit ce
 * que l'application en a fait ; on importe à la main ce qui a été laissé, on
 * écarte ce qui n'est pas une candidature, et on ignore un expéditeur une fois
 * pour toutes.
 *
 * Rien n'est jamais effacé de la boîte Microsoft : l'application lit, et marque
 * lu ce qu'elle importe.
 */

const STATUTS: Record<Exclude<StatutMessage, ''>, { libelle: string; ton: string }> = {
  IMPORTE: { libelle: 'Importé', ton: 'bg-emerald-100 text-emerald-800' },
  IGNORE: { libelle: 'Ignoré', ton: 'bg-ink-100 text-ink-600' },
  SANS_PIECE: { libelle: 'Sans pièce lisible', ton: 'bg-amber-100 text-amber-800' },
  SUPPRIME: { libelle: 'Importé puis supprimé', ton: 'bg-ink-100 text-ink-500' },
}

const FILTRES: Array<[string, string]> = [
  ['tous', 'Tous'],
  ['non_lus', 'Non lus'],
  ['avec_pj', 'Avec pièces jointes'],
]

const VUES: Array<[string, string]> = [
  ['tout', 'Tout'],
  ['a_traiter', 'À traiter'],
  ['IMPORTE', 'Importés'],
  ['IGNORE', 'Ignorés'],
]

function dateCourte(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  const aujourdhui = new Date()
  if (d.toDateString() === aujourdhui.toDateString()) {
    return d.toLocaleTimeString('fr', { hour: '2-digit', minute: '2-digit' })
  }
  return d.toLocaleDateString('fr', {
    day: 'numeric',
    month: 'short',
    ...(d.getFullYear() !== aujourdhui.getFullYear() ? { year: 'numeric' } : {}),
  })
}

function domaine(adresse: string): string {
  const i = adresse.indexOf('@')
  return i >= 0 ? adresse.slice(i) : adresse
}

function Pastille({ statut }: { statut: StatutMessage }) {
  if (!statut) return null
  const s = STATUTS[statut]
  return (
    <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ${s.ton}`}>
      {s.libelle}
    </span>
  )
}

/** Choisir le poste avant d'importer — ou aucun : le dossier va au vivier. */
function Importer({
  messages,
  posteSuggere,
  onClose,
  onFait,
}: {
  messages: MessageBoite[]
  posteSuggere: { id: string; intitule: string } | null
  onClose: () => void
  onFait: (compteRendu: string) => void
}) {
  const postes = useQuery({ queryKey: ['postes-actifs'], queryFn: dossiersApi.postesActifs })
  const [posteId, setPosteId] = useState(posteSuggere?.id ?? '')
  const [regrouper, setRegrouper] = useState(true)
  const expediteurs = new Set(messages.map((m) => m.expediteur)).size

  const importer = useMutation({
    mutationFn: () =>
      boiteApi.importer(
        messages.map((m) => m.id),
        posteId || null,
        regrouper,
      ),
    onSuccess: (r) => {
      const parts = [`${r.crees} dossier(s) créé(s)`]
      if (r.completes) parts.push(`${r.completes} dossier(s) complété(s)`)
      if (r.fusionnes) parts.push(`${r.fusionnes} candidat(s) qui avai(en)t déjà un dossier : pièces versées, aucun doublon`)
      if (r.deja_importes.length) parts.push(`${r.deja_importes.length} déjà importé(s)`)
      if (r.sans_piece.length) parts.push(`${r.sans_piece.length} sans pièce lisible`)
      if (r.liens_recuperes) parts.push(`${r.liens_recuperes} document(s) récupéré(s) depuis un lien`)
      if (r.liens_inaccessibles.length)
        parts.push(
          `${r.liens_inaccessibles.length} lien(s) à ouvrir à la main (${r.liens_inaccessibles.join(' ; ')})`,
        )
      onFait(parts.join(' · ') + '.')
    },
  })

  return (
    <Modal open title={`Importer ${messages.length} message(s)`} onClose={onClose}>
      <div className="space-y-4 text-sm">
        <label className="block">
          <span className="text-xs font-medium text-ink-700">Poste visé</span>
          <select
            className="input mt-1"
            value={posteId}
            onChange={(e) => setPosteId(e.target.value)}
            disabled={postes.isLoading}
          >
            <option value="">Aucun — au vivier, comme candidature spontanée</option>
            {(postes.data ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.intitule}
                {p.client ? ` — ${p.client}` : ''}
              </option>
            ))}
          </select>
          {posteSuggere && (
            <span className="mt-1 block text-xs text-ink-500">
              L&apos;objet désigne « {posteSuggere.intitule} » : il est proposé.
            </span>
          )}
        </label>

        {messages.length > 1 && (
          <label className="flex items-start gap-2">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={regrouper}
              onChange={(e) => setRegrouper(e.target.checked)}
            />
            <span>
              Un seul dossier par adresse
              <span className="block text-xs text-ink-500">
                {expediteurs < messages.length
                  ? `${messages.length} messages de ${expediteurs} adresse(s) : le CV, puis les diplômes… finissent dans le même dossier.`
                  : 'Chaque message vient d’une adresse différente.'}
              </span>
            </span>
          </label>
        )}

        {importer.isError && (
          <Callout tone="danger">
            {importer.error instanceof Error ? importer.error.message : 'Import impossible'}
          </Callout>
        )}
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button type="button" className="btn-ghost" onClick={onClose}>
          Annuler
        </button>
        <button
          type="button"
          className="btn-primary"
          disabled={importer.isPending}
          onClick={() => importer.mutate()}
        >
          {importer.isPending && <Spinner />}
          Importer
        </button>
      </div>
    </Modal>
  )
}

/** Tout relever, lot après lot, en montrant l'avancement. */
function ReleverTout({ onClose, onFait }: { onClose: () => void; onFait: () => void }) {
  const [etat, setEtat] = useState({
    lots: 0,
    crees: 0,
    spontanees: 0,
    ignores: 0,
    expediteurs: 0,
    sansPiece: 0,
    liens: 0,
    fusionnes: 0,
    liensInaccessibles: [] as string[],
    fini: false,
    erreur: null as string | null,
  })
  const arret = useRef(false)

  useEffect(() => {
    let vivant = true
    ;(async () => {
      let reste = true
      while (reste && !arret.current && vivant) {
        try {
          const r = await recrutementApi.releverCourriel(25)
          reste = r.reste
          setEtat((e) => ({
            ...e,
            lots: e.lots + 1,
            crees: e.crees + r.crees,
            spontanees: e.spontanees + r.spontanees,
            ignores: e.ignores + r.ignores,
            expediteurs: e.expediteurs + r.expediteurs_ignores,
            sansPiece: e.sansPiece + r.sans_piece.length + r.non_rattaches.length,
            liens: e.liens + r.liens_recuperes,
            fusionnes: e.fusionnes + r.fusionnes,
            liensInaccessibles: [...e.liensInaccessibles, ...r.liens_inaccessibles],
          }))
        } catch (err) {
          setEtat((e) => ({ ...e, erreur: err instanceof Error ? err.message : 'Relevé interrompu' }))
          break
        }
      }
      if (vivant) setEtat((e) => ({ ...e, fini: true }))
      onFait()
    })()
    return () => {
      vivant = false
      arret.current = true
    }
    // Lancé une fois, à l'ouverture.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <Modal open title="Relever toute la boîte" onClose={onClose}>
      <div className="space-y-3 text-sm">
        {!etat.fini && (
          <p className="flex items-center gap-2 text-ink-700">
            <Spinner /> Lot {etat.lots + 1} en cours — les messages déjà traités sont sautés.
          </p>
        )}
        <dl className="grid grid-cols-2 gap-2">
          {[
            ['Candidatures rattachées à un poste', etat.crees],
            ['Candidatures sans poste (vivier)', etat.spontanees],
            ['Sans pièce lisible — laissés non lus', etat.sansPiece],
            ['Expéditeurs ignorés', etat.expediteurs],
            ['Déjà reçus', etat.ignores],
            ['Versés à un dossier existant (pas de doublon)', etat.fusionnes],
            ['Documents récupérés depuis un lien', etat.liens],
          ].map(([libelle, n]) => (
            <div key={libelle as string} className="rounded-lg border border-ink-200 px-3 py-2">
              <dt className="text-xs text-ink-500">{libelle}</dt>
              <dd className="text-lg font-semibold tabular-nums text-ink-900">{n}</dd>
            </div>
          ))}
        </dl>
        {etat.liensInaccessibles.length > 0 && (
          <Callout tone="warning">
            {etat.liensInaccessibles.length} lien(s) à ouvrir à la main — privés, ou d&apos;un
            service sans téléchargement direct :
            <ul className="mt-1 max-h-32 list-disc overflow-y-auto pl-5 text-xs">
              {etat.liensInaccessibles.map((l, i) => (
                <li key={i}>{l}</li>
              ))}
            </ul>
          </Callout>
        )}
        {etat.erreur && <Callout tone="danger">{etat.erreur}</Callout>}
        {etat.fini && !etat.erreur && (
          <Callout tone="success">
            Relevé terminé. Les dossiers sans poste attendent au{' '}
            <Link to="/vivier" className="font-medium underline">
              vivier
            </Link>{' '}
            : on y supprime d&apos;un coup ceux qui ne sont pas des candidatures.
          </Callout>
        )}
      </div>
      <div className="mt-5 flex justify-end gap-2">
        {!etat.fini ? (
          <button
            type="button"
            className="btn-ghost"
            onClick={() => {
              arret.current = true
            }}
          >
            Arrêter après ce lot
          </button>
        ) : (
          <button type="button" className="btn-primary" onClick={onClose}>
            Fermer
          </button>
        )}
      </div>
    </Modal>
  )
}

/** Les expéditeurs dont le relevé ne tire plus de dossier. */
function ExpediteursIgnores({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient()
  const regles = useQuery({ queryKey: ['boite-regles'], queryFn: boiteApi.regles })
  const [adresse, setAdresse] = useState('')
  const rafraichir = () => {
    void queryClient.invalidateQueries({ queryKey: ['boite-regles'] })
    void queryClient.invalidateQueries({ queryKey: ['boite'] })
  }
  const ajouter = useMutation({
    mutationFn: () => boiteApi.ajouterRegle(adresse.trim()),
    onSuccess: () => {
      setAdresse('')
      rafraichir()
    },
  })
  const retirer = useMutation({ mutationFn: boiteApi.retirerRegle, onSuccess: rafraichir })

  return (
    <Modal open title="Expéditeurs ignorés" onClose={onClose}>
      <p className="text-sm text-ink-600">
        Leurs messages restent dans la boîte, mais le relevé n&apos;en tire plus de dossier. Une
        adresse (lettre@journal.tg) ou tout un domaine (@journal.tg).
      </p>
      <form
        className="mt-3 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (adresse.trim()) ajouter.mutate()
        }}
      >
        <input
          className="input"
          value={adresse}
          placeholder="@journal.tg"
          onChange={(e) => setAdresse(e.target.value)}
        />
        <button type="submit" className="btn-secondary shrink-0" disabled={ajouter.isPending}>
          Ajouter
        </button>
      </form>
      {ajouter.isError && (
        <p className="mt-1 text-xs text-red-700">
          {ajouter.error instanceof Error ? ajouter.error.message : 'Ajout impossible'}
        </p>
      )}
      <ul className="mt-4 max-h-72 divide-y divide-ink-100 overflow-y-auto">
        {(regles.data ?? []).length === 0 && (
          <li className="py-2 text-sm text-ink-500">Aucun expéditeur ignoré.</li>
        )}
        {(regles.data ?? []).map((r) => (
          <li key={r.id} className="flex items-center gap-2 py-2 text-sm">
            <span className="min-w-0 flex-1 truncate font-medium text-ink-800">{r.adresse}</span>
            <button
              type="button"
              className="text-xs text-ink-500 underline hover:text-ink-800"
              onClick={() => retirer.mutate(r.id)}
            >
              Ne plus ignorer
            </button>
          </li>
        ))}
      </ul>
    </Modal>
  )
}

/** Le message ouvert : ce qu'il dit, ce qu'il porte, ce qu'on en fait. */
function Lecture({
  id,
  onImporter,
  onChange,
  onFermer,
}: {
  id: string
  onImporter: (messages: MessageBoite[], poste: MessageBoiteDetail['poste_propose']) => void
  onChange: (compteRendu: string) => void
  onFermer: () => void
}) {
  const queryClient = useQueryClient()
  const detail = useQuery({ queryKey: ['boite', 'message', id], queryFn: () => boiteApi.lire(id) })
  const [avecAutres, setAvecAutres] = useState<Set<string>>(new Set())
  const [erreurPiece, setErreurPiece] = useState<string | null>(null)

  useEffect(() => {
    // Les autres envois du même expéditeur, non encore importés et porteurs de
    // pièces, sont cochés d'office : ils vont presque toujours ensemble.
    const autres = detail.data?.autres ?? []
    setAvecAutres(new Set(autres.filter((a) => !a.statut && a.avec_pieces).map((a) => a.id)))
  }, [detail.data])

  const rafraichir = () => {
    void queryClient.invalidateQueries({ queryKey: ['boite'] })
  }
  const ignorer = useMutation({
    mutationFn: (m: MessageBoite) => boiteApi.ignorer([m]),
    onSuccess: () => {
      rafraichir()
      onChange('Message ignoré : le relevé ne le lira plus.')
    },
  })
  const retablir = useMutation({
    mutationFn: (m: MessageBoite) => boiteApi.retablir([m.message_id]),
    onSuccess: () => {
      rafraichir()
      onChange('Message rétabli : le prochain relevé le reconsidérera.')
    },
  })
  const ignorerExpediteur = useMutation({
    mutationFn: (adresse: string) => boiteApi.ajouterRegle(adresse),
    onSuccess: (r) => {
      rafraichir()
      void queryClient.invalidateQueries({ queryKey: ['boite-regles'] })
      onChange(`${r.adresse} est désormais ignoré par le relevé.`)
    },
  })

  if (detail.isLoading) return <PageLoader />
  if (detail.isError) return <ErrorState error={detail.error} onRetry={() => detail.refetch()} />
  const m = detail.data!

  const ouvrir = async (pieceId: string) => {
    setErreurPiece(null)
    const onglet = window.open('', '_blank')
    try {
      const url = await boiteApi.pieceObjectUrl(m.id, pieceId)
      if (onglet) onglet.location.href = url
    } catch (e) {
      onglet?.close()
      setErreurPiece(e instanceof Error ? e.message : 'Pièce indisponible')
    }
  }

  const aImporter = [m, ...m.autres.filter((a) => avecAutres.has(a.id))]
  const pieces = m.pieces.filter((p) => !p.en_ligne)

  return (
    <article className="flex h-full flex-col">
      <header className="border-b border-ink-100 pb-3">
        <div className="flex items-start gap-2">
          <h2 className="min-w-0 flex-1 text-base font-semibold text-ink-900">
            {m.sujet || '(sans objet)'}
          </h2>
          <button type="button" className="btn-ghost px-2 py-1 text-xs lg:hidden" onClick={onFermer}>
            Retour
          </button>
        </div>
        <p className="mt-1 text-sm text-ink-700">
          {m.nom_expediteur && <span className="font-medium">{m.nom_expediteur} </span>}
          <span className="text-ink-500">&lt;{m.expediteur}&gt;</span>
        </p>
        <p className="text-xs text-ink-500">
          {new Date(m.recu_le).toLocaleString('fr', { dateStyle: 'long', timeStyle: 'short' })}
        </p>

        {m.statut === 'IMPORTE' && m.candidature_id && (
          <div className="mt-3">
            <Callout tone="success">Importé. Le dossier se trouve sous son poste, ou au vivier s&apos;il n&apos;en a pas.</Callout>
          </div>
        )}
        {(m.statut === 'IGNORE' || m.statut === 'SANS_PIECE' || m.statut === 'SUPPRIME') && (
          <div className="mt-3">
            <Callout tone="info">
              {STATUTS[m.statut].libelle}
              {m.motif ? ` — ${m.motif}` : ''}.
            </Callout>
          </div>
        )}
        {m.expediteur_ignore && (
          <p className="mt-2 text-xs text-ink-500">
            Cet expéditeur est ignoré par le relevé (Expéditeurs ignorés).
          </p>
        )}

        <div className="mt-3 flex flex-wrap gap-2">
          {m.statut !== 'IMPORTE' && (
            <button
              type="button"
              className="btn-primary px-3 py-1.5 text-xs"
              onClick={() => onImporter(aImporter, m.poste_propose)}
            >
              Importer{aImporter.length > 1 ? ` (${aImporter.length} messages)` : ''}
            </button>
          )}
          {!m.statut && (
            <button
              type="button"
              className="btn-ghost px-3 py-1.5 text-xs"
              disabled={ignorer.isPending}
              onClick={() => ignorer.mutate(m)}
            >
              Ignorer
            </button>
          )}
          {(m.statut === 'IGNORE' || m.statut === 'SANS_PIECE') && (
            <button
              type="button"
              className="btn-ghost px-3 py-1.5 text-xs"
              disabled={retablir.isPending}
              onClick={() => retablir.mutate(m)}
            >
              Rétablir
            </button>
          )}
          {!m.expediteur_ignore && (
            <>
              <button
                type="button"
                className="btn-ghost px-3 py-1.5 text-xs"
                onClick={() => ignorerExpediteur.mutate(m.expediteur)}
              >
                Ignorer cet expéditeur
              </button>
              {/* Une messagerie publique (@gmail.com…) porte la plupart des
                  candidats : on n'en ignore jamais le domaine entier. */}
              {!estDomainePublic(domaine(m.expediteur)) && (
                <button
                  type="button"
                  className="btn-ghost px-3 py-1.5 text-xs"
                  onClick={() => ignorerExpediteur.mutate(domaine(m.expediteur))}
                >
                  Ignorer tout {domaine(m.expediteur)}
                </button>
              )}
            </>
          )}
        </div>
        {(ignorerExpediteur.isError || ignorer.isError) && (
          <p className="mt-1 text-xs text-red-700">
            {((ignorerExpediteur.error ?? ignorer.error) as Error | null)?.message}
          </p>
        )}
      </header>

      {pieces.length > 0 && (
        <div className="flex flex-wrap gap-1.5 border-b border-ink-100 py-3">
          {pieces.map((p) => (
            <button
              key={p.id}
              type="button"
              className="rounded-md border border-ink-200 px-2 py-1 text-xs text-ink-700 hover:border-brand-300 hover:text-brand-800"
              onClick={() => void ouvrir(p.id)}
              title={p.type}
            >
              📎 {p.nom} · {Math.max(1, Math.round(p.octets / 1024))} Ko
            </button>
          ))}
          {erreurPiece && <p className="w-full text-xs text-red-700">{erreurPiece}</p>}
        </div>
      )}

      {m.liens.length > 0 && (
        <div className="border-b border-ink-100 py-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">
            Documents en lien ({m.liens.length})
          </p>
          <p className="mt-0.5 text-xs text-ink-500">
            Récupérés à l&apos;import s&apos;ils sont publics ; un lien privé est signalé.
          </p>
          <ul className="mt-1.5 space-y-1 text-xs">
            {m.liens.map((l) => (
              <li key={l.url} className="flex items-center gap-2">
                <span className="shrink-0 rounded bg-ink-100 px-1.5 py-0.5 text-ink-700">{l.service}</span>
                <a
                  href={l.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="min-w-0 flex-1 truncate text-brand-700 underline"
                >
                  {l.url}
                </a>
                {!l.telechargeable && <span className="shrink-0 text-amber-700">à ouvrir à la main</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto py-3">
        <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-ink-800">
          {m.corps.trim() || '(message sans texte)'}
        </p>
      </div>

      {m.autres.length > 0 && (
        <section className="border-t border-ink-100 pt-3">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
            Autres messages de cette adresse ({m.autres.length})
          </h3>
          <p className="mt-0.5 text-xs text-ink-500">
            Cochés : importés avec celui-ci, dans le même dossier.
          </p>
          <ul className="mt-2 max-h-40 space-y-1 overflow-y-auto">
            {m.autres.map((a) => (
              <li key={a.id}>
                <label className="flex items-center gap-2 text-xs">
                  <input
                    type="checkbox"
                    disabled={a.statut === 'IMPORTE'}
                    checked={avecAutres.has(a.id)}
                    onChange={() =>
                      setAvecAutres((s) => {
                        const n = new Set(s)
                        if (n.has(a.id)) n.delete(a.id)
                        else n.add(a.id)
                        return n
                      })
                    }
                  />
                  <span className="min-w-0 flex-1 truncate text-ink-800">{a.sujet || '(sans objet)'}</span>
                  {a.avec_pieces && <span aria-label="pièces jointes">📎</span>}
                  <Pastille statut={a.statut} />
                  <span className="shrink-0 text-ink-500">{dateCourte(a.recu_le)}</span>
                </label>
              </li>
            ))}
          </ul>
        </section>
      )}
    </article>
  )
}

export default function BoitePage() {
  const queryClient = useQueryClient()
  const [filtre, setFiltre] = useState('tous')
  const [vue, setVue] = useState('tout')
  const [recherche, setRecherche] = useState('')
  const [rechercheAppliquee, setRechercheAppliquee] = useState('')
  const [pages, setPages] = useState<MessageBoite[][]>([])
  const [suite, setSuite] = useState('')
  const [ouvert, setOuvert] = useState<string | null>(null)
  const [coches, setCoches] = useState<Set<string>>(new Set())
  const [aImporter, setAImporter] = useState<{
    messages: MessageBoite[]
    poste: MessageBoiteDetail['poste_propose']
  } | null>(null)
  const [releve, setReleve] = useState(false)
  const [regles, setRegles] = useState(false)
  const [compteRendu, setCompteRendu] = useState<string | null>(null)

  const etat = useQuery({ queryKey: ['courriel'], queryFn: recrutementApi.etatCourriel })
  const premiere = useQuery({
    queryKey: ['boite', 'liste', filtre, rechercheAppliquee],
    queryFn: () => boiteApi.lister({ filtre, recherche: rechercheAppliquee }),
    enabled: Boolean(etat.data?.actif),
  })

  useEffect(() => {
    if (premiere.data) {
      setPages([premiere.data.messages])
      setSuite(premiere.data.suite)
    }
  }, [premiere.data])

  const plus = useMutation({
    mutationFn: () => boiteApi.lister({ suite }),
    onSuccess: (r) => {
      setPages((p) => [...p, r.messages])
      setSuite(r.suite)
    },
  })

  const ignorerLot = useMutation({
    mutationFn: (messages: MessageBoite[]) => boiteApi.ignorer(messages),
    onSuccess: (r) => {
      setCoches(new Set())
      setCompteRendu(`${r.ignores} message(s) ignoré(s) — rétablissables depuis le message.`)
      void queryClient.invalidateQueries({ queryKey: ['boite'] })
    },
  })

  const messages = useMemo(() => pages.flat(), [pages])
  const visibles = useMemo(
    () =>
      messages.filter((m) =>
        vue === 'tout' ? true : vue === 'a_traiter' ? !m.statut : m.statut === vue,
      ),
    [messages, vue],
  )
  const selection = messages.filter((m) => coches.has(m.id))

  if (etat.isLoading) return <PageLoader />
  if (!etat.data?.actif) {
    return (
      <div className="mx-auto max-w-xl py-10">
        <EmptyState
          title="La boîte n'est pas branchée"
          hint={
            etat.data?.releve_desactive
              ? 'Le relevé est désactivé dans Paramètres › Courriel.'
              : `Il manque ${etat.data?.manquants.join(' et ') || 'la configuration'} — Paramètres › Courriel.`
          }
        />
      </div>
    )
  }

  const basculer = (id: string) =>
    setCoches((s) => {
      const n = new Set(s)
      if (n.has(id)) n.delete(id)
      else n.add(id)
      return n
    })

  return (
    <div className="flex h-[calc(100vh-7rem)] min-h-[32rem] flex-col">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-semibold tracking-tight text-ink-900">Boîte de recrutement</h1>
          <p className="text-xs text-ink-500">
            {etat.data.boite}
            {premiere.data?.total !== undefined &&
              ` · ${premiere.data.total} message(s), dont ${premiere.data.non_lus} non lu(s)`}
          </p>
        </div>
        <button type="button" className="btn-ghost px-3 py-1.5 text-xs" onClick={() => setRegles(true)}>
          Expéditeurs ignorés
        </button>
        <button type="button" className="btn-primary" onClick={() => setReleve(true)}>
          Relever tout
        </button>
      </div>

      {compteRendu && (
        <div className="mb-3">
          <Callout tone="success">
            {compteRendu}{' '}
            <button type="button" className="underline" onClick={() => setCompteRendu(null)}>
              Fermer
            </button>
          </Callout>
        </div>
      )}

      <div className="mb-2 flex flex-wrap items-center gap-2">
        <div className="flex rounded-lg border border-ink-200 p-0.5">
          {FILTRES.map(([cle, libelle]) => (
            <button
              key={cle}
              type="button"
              aria-pressed={filtre === cle}
              onClick={() => setFiltre(cle)}
              className={`rounded-md px-2.5 py-1 text-xs font-medium ${
                filtre === cle ? 'bg-ink-900 text-white' : 'text-ink-600 hover:text-ink-900'
              }`}
            >
              {libelle}
            </button>
          ))}
        </div>
        <div className="flex rounded-lg border border-ink-200 p-0.5">
          {VUES.map(([cle, libelle]) => (
            <button
              key={cle}
              type="button"
              aria-pressed={vue === cle}
              onClick={() => setVue(cle)}
              className={`rounded-md px-2.5 py-1 text-xs font-medium ${
                vue === cle ? 'bg-brand-700 text-white' : 'text-ink-600 hover:text-ink-900'
              }`}
            >
              {libelle}
            </button>
          ))}
        </div>
        <form
          className="ml-auto flex min-w-[12rem] flex-1 gap-1 sm:max-w-xs"
          onSubmit={(e) => {
            e.preventDefault()
            setRechercheAppliquee(recherche.trim())
          }}
        >
          <input
            className="input py-1.5 text-sm"
            placeholder="Chercher (nom, objet, adresse)…"
            value={recherche}
            onChange={(e) => setRecherche(e.target.value)}
          />
        </form>
      </div>

      {selection.length > 0 && (
        <div className="mb-2 flex flex-wrap items-center gap-2 rounded-lg bg-brand-50 px-3 py-2 text-sm">
          <span className="font-medium text-brand-900">{selection.length} sélectionné(s)</span>
          <button
            type="button"
            className="btn-primary px-3 py-1 text-xs"
            onClick={() => setAImporter({ messages: selection, poste: null })}
          >
            Importer
          </button>
          <button
            type="button"
            className="btn-ghost px-3 py-1 text-xs"
            disabled={ignorerLot.isPending}
            onClick={() => ignorerLot.mutate(selection.filter((m) => m.statut !== 'IMPORTE'))}
          >
            Ignorer
          </button>
          <button type="button" className="ml-auto text-xs underline" onClick={() => setCoches(new Set())}>
            Tout désélectionner
          </button>
        </div>
      )}

      <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <section
          className={`card min-h-0 overflow-y-auto ${ouvert ? 'hidden lg:block' : ''}`}
          aria-label="Messages"
        >
          {premiere.isLoading && <PageLoader />}
          {premiere.isError && (
            <ErrorState error={premiere.error} onRetry={() => premiere.refetch()} />
          )}
          {premiere.data && visibles.length === 0 && (
            <p className="p-4 text-sm text-ink-500">Aucun message ici.</p>
          )}
          <ul className="divide-y divide-ink-100">
            {visibles.map((m) => (
              <li
                key={m.id}
                className={`flex cursor-pointer items-start gap-2 px-3 py-2.5 ${
                  ouvert === m.id ? 'bg-brand-50' : 'hover:bg-ink-50'
                }`}
                onClick={() => setOuvert(m.id)}
              >
                <input
                  type="checkbox"
                  className="mt-1"
                  aria-label={`Sélectionner ${m.sujet}`}
                  checked={coches.has(m.id)}
                  onClick={(e) => e.stopPropagation()}
                  onChange={() => basculer(m.id)}
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-2">
                    <span
                      className={`min-w-0 flex-1 truncate text-sm ${
                        m.lu ? 'text-ink-700' : 'font-semibold text-ink-900'
                      }`}
                    >
                      {m.nom_expediteur || m.expediteur}
                    </span>
                    <span className="shrink-0 text-xs text-ink-500">{dateCourte(m.recu_le)}</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span
                      className={`min-w-0 flex-1 truncate text-xs ${
                        m.lu ? 'text-ink-600' : 'font-medium text-ink-800'
                      }`}
                    >
                      {m.sujet || '(sans objet)'}
                    </span>
                    {m.avec_pieces && (
                      <span className="shrink-0 text-xs" aria-label="pièces jointes">
                        📎
                      </span>
                    )}
                    <Pastille statut={m.statut} />
                  </div>
                  <p className="truncate text-xs text-ink-400">{m.apercu}</p>
                </div>
              </li>
            ))}
          </ul>
          {suite && (
            <div className="p-3 text-center">
              <button
                type="button"
                className="btn-ghost px-3 py-1.5 text-xs"
                disabled={plus.isPending}
                onClick={() => plus.mutate()}
              >
                {plus.isPending && <Spinner />}
                Charger les messages suivants
              </button>
            </div>
          )}
        </section>

        <section className={`card min-h-0 overflow-hidden p-4 ${ouvert ? '' : 'hidden lg:block'}`}>
          {ouvert ? (
            <Lecture
              key={ouvert}
              id={ouvert}
              onImporter={(msgs, poste) => setAImporter({ messages: msgs, poste })}
              onChange={setCompteRendu}
              onFermer={() => setOuvert(null)}
            />
          ) : (
            <p className="text-sm text-ink-500">
              Choisissez un message pour le lire. Cochez-en plusieurs pour les importer ou les
              ignorer d&apos;un coup.
            </p>
          )}
        </section>
      </div>

      {aImporter && (
        <Importer
          messages={aImporter.messages}
          posteSuggere={aImporter.poste}
          onClose={() => setAImporter(null)}
          onFait={(m) => {
            setAImporter(null)
            setCoches(new Set())
            setCompteRendu(m)
            void queryClient.invalidateQueries({ queryKey: ['boite'] })
            void queryClient.invalidateQueries({ queryKey: ['dossiers-sans-poste'] })
          }}
        />
      )}
      {releve && (
        <ReleverTout
          onClose={() => setReleve(false)}
          onFait={() => {
            void queryClient.invalidateQueries({ queryKey: ['boite'] })
            void queryClient.invalidateQueries({ queryKey: ['dossiers-sans-poste'] })
            void queryClient.invalidateQueries({ queryKey: ['grille'] })
          }}
        />
      )}
      {regles && <ExpediteursIgnores onClose={() => setRegles(false)} />}
    </div>
  )
}
