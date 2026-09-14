import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { vivierApi, type CriteresVivier, type VivierItem } from '@/lib/api'
import {
  Badge,
  Callout,
  EmptyState,
  ErrorState,
  Field,
  Modal,
  PageLoader,
  Spinner,
  delaiListe,
} from '@/components/ui'
import { formatDate } from '@/lib/format'

/**
 * Le vivier : les profils déjà passés par le cabinet.
 *
 * La page existe pour donner un usage à ce que la purge conserve. Un mandat
 * terminé perd ses fichiers ; les personnes, elles, restent connues — et c'est
 * ici qu'on les retrouve quand un nouveau client demande « un contrôleur de
 * gestion BAC+5 avec dix ans d'expérience ».
 *
 * Deux partis pris d'affichage :
 *
 * - Une identité seulement devinée (dossier arrivé par email, non relu) porte
 *   une mention visible. Sans elle, une supposition se lirait comme un fait.
 * - Un profil dont les fichiers ont été purgés ne s'affiche pas comme abîmé :
 *   c'est l'état normal d'un dossier ancien, et tout ce qui sert à le juger
 *   est là.
 */

const NIVEAUX: Array<[number, string]> = [
  [0, 'BAC'],
  [2, 'BAC+2'],
  [3, 'BAC+3 (licence)'],
  [4, 'BAC+4'],
  [5, 'BAC+5 (master)'],
  [8, 'BAC+8 (doctorat)'],
]

function mentionProvenance(item: { provenance: string; verifie: boolean }) {
  if (item.verifie || item.provenance === 'VERIFIE_RH') {
    return { texte: 'Relu par les RH', ton: 'bg-emerald-100 text-emerald-800' }
  }
  if (item.provenance === 'SAISI_RH') {
    return { texte: 'Saisi par les RH', ton: 'bg-ink-100 text-ink-700' }
  }
  if (item.provenance === 'DECLARE') {
    return { texte: 'Déclaré par le candidat', ton: 'bg-ink-100 text-ink-700' }
  }
  return { texte: 'Deviné, non relu', ton: 'bg-amber-100 text-amber-800' }
}

