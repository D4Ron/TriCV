import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { recrutementApi } from '@/lib/api'
import { Callout, Spinner } from '@/components/ui'
import type { BaremeDetail, BaremeExperienceDetail, LigneGrilleSelection } from '@/types'

/**
 * Le barème du poste et la grille de sélection qui en découle, sous la main.
 *
 * Trois barèmes entre lesquels on bascule d'un clic : celui du cabinet
 * (3 / 7 / 5 / 15, la courbe par défaut), celui que propose l'assistance à
 * partir de la fiche de poste, et un réglage personnalisé. Rien ne s'applique
 * sans le bouton « Appliquer » : la grille affichée est un aperçu tant que le
 * barème n'est pas celui du poste. Appliquer recalcule les notes.
 */

type Mode = 'cabinet' | 'ia' | 'perso'

const MODES: { valeur: Mode; libelle: string; aide: string }[] = [
  { valeur: 'cabinet', libelle: 'Barème du cabinet', aide: 'La répartition type, sans réglage.' },
  { valeur: 'ia', libelle: "Proposition de l'IA", aide: 'Réglée à partir de la fiche de poste.' },
  { valeur: 'perso', libelle: 'Personnalisé', aide: 'Réglez chaque courbe vous-même.' },
]

// Le seuil vit sur le poste et se règle à part : il ne distingue pas deux barèmes.
const sansSeuil = (b: unknown) =>
  b && typeof b === 'object' ? { ...(b as object), seuil_preselection: undefined } : b
const identique = (a: unknown, b: unknown) =>
  JSON.stringify(sansSeuil(a)) === JSON.stringify(sansSeuil(b))
const pts = (n: number) => `${Math.round(n * 100) / 100}`.replace('.', ',')

/** Ce qu'un candidat obtient au niveau exigé, et ce qui reste à gagner au-delà. */
function repartition(b: BaremeDetail) {
  const c = b.consistance
  return [
    {
      code: 'CD',
      libelle: 'Consistance du dossier',
      max: c.points_max,
      acquis: c.points_dossier_complet + c.points_coherence,
    },
    {
      code: 'FA',
      libelle: 'Formation académique',
      max: b.formation.points_max,
      acquis: b.formation.points_niveau_requis,
    },
    {
      code: 'EG',
      libelle: 'Expérience générale',
      max: b.experience_generale.points_max,
      acquis: b.experience_generale.points_au_seuil,
    },
    {
      code: 'ES',
      libelle: 'Expérience spécifique',
      max: b.experience_specifique.points_max,
      acquis: b.experience_specifique.points_au_seuil,
    },
  ]
}

function BarreRepartition({ bareme }: { bareme: BaremeDetail }) {
  const parts = repartition(bareme)
  const total = bareme.total_max || 30
  const conforme = parts.reduce((s, p) => s + Math.min(p.acquis, p.max), 0)
  return (
    <div>
      <div className="flex h-11 w-full overflow-hidden rounded-lg border border-ink-200">
        {parts.map((p, i) => (
          <div
            key={p.code}
            className={`flex h-full ${i > 0 ? 'border-l-2 border-white' : ''}`}
            style={{ width: `${(p.max / total) * 100}%` }}
            title={`${p.libelle} : ${pts(p.acquis)} au niveau exigé, ${pts(p.max)} au plus`}
          >
            <div
              className="flex h-full items-center justify-center bg-brand-700 text-[11px] font-semibold text-white"
              style={{ width: `${(Math.min(p.acquis, p.max) / p.max) * 100}%` }}
            >
              {p.code}
            </div>
            <div className="h-full flex-1 bg-brand-200" />
          </div>
        ))}
      </div>
      <div className="mt-2 grid grid-cols-4 gap-2 text-[11px] text-ink-600">
        {parts.map((p) => (
          <div key={p.code}>
            <span className="font-semibold text-ink-900">{p.code}</span> · {pts(p.max)} pts
            <div className="text-ink-500">{pts(p.acquis)} au seuil</div>
          </div>
        ))}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-4 text-[11px] text-ink-500">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-sm bg-brand-700" />
          Acquis au niveau exigé (candidat conforme : {pts(conforme)}/{pts(total)})
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-sm bg-brand-200" />
          À gagner au-delà de l&apos;exigence
        </span>
      </div>
    </div>
  )
}

