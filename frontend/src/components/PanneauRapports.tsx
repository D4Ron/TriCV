import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  TYPES_RAPPORT,
  rapportsApi,
  recrutementApi,
  type SectionRapport,
  type TypeRapport,
} from '@/lib/api'
import { Callout, EmptyState, Spinner, Toggle } from '@/components/ui'
import { formatDate } from '@/lib/format'
import ApercuRapport from '@/components/ApercuRapport'

/**
 * Le rapport de recrutement : génération, relecture, validation, export.
 *
 * Le fil conducteur est la **relecture**. L'assistance propose un texte pour
 * chaque section ; tant qu'une section n'a pas été relue, elle est marquée
 * « proposée » et le rapport ne peut pas être validé. Un rapport engage le
 * cabinet devant son client : personne ne doit pouvoir en signer un qu'aucun
 * humain n'a lu.
 *
 * Les chiffres, eux, ne viennent jamais de la rédaction : effectifs, notes et
 * tableaux sont calculés et figés à la génération. C'est ce qui rend le
 * document vérifiable — et réexportable à l'identique dans six mois.
 */

const STATUT_STYLE: Record<string, string> = {
  BROUILLON: 'bg-ink-100 text-ink-600',
  EN_RELECTURE: 'bg-amber-100 text-amber-800',
  VALIDE: 'bg-emerald-100 text-emerald-800',
}

const STATUT_LIBELLE: Record<string, string> = {
  BROUILLON: 'Brouillon',
  EN_RELECTURE: 'En relecture',
  VALIDE: 'Validé',
}

const FORMATS: Array<{ cle: 'docx' | 'pdf' | 'odt' | 'txt'; libelle: string }> = [
  { cle: 'docx', libelle: 'Word' },
  { cle: 'pdf', libelle: 'PDF' },
  { cle: 'odt', libelle: 'OpenDocument' },
  { cle: 'txt', libelle: 'Texte' },
]