function ProfilComplet({ id, onClose }: { id: string; onClose: () => void }) {
  const profil = useQuery({ queryKey: ['vivier', id], queryFn: () => vivierApi.profil(id) })

  const p = profil.data
  const titre = p ? `${p.prenom} ${p.nom}`.trim() : 'Profil'
  const mention = p ? mentionProvenance(p) : null

  return (
    <Modal open title={titre} onClose={onClose}>
      {profil.isLoading && <Spinner />}
      {profil.isError && <ErrorState error={profil.error} onRetry={() => profil.refetch()} />}

      {p && (
        <div className="space-y-5 text-sm">
          {mention && (
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={mention.ton}>{mention.texte}</Badge>
              {p.pieces_purgees > 0 && p.pieces_conservees === 0 && (
                <Badge tone="bg-ink-100 text-ink-600">
                  Fichiers purgés — informations conservées
                </Badge>
              )}
            </div>
          )}

          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
              Coordonnées
            </h3>
            <dl className="mt-2 grid grid-cols-[auto,1fr] gap-x-4 gap-y-1">
              {[
                ['Email', p.email],
                ['Téléphone', p.telephone],
                ['Adresse', p.adresse],
                ['Âge', p.age ? `${p.age} ans` : null],
                ['Sexe', p.sexe === 'F' ? 'Féminin' : p.sexe === 'M' ? 'Masculin' : null],
                ['Nationalité', p.nationalites.join(', ') || null],
                ['Langues', p.langues.join(', ') || null],
              ]
                .filter(([, valeur]) => valeur)
                .map(([libelle, valeur]) => (
                  <div key={libelle} className="contents">
                    <dt className="text-ink-500">{libelle}</dt>
                    <dd className="text-ink-900">{valeur}</dd>
                  </div>
                ))}
            </dl>
          </section>

          {p.diplomes.length > 0 && (
            <section>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                Formation
              </h3>
              <ul className="mt-2 space-y-1.5">
                {p.diplomes.map((d, i) => (
                  <li key={i} className="text-ink-800">
                    <span className="font-medium">{d.intitule}</span>
                    <span className="text-ink-500">
                      {' '}
                      · {d.niveau_libelle ?? `BAC+${d.niveau}`} · {d.domaine}
                      {d.etablissement ? ` · ${d.etablissement}` : ''}
                      {d.annee ? ` · ${d.annee}` : ''}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {p.experiences.length > 0 && (
            <section>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                Parcours · {p.annees_experience} an(s) au total
              </h3>
              <ul className="mt-2 space-y-1.5">
                {p.experiences.map((e, i) => (
                  <li key={i} className="text-ink-800">
                    <span className="font-medium">{e.poste}</span>
                    <span className="text-ink-500">
                      {' '}
                      · {e.employeur} · {formatDate(e.debut, 'fr')} →{' '}
                      {e.fin ? formatDate(e.fin, 'fr') : 'en poste'}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
              Candidatures passées
            </h3>
            {p.historique.length === 0 ? (
              <p className="mt-2 text-ink-500">Aucune candidature enregistrée.</p>
            ) : (
              <ul className="mt-2 space-y-2">
                {p.historique.map((h) => (
                  <li key={h.candidature_id} className="rounded-lg border border-ink-100 p-2.5">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <Link
                        to={`/postes/${h.poste_id}`}
                        className="font-medium text-ink-900 hover:underline"
                        onClick={onClose}
                      >
                        {h.poste}
                      </Link>
                      {h.note !== null && (
                        <span className="tabular-nums text-ink-700">
                          {h.note} / {h.note_max}
                        </span>
                      )}
                    </div>
                    <p className="mt-0.5 text-xs text-ink-500">
                      {h.client} · {h.mandat} · {formatDate(h.recue_le, 'fr')}
                      {h.mandat_archive ? ' · mandat archivé' : ''}
                      {h.pieces_conservees === 0 && h.pieces_purgees > 0
                        ? ' · fichiers purgés'
                        : ''}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}

      <div className="mt-5 flex justify-end">
        <button type="button" className="btn-ghost" onClick={onClose}>
          Fermer
        </button>
      </div>
    </Modal>
  )
}

function Carte({
  item,
  rang,
  onOuvrir,
}: {
  item: VivierItem
  rang: number
  onOuvrir: () => void
}) {
  const mention = mentionProvenance(item)
  const purge = item.pieces_conservees === 0 && item.pieces_purgees > 0

  return (
    <button
      type="button"
      onClick={onOuvrir}
      className="card-interactive stagger w-full animate-rise p-4 text-left"
      style={delaiListe(rang)}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="font-semibold text-ink-900">
          {item.prenom} {item.nom}
        </span>
        <span className="text-xs text-ink-500">
          {item.nombre_candidatures} candidature(s)
          {item.derniere_candidature
            ? ` · dernière le ${formatDate(item.derniere_candidature, 'fr')}`
            : ''}
        </span>
      </div>

      <p className="mt-1 text-sm text-ink-700">
        {item.dernier_poste ?? item.diplome_principal ?? 'Parcours non renseigné'}
        {item.dernier_employeur ? ` — ${item.dernier_employeur}` : ''}
      </p>

      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {item.niveau_libelle && <Badge>{item.niveau_libelle}</Badge>}
        {item.annees_experience > 0 && <Badge>{item.annees_experience} an(s) d'expérience</Badge>}
        {item.age !== null && <Badge>{item.age} ans</Badge>}
        {item.nationalites.map((n) => (
          <Badge key={n}>{n}</Badge>
        ))}
        <Badge tone={mention.ton}>{mention.texte}</Badge>
        {purge && <Badge tone="bg-ink-100 text-ink-600">Fichiers purgés</Badge>}
      </div>

      {(item.email || item.telephone) && (
        <p className="mt-2 text-xs text-ink-500">
          {[item.email, item.telephone].filter(Boolean).join(' · ')}
        </p>
      )}
    </button>
  )
}

export default function VivierPage() {
  const [criteres, setCriteres] = useState<CriteresVivier>({})
  const [texte, setTexte] = useState('')
  const [ouvert, setOuvert] = useState<string | null>(null)

  const resultats = useQuery({
    queryKey: ['vivier', criteres],
    queryFn: () => vivierApi.rechercher(criteres),
  })

  const modifier = (champ: keyof CriteresVivier, valeur: string) =>
    setCriteres((c) => ({
      ...c,
      [champ]: valeur === '' ? undefined : champ === 'domaine' || champ === 'nationalite' || champ === 'sexe' ? valeur : Number(valeur),
    }))

  const sensible =
    criteres.sexe !== undefined ||
    criteres.age_min !== undefined ||
    criteres.age_max !== undefined ||
    (criteres.nationalite ?? '') !== ''

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-xl font-semibold tracking-tight text-ink-900">Vivier</h1>
        <p className="mt-1 text-sm text-ink-500">
          Toutes les personnes déjà passées par le cabinet, tous mandats confondus. Ce que la
          purge d'un mandat archivé conserve se retrouve ici : identité, coordonnées, diplômes,
          parcours et notes obtenues. Seuls les fichiers disparaissent.
        </p>
      </div>

      <section className="card mb-5 p-4">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            setCriteres((c) => ({ ...c, recherche: texte.trim() || undefined }))
          }}
          className="space-y-3"
        >
          <Field
            label="Rechercher"
            htmlFor="vivier-recherche"
            hint="Cherche dans le nom, l'email, les diplômes, les postes occupés et les employeurs."
          >
            <div className="flex gap-2">
              <input
                id="vivier-recherche"
                className="input"
                value={texte}
                placeholder="contrôle de gestion, hôpital, Sarakawa…"
                onChange={(e) => setTexte(e.target.value)}
              />
              <button type="submit" className="btn-primary shrink-0">
                Chercher
              </button>
            </div>
          </Field>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Field label="Diplôme au moins" htmlFor="vivier-niveau">
              <select
                id="vivier-niveau"
                className="input"
                value={criteres.niveau_min ?? ''}
                onChange={(e) => modifier('niveau_min', e.target.value)}
              >
                <option value="">Indifférent</option>
                {NIVEAUX.map(([valeur, libelle]) => (
                  <option key={valeur} value={valeur}>
                    {libelle}
                  </option>
                ))}
              </select>
            </Field>

            <Field label="Expérience minimale (ans)" htmlFor="vivier-exp">
              <input
                id="vivier-exp"
                type="number"
                min={0}
                max={60}
                className="input"
                value={criteres.annees_experience_min ?? ''}
                onChange={(e) => modifier('annees_experience_min', e.target.value)}
              />
            </Field>

            <Field label="Domaine" htmlFor="vivier-domaine">
              <input
                id="vivier-domaine"
                className="input"
                value={criteres.domaine ?? ''}
                placeholder="finance, santé…"
                onChange={(e) => modifier('domaine', e.target.value)}
              />
            </Field>

            <Field label="Nationalité" htmlFor="vivier-nationalite">
              <input
                id="vivier-nationalite"
                className="input"
                value={criteres.nationalite ?? ''}
                placeholder="togolaise…"
                onChange={(e) => modifier('nationalite', e.target.value)}
              />
            </Field>

            <Field label="Sexe" htmlFor="vivier-sexe">
              <select
                id="vivier-sexe"
                className="input"
                value={criteres.sexe ?? ''}
                onChange={(e) => modifier('sexe', e.target.value)}
              >
                <option value="">Indifférent</option>
                <option value="F">Féminin</option>
                <option value="M">Masculin</option>
              </select>
            </Field>

            <Field label="Âge minimum" htmlFor="vivier-age-min">
              <input
                id="vivier-age-min"
                type="number"
                min={15}
                max={100}
                className="input"
                value={criteres.age_min ?? ''}
                onChange={(e) => modifier('age_min', e.target.value)}
              />
            </Field>

            <Field label="Âge maximum" htmlFor="vivier-age-max">
              <input
                id="vivier-age-max"
                type="number"
                min={15}
                max={100}
                className="input"
                value={criteres.age_max ?? ''}
                onChange={(e) => modifier('age_max', e.target.value)}
              />
            </Field>

            <div className="flex items-end">
              <button
                type="button"
                className="btn-ghost"
                onClick={() => {
                  setTexte('')
                  setCriteres({})
                }}
              >
                Tout effacer
              </button>
            </div>
          </div>
        </form>

        {sensible && (
          <div className="mt-3">
            <Callout tone="warning">
              Vous filtrez sur le sexe, l'âge ou la nationalité. C'est légitime quand le poste
              pose la condition, et cette recherche est enregistrée au journal — comme les
              conditions restrictives d'une fiche de poste.
            </Callout>
          </div>
        )}
      </section>

      {resultats.isLoading && <PageLoader />}
      {resultats.isError && (
        <ErrorState error={resultats.error} onRetry={() => resultats.refetch()} />
      )}

      {resultats.data && (
        <>
          <p className="mb-3 text-sm text-ink-500">
            {resultats.data.total} profil(s)
            {resultats.data.total > resultats.data.items.length
              ? ` · ${resultats.data.items.length} affiché(s)`
              : ''}
          </p>

          {resultats.data.items.length === 0 ? (
            <EmptyState
              title="Aucun profil ne correspond"
              hint="Élargissez la recherche, ou vérifiez qu'au moins une candidature a été enregistrée."
            />
          ) : (
            <div className="grid gap-3">
              {resultats.data.items.map((item, index) => (
                <Carte
                  key={item.id}
                  item={item}
                  rang={index}
                  onOuvrir={() => setOuvert(item.id)}
                />
              ))}
            </div>
          )}
        </>
      )}

      {ouvert && <ProfilComplet id={ouvert} onClose={() => setOuvert(null)} />}
    </div>
  )
}