function Curseur({
  label,
  valeur,
  max,
  pas = 0.25,
  onChange,
  suffixe = 'pts',
}: {
  label: string
  valeur: number
  max: number
  pas?: number
  onChange: (v: number) => void
  suffixe?: string
}) {
  return (
    <label className="block">
      <span className="flex justify-between text-xs text-ink-600">
        {label}
        <span className="font-semibold text-ink-900">
          {pts(valeur)} {suffixe}
        </span>
      </span>
      <input
        type="range"
        className="mt-1 w-full accent-brand-700"
        min={0}
        max={max}
        step={pas}
        value={valeur}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  )
}

function ReglagesExperience({
  titre,
  valeur,
  onChange,
}: {
  titre: string
  valeur: BaremeExperienceDetail
  onChange: (v: BaremeExperienceDetail) => void
}) {
  return (
    <fieldset className="rounded-lg border border-ink-200 p-3">
      <legend className="px-1 text-xs font-semibold text-ink-900">
        {titre} — {pts(valeur.points_max)} pts
      </legend>
      <div className="grid gap-3 sm:grid-cols-3">
        <Curseur
          label="Au seuil exigé"
          valeur={valeur.points_au_seuil}
          max={valeur.points_max}
          onChange={(v) => onChange({ ...valeur, points_au_seuil: v })}
        />
        <Curseur
          label="Par année en plus"
          valeur={valeur.points_par_annee_supplementaire}
          max={Math.max(valeur.points_max - valeur.points_au_seuil, 0)}
          pas={0.1}
          onChange={(v) => onChange({ ...valeur, points_par_annee_supplementaire: v })}
        />
        <Curseur
          label="Années comptées au plus"
          valeur={valeur.annees_supplementaires_max ?? 20}
          max={20}
          pas={1}
          suffixe="an(s)"
          onChange={(v) => onChange({ ...valeur, annees_supplementaires_max: v })}
        />
      </div>
    </fieldset>
  )
}

function TableauGrille({ lignes, total }: { lignes: LigneGrilleSelection[]; total: number }) {
  return (
    <table className="w-full border-collapse text-xs">
      <thead>
        <tr className="border-b border-ink-300 text-left text-[11px] uppercase tracking-wide text-ink-500">
          <th className="w-12 py-1.5" />
          <th className="py-1.5">Critères</th>
          <th className="w-14 py-1.5 text-right">Note</th>
        </tr>
      </thead>
      <tbody>
        {lignes.map((l) => (
          <tr key={l.numero + l.libelle} className="border-b border-ink-100 align-top">
            <td className={`py-1.5 pr-2 ${l.niveau < 3 ? 'font-semibold text-ink-900' : 'text-ink-500'}`}>
              {l.numero}
            </td>
            <td
              className={`py-1.5 pr-2 ${
                l.niveau === 1
                  ? 'font-semibold text-brand-700'
                  : l.niveau === 2
                    ? 'font-semibold text-ink-900'
                    : 'text-ink-700'
              }`}
            >
              {l.libelle}
              {l.eliminatoire && (
                <span className="ml-2 rounded bg-red-50 px-1.5 py-0.5 text-[10px] font-semibold text-red-700">
                  Critère éliminatoire
                </span>
              )}
            </td>
            <td
              className={`py-1.5 text-right tabular-nums ${
                l.niveau < 3 ? 'font-semibold text-brand-700' : 'text-ink-700'
              }`}
            >
              {pts(l.points)}
            </td>
          </tr>
        ))}
        <tr>
          <td />
          <td className="py-2 font-bold text-ink-900">TOTAL</td>
          <td className="py-2 text-right font-bold text-brand-700">{pts(total)}</td>
        </tr>
      </tbody>
    </table>
  )
}