function Editeur({ rapportId, onFerme }: { rapportId: string; onFerme: () => void }) {
  const queryClient = useQueryClient()
  const rapport = useQuery({
    queryKey: ['rapport', rapportId],
    queryFn: () => rapportsApi.lire(rapportId),
  })

  const [titre, setTitre] = useState('')
  const [sections, setSections] = useState<SectionRapport[]>([])
  const [message, setMessage] = useState<string | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  // Relire le document entier avant de valider, sans passer par un export.
  const [vue, setVue] = useState<'rediger' | 'apercu'>('rediger')

  useEffect(() => {
    if (!rapport.data) return
    setTitre(rapport.data.titre)
    setSections(rapport.data.sections)
  }, [rapport.data])

  const enregistrer = useMutation({
    mutationFn: () =>
      rapportsApi.modifier(rapportId, {
        titre,
        sections: sections.map((s) => ({ code: s.code, titre: s.titre, contenu: s.contenu })),
      }),
    onSuccess: () => {
      setErreur(null)
      setMessage('Corrections enregistrées.')
      void rapport.refetch()
      void queryClient.invalidateQueries({ queryKey: ['rapports'] })
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Enregistrement impossible'),
  })

  const valider = useMutation({
    mutationFn: () => rapportsApi.valider(rapportId),
    onSuccess: () => {
      setErreur(null)
      setMessage('Rapport validé. Il ne se modifie plus.')
      void rapport.refetch()
      void queryClient.invalidateQueries({ queryKey: ['rapports'] })
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Validation impossible'),
  })

  const partager = useMutation({
    mutationFn: (actif: boolean) => rapportsApi.partager(rapportId, actif),
    onSuccess: () => {
      void rapport.refetch()
      void queryClient.invalidateQueries({ queryKey: ['rapports'] })
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Partage impossible'),
  })

  if (rapport.isLoading) return <Spinner />
  if (!rapport.data) return null

  const r = rapport.data
  const verrouille = r.statut === 'VALIDE'
  const aRelire = sections.filter((s) => s.origine === 'PROPOSEE')
  // Le même sous-titre et la même date que l'export : l'aperçu doit montrer le
  // document, pas une approximation.
  const sousTitre =
    ((r.donnees as { mandat?: { client?: string } })?.mandat?.client as string) || ''

  return (
    <div className="card p-5">
      <div className="flex flex-wrap items-baseline gap-2">
        <input
          className="input min-w-0 flex-1 font-medium"
          value={titre}
          disabled={verrouille}
          aria-label="Titre du rapport"
          onChange={(e) => setTitre(e.target.value)}
        />
        <span className={`badge ${STATUT_STYLE[r.statut]}`}>{STATUT_LIBELLE[r.statut]}</span>
        <button type="button" className="btn-ghost px-3 py-1.5 text-xs" onClick={onFerme}>
          Fermer
        </button>
      </div>

      <div className="mt-3 inline-flex rounded-lg border border-ink-200 p-0.5" role="tablist">
        {(
          [
            ['rediger', 'Rédiger'],
            ['apercu', 'Aperçu du document'],
          ] as const
        ).map(([cle, libelle]) => (
          <button
            key={cle}
            type="button"
            role="tab"
            aria-selected={vue === cle}
            className={`rounded-md px-3 py-1 text-xs font-medium ${
              vue === cle ? 'bg-ink-900 text-white' : 'text-ink-600 hover:bg-ink-50'
            }`}
            onClick={() => setVue(cle)}
          >
            {libelle}
          </button>
        ))}
      </div>

      {aRelire.length > 0 && (
        <div className="mt-3">
          <Callout tone="warning" title={`${aRelire.length} section(s) à relire`}>
            Ces textes ont été proposés automatiquement. Relisez-les — corrigez, ou réécrivez.
            Un rapport ne se valide qu&apos;une fois chaque section passée entre des mains
            humaines.
          </Callout>
        </div>
      )}

      {vue === 'apercu' && (
        <div className="mt-4">
          <ApercuRapport
            titre={titre}
            sousTitre={sousTitre}
            etabliLe={r.valide_le ?? r.created_at}
            sections={sections}
          />
        </div>
      )}

      <div className={`mt-4 space-y-4 ${vue === 'apercu' ? 'hidden' : ''}`}>
        {sections.map((section, index) => (
          <div key={section.code}>
            <div className="flex flex-wrap items-baseline gap-2">
              <label
                className="text-sm font-medium text-ink-800"
                htmlFor={`section-${section.code}`}
              >
                {section.titre}
              </label>
              {section.origine === 'PROPOSEE' && (
                <span className="badge bg-amber-100 text-amber-800">Proposée — à relire</span>
              )}
              {section.origine === 'CALCULEE' && !section.tableaux?.length && (
                <span className="badge bg-brand-100 text-brand-800">
                  Calculée à partir des dossiers
                </span>
              )}
              {/* Le tableau n'est pas dans la zone de texte : il est calculé
                  et se voit dans l'aperçu. Le dire évite de chercher. */}
              {Boolean(section.tableaux?.length) && (
                <span className="badge bg-brand-100 text-brand-800">
                  {section.tableaux!.length} tableau(x) calculé(s) — voir l&apos;aperçu
                </span>
              )}
            </div>
            <textarea
              id={`section-${section.code}`}
              className="input mt-1.5 font-mono text-xs"
              rows={section.origine === 'CALCULEE' ? 6 : 8}
              value={section.contenu}
              disabled={verrouille}
              onChange={(e) =>
                setSections((tous) =>
                  tous.map((s, i) => (i === index ? { ...s, contenu: e.target.value } : s)),
                )
              }
            />
          </div>
        ))}
      </div>

      {erreur && (
        <div className="mt-3">
          <Callout tone="danger">{erreur}</Callout>
        </div>
      )}
      {message && <p className="mt-3 text-sm font-medium text-emerald-700">{message}</p>}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        {!verrouille && (
          <>
            <button
              type="button"
              className="btn-ghost px-3 py-1.5 text-xs"
              disabled={enregistrer.isPending}
              onClick={() => enregistrer.mutate()}
            >
              {enregistrer.isPending && <Spinner />}
              Enregistrer
            </button>
            <button
              type="button"
              className="btn-primary px-3 py-1.5 text-xs"
              disabled={valider.isPending}
              onClick={() => valider.mutate()}
            >
              {valider.isPending && <Spinner />}
              Valider
            </button>
          </>
        )}

        {verrouille && (
          <Toggle
            checked={Boolean(r.partage_le)}
            onChange={(actif) => partager.mutate(actif)}
            label="Remis au client"
            hint="Le rapport apparaît alors dans l'espace de suivi du promoteur."
          />
        )}

        <span className="ml-auto flex flex-wrap items-center gap-1 text-xs text-ink-500">
          Exporter :
          {FORMATS.map((f) => (
            <button
              key={f.cle}
              type="button"
              className="btn-ghost px-2 py-1 text-xs"
              onClick={() => void rapportsApi.exporter(r.id, f.cle)}
            >
              {f.libelle}
            </button>
          ))}
        </span>
      </div>
    </div>
  )
}

export default function PanneauRapports({ mandatId }: { mandatId: string }) {
  const queryClient = useQueryClient()
  const [ouvert, setOuvert] = useState<string | null>(null)
  const [posteId, setPosteId] = useState('')
  const [assistance, setAssistance] = useState(true)
  const [erreur, setErreur] = useState<string | null>(null)
  // Le type se choisit avant tout le reste : c'est lui qui décide des sections.
  const [type, setType] = useState<TypeRapport>('PRESELECTION')

  const rapports = useQuery({
    queryKey: ['rapports', mandatId],
    queryFn: () => rapportsApi.lister(mandatId),
  })
  const postes = useQuery({
    queryKey: ['postes', mandatId],
    queryFn: () => recrutementApi.postes(mandatId),
  })
  const modeles = useQuery({
    queryKey: ['modeles-documents', mandatId],
    queryFn: () => rapportsApi.modeles({ mandat_id: mandatId, usage: 'RAPPORT' }),
  })
  const [modeleId, setModeleId] = useState('')

  const generer = useMutation({
    mutationFn: () =>
      rapportsApi.generer(mandatId, {
        poste_id: posteId || null,
        modele_id: modeleId || null,
        type_rapport: type,
        avec_assistance: assistance,
      }),
    onSuccess: (r) => {
      setErreur(null)
      setOuvert(r.id)
      void queryClient.invalidateQueries({ queryKey: ['rapports', mandatId] })
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Génération impossible'),
  })

  return (
    <div className="space-y-4">
      <section className="card p-5">
        <h2 className="text-sm font-semibold text-ink-900">Rapport de recrutement</h2>
        <p className="mt-1 text-xs text-ink-500">
          Les chiffres sont figés au moment de la génération : le document reste exportable à
          l&apos;identique quoi qu&apos;il advienne des dossiers ensuite. Les textes sont proposés,
          puis relus — jamais signés en l&apos;état.
        </p>

        <div className="mt-4 space-y-2">
          <span className="label mb-0">Type de rapport</span>
          {TYPES_RAPPORT.map((choix) => (
            <label
              key={choix.cle}
              className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 ${
                type === choix.cle
                  ? 'border-brand-400 bg-brand-50/60'
                  : 'border-ink-200 hover:bg-ink-50'
              }`}
            >
              <input
                type="radio"
                name="type-rapport"
                className="mt-0.5 h-4 w-4 border-ink-300 text-ink-900 focus:ring-brand-500"
                checked={type === choix.cle}
                onChange={() => setType(choix.cle)}
              />
              <span>
                <span className="block text-sm font-medium text-ink-900">{choix.libelle}</span>
                <span className="mt-0.5 block text-xs text-ink-500">{choix.quand}</span>
              </span>
            </label>
          ))}
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <select
            className="input py-1.5 text-sm"
            value={posteId}
            aria-label="Poste concerné"
            onChange={(e) => setPosteId(e.target.value)}
          >
            <option value="">Tout le mandat</option>
            {postes.data?.map((poste) => (
              <option key={poste.id} value={poste.id}>
                {poste.intitule}
              </option>
            ))}
          </select>
          <select
            className="input py-1.5 text-sm"
            value={modeleId}
            aria-label="Trame imposée"
            onChange={(e) => setModeleId(e.target.value)}
          >
            <option value="">Trame du cabinet</option>
            {modeles.data?.map((modele) => (
              <option key={modele.id} value={modele.id}>
                {modele.libelle}
              </option>
            ))}
          </select>
        </div>

        <div className="mt-3">
          <Toggle
            checked={assistance}
            onChange={setAssistance}
            label="Proposer une rédaction"
            hint="Décoché, les sections arrivent vides avec leur titre : les tableaux et les chiffres sont produits dans tous les cas."
          />
        </div>

        {erreur && (
          <div className="mt-3">
            <Callout tone="danger">{erreur}</Callout>
          </div>
        )}

        <button
          type="button"
          className="btn-primary mt-4"
          disabled={generer.isPending}
          onClick={() => generer.mutate()}
        >
          {generer.isPending && <Spinner />}
          Générer le rapport
        </button>
      </section>

      {ouvert && <Editeur rapportId={ouvert} onFerme={() => setOuvert(null)} />}

      {rapports.data?.length === 0 ? (
        <EmptyState
          title="Aucun rapport"
          hint="Générez-en un une fois les entretiens tenus : le classement final y figurera."
        />
      ) : (
        <div className="space-y-2">
          {rapports.data?.map((rapport) => (
            <button
              key={rapport.id}
              type="button"
              className="card-interactive flex w-full flex-wrap items-center gap-2 p-3 text-left"
              onClick={() => setOuvert(rapport.id === ouvert ? null : rapport.id)}
            >
              <span className="min-w-0 flex-1 truncate text-sm text-ink-900">{rapport.titre}</span>
              <span className="badge bg-ink-100 text-ink-600">
                {TYPES_RAPPORT.find((t) => t.cle === rapport.type_rapport)?.libelle ??
                  rapport.type_rapport}
              </span>
              {rapport.partage_le && (
                <span className="badge bg-brand-100 text-brand-800">Remis au client</span>
              )}
              <span className={`badge ${STATUT_STYLE[rapport.statut]}`}>
                {STATUT_LIBELLE[rapport.statut]}
              </span>
              {rapport.created_at && (
                <span className="text-xs text-ink-500">
                  {formatDate(rapport.created_at, 'fr')}
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