export default function GrilleSelectionPanneau({
  posteId,
  onClose,
}: {
  posteId: string
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const grille = useQuery({
    queryKey: ['grille-selection', posteId],
    queryFn: () => recrutementApi.grilleSelection(posteId),
  })
  const [mode, setMode] = useState<Mode | null>(null)
  const [brouillon, setBrouillon] = useState<BaremeDetail | null>(null)
  const [suggestion, setSuggestion] = useState<{ bareme: BaremeDetail; justification: string } | null>(
    null,
  )
  const [message, setMessage] = useState<string | null>(null)

  // Au chargement : le barème en vigueur, et le mode qui lui correspond.
  useEffect(() => {
    if (grille.data && brouillon === null) {
      setBrouillon(grille.data.bareme)
      setMode(identique(grille.data.bareme, grille.data.bareme_cabinet) ? 'cabinet' : 'perso')
    }
  }, [grille.data, brouillon])

  useEffect(() => {
    const surTouche = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', surTouche)
    return () => document.removeEventListener('keydown', surTouche)
  }, [onClose])

  // L'aperçu suit le brouillon, avec un léger délai pendant qu'on glisse.
  const [cle, setCle] = useState('')
  useEffect(() => {
    const id = window.setTimeout(() => setCle(JSON.stringify(brouillon)), 250)
    return () => window.clearTimeout(id)
  }, [brouillon])
  const apercu = useQuery({
    queryKey: ['grille-selection-apercu', posteId, cle],
    queryFn: () => recrutementApi.apercuGrilleSelection(posteId, JSON.parse(cle) as BaremeDetail),
    enabled: cle !== '' && cle !== 'null',
    placeholderData: (precedent) => precedent,
  })

  const suggerer = useMutation({
    mutationFn: () => recrutementApi.suggererBareme(posteId),
    onSuccess: (r) => {
      setSuggestion({ bareme: r.bareme, justification: r.justification })
      setBrouillon(r.bareme)
    },
  })

  const appliquer = useMutation({
    mutationFn: (b: BaremeDetail) => recrutementApi.definirBareme(posteId, b),
    onSuccess: () => {
      setMessage('Barème appliqué. Les notes du poste ont été recalculées.')
      void queryClient.invalidateQueries({ queryKey: ['grille-selection', posteId] })
      void queryClient.invalidateQueries({ queryKey: ['grille', posteId] })
      void queryClient.invalidateQueries({ queryKey: ['poste', posteId] })
    },
  })

  const telecharger = useMutation({
    mutationFn: () => recrutementApi.telechargerGrilleSelection(posteId),
  })

  const choisir = (m: Mode) => {
    setMessage(null)
    setMode(m)
    if (!grille.data) return
    if (m === 'cabinet') setBrouillon(grille.data.bareme_cabinet)
    if (m === 'ia') {
      if (suggestion) setBrouillon(suggestion.bareme)
      else suggerer.mutate()
    }
  }

  const modifier = (b: BaremeDetail) => {
    setMessage(null)
    setMode('perso')
    setBrouillon(b)
  }

  const enVigueur = grille.data?.bareme
  const nonApplique = useMemo(
    () => brouillon !== null && enVigueur !== undefined && !identique(brouillon, enVigueur),
    [brouillon, enVigueur],
  )
  const lignes = apercu.data?.lignes ?? grille.data?.lignes ?? []
  const f = brouillon?.formation

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-ink-900/40" onClick={onClose} role="dialog" aria-modal="true">
      <div
        className="flex h-full w-full max-w-3xl flex-col bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 border-b border-ink-200 px-5 py-4">
          <div>
            <h2 className="text-base font-semibold text-ink-900">Barème et grille de sélection</h2>
            <p className="text-xs text-ink-500">
              {grille.data?.intitule} · la grille est celle que la présélection applique.
            </p>
          </div>
          <button type="button" className="btn-ghost -my-1 px-2 py-1 text-lg leading-none" onClick={onClose} aria-label="Fermer">
            ×
          </button>
        </div>

        <div className="flex-1 space-y-5 overflow-y-auto px-5 py-4 text-sm text-ink-700">
          {grille.isLoading || !brouillon ? (
            <div className="flex justify-center py-10">
              <Spinner className="h-6 w-6" />
            </div>
          ) : (
            <>
              <div className="grid gap-2 sm:grid-cols-3" role="radiogroup" aria-label="Barème">
                {MODES.map((m) => (
                  <button
                    key={m.valeur}
                    type="button"
                    role="radio"
                    aria-checked={mode === m.valeur}
                    onClick={() => choisir(m.valeur)}
                    className={`rounded-lg border p-3 text-left transition ${
                      mode === m.valeur
                        ? 'border-brand-700 bg-brand-50 ring-1 ring-brand-700'
                        : 'border-ink-200 hover:border-ink-300'
                    }`}
                  >
                    <span className="flex items-center gap-2 text-sm font-semibold text-ink-900">
                      {m.valeur === 'ia' && suggerer.isPending && <Spinner />}
                      {m.libelle}
                    </span>
                    <span className="text-xs text-ink-500">{m.aide}</span>
                  </button>
                ))}
              </div>

              {suggerer.isError && mode === 'ia' && (
                <Callout tone="danger">{(suggerer.error as Error).message}</Callout>
              )}
              {mode === 'ia' && suggestion?.justification && (
                <Callout tone="info">{suggestion.justification}</Callout>
              )}

              <BarreRepartition bareme={brouillon} />

              {mode === 'perso' && f && (
                <div className="space-y-3">
                  <fieldset className="rounded-lg border border-ink-200 p-3">
                    <legend className="px-1 text-xs font-semibold text-ink-900">
                      Formation académique — {pts(f.points_max)} pts
                    </legend>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <Curseur
                        label="Au niveau de diplôme exigé"
                        valeur={f.points_niveau_requis}
                        max={f.points_max}
                        onChange={(v) => modifier({ ...brouillon, formation: { ...f, points_niveau_requis: v } })}
                      />
                      <Curseur
                        label="Par niveau de diplôme au-dessus"
                        valeur={f.points_par_niveau_superieur}
                        max={f.points_max - f.points_niveau_requis}
                        onChange={(v) =>
                          modifier({ ...brouillon, formation: { ...f, points_par_niveau_superieur: v } })
                        }
                      />
                      <Curseur
                        label="Par certification professionnelle"
                        valeur={f.points_par_certification}
                        max={f.points_max - f.points_niveau_requis}
                        onChange={(v) =>
                          modifier({ ...brouillon, formation: { ...f, points_par_certification: v } })
                        }
                      />
                      <Curseur
                        label="Formation complémentaire souhaitée"
                        valeur={f.points_formation_complementaire}
                        max={f.points_max - f.points_niveau_requis}
                        onChange={(v) =>
                          modifier({ ...brouillon, formation: { ...f, points_formation_complementaire: v } })
                        }
                      />
                    </div>
                    <p className="hint mt-2">
                      Les points au-delà du niveau exigé se prennent dans les {pts(f.points_max)} : la
                      formation ne dépasse jamais son maximum.
                    </p>
                  </fieldset>
                  <ReglagesExperience
                    titre="Expérience générale"
                    valeur={brouillon.experience_generale}
                    onChange={(v) => modifier({ ...brouillon, experience_generale: v })}
                  />
                  <ReglagesExperience
                    titre="Expérience spécifique"
                    valeur={brouillon.experience_specifique}
                    onChange={(v) => modifier({ ...brouillon, experience_specifique: v })}
                  />
                </div>
              )}

              <div>
                <div className="mb-2 flex items-center gap-2">
                  <h3 className="text-sm font-semibold text-ink-900">Grille de notation</h3>
                  {nonApplique ? (
                    <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[11px] font-medium text-amber-700">
                      Aperçu — pas encore appliqué
                    </span>
                  ) : (
                    <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[11px] font-medium text-emerald-700">
                      En vigueur
                    </span>
                  )}
                  {apercu.isFetching && <Spinner />}
                </div>
                {apercu.isError && <Callout tone="danger">{(apercu.error as Error).message}</Callout>}
                <TableauGrille lignes={lignes} total={brouillon.total_max} />
              </div>

              {message && <Callout tone="success">{message}</Callout>}
              {appliquer.isError && <Callout tone="danger">{(appliquer.error as Error).message}</Callout>}
            </>
          )}
        </div>

        <div className="flex flex-wrap justify-end gap-2 border-t border-ink-200 px-5 py-3">
          <button
            type="button"
            className="btn-ghost"
            disabled={telecharger.isPending || nonApplique}
            title={nonApplique ? "Appliquez d'abord le barème : le document reprend celui en vigueur." : undefined}
            onClick={() => telecharger.mutate()}
          >
            {telecharger.isPending && <Spinner />}
            Télécharger (Word)
          </button>
          <button
            type="button"
            className="btn-primary"
            disabled={!nonApplique || appliquer.isPending || !brouillon}
            onClick={() => brouillon && appliquer.mutate(brouillon)}
          >
            {appliquer.isPending && <Spinner />}
            Appliquer ce barème
          </button>
        </div>
      </div>
    </div>
  )
}
