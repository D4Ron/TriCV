import { useEffect, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { santeApi, type EtatVerification, type Verification } from '@/lib/api'
import { ErrorState, PageLoader, Spinner } from '@/components/ui'
import ColonnesJour from '@/components/ColonnesJour'

/**
 * L'état de l'application, tel que l'administrateur doit pouvoir le lire.
 *
 * Ce qui manquait se découvrait jusqu'ici à l'usage, et souvent par un tiers :
 * un candidat qui n'arrive pas à déposer, un avis qui sort en squelette, un
 * courriel qui ne part pas. Cet onglet dit, en un regard, ce qui est en place,
 * ce qui ne l'est pas, et où le régler — puis si les candidats arrivent.
 *
 * Deux constats ne viennent pas du serveur et sont mesurés ici. La clé du
 * modèle : qu'elle soit renseignée ne prouve pas qu'elle soit acceptée, d'où
 * l'essai réel. La limite du serveur frontal : il refuse les envois trop
 * lourds avant que l'application les voie, et seul un navigateur peut s'en
 * apercevoir.
 *
 * Chaque état porte une icône et un mot, jamais une couleur seule.
 */

type Onglet = 'general' | 'courriel' | 'comptes'

// Un dossier ordinaire dépasse le mégaoctet du réglage par défaut de nginx :
// c'est cette barre-là qu'il faut franchir pour savoir si les candidats passent.
const SONDE_OCTETS = Math.round(1.5 * 1024 * 1024)
const SONDE_GRANDE = 10 * 1024 * 1024

const LIBELLES: Record<EtatVerification, string> = {
  ok: 'En place',
  a_regler: 'À régler',
  a_verifier: 'À vérifier',
  info: 'Pour info',
}

const TONS: Record<EtatVerification, string> = {
  ok: 'text-emerald-700 bg-emerald-50 border-emerald-200',
  a_regler: 'text-red-700 bg-red-50 border-red-200',
  a_verifier: 'text-amber-800 bg-amber-50 border-amber-200',
  info: 'text-ink-600 bg-ink-50 border-ink-200',
}

function Icone({ etat }: { etat: EtatVerification }) {
  const chemin = {
    ok: 'M4 8.5 7 11.5 12 5',
    a_regler: 'M8 4.5V9M8 11.5v.01',
    a_verifier: 'M5.5 8h.01M8 8h.01M10.5 8h.01',
    info: 'M8 7v4.5M8 4.5v.01',
  }[etat]
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" className="shrink-0">
      <circle cx="8" cy="8" r="7.25" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d={chemin} fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function Pastille({ etat }: { etat: EtatVerification }) {
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium ${TONS[etat]}`}
    >
      <Icone etat={etat} />
      {LIBELLES[etat]}
    </span>
  )
}

const ONGLETS_LIBELLES: Record<string, string> = {
  courriel: 'Paramètres › Courriel',
  comptes: 'Paramètres › Utilisateurs',
  general: 'Paramètres › Général',
}

export default function EtatApplication({ onAller }: { onAller: (o: Onglet) => void }) {
  const etat = useQuery({ queryKey: ['sante'], queryFn: santeApi.etat })

  // La limite du frontal, mesurée une fois à l'ouverture de l'onglet.
  const sonde = useMutation({ mutationFn: (octets: number) => santeApi.sonderDepot(octets) })
  const [tailleSondee, setTailleSondee] = useState(SONDE_OCTETS)
  useEffect(() => {
    sonde.mutate(SONDE_OCTETS)
    // Une mesure par ouverture : elle coûte un envoi de quelques mégaoctets.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const ia = useMutation({ mutationFn: santeApi.testerIa })

  if (etat.isLoading) return <PageLoader />
  if (etat.isError) return <ErrorState error={etat.error} onRetry={() => etat.refetch()} />
  const donnees = etat.data!

  // Les constats du serveur, complétés par ce que l'écran a mesuré.
  const verifications: Verification[] = donnees.verifications.map((v) => {
    if (v.code === 'depot') {
      if (sonde.isPending) return { ...v, detail: 'Mesure en cours…' }
      if (sonde.isError)
        return { ...v, detail: 'La mesure n’a pas abouti : la connexion a été interrompue.' }
      if (sonde.data) {
        const mo = (tailleSondee / 1048576).toLocaleString('fr', { maximumFractionDigits: 1 })
        return sonde.data.passe
          ? {
              ...v,
              etat: 'ok',
              detail: `Un envoi de ${mo} Mo passe le serveur frontal (${sonde.data.secondes} s).`,
            }
          : {
              ...v,
              etat: 'a_regler',
              detail:
                sonde.data.statut === 413
                  ? `Le serveur frontal refuse un envoi de ${mo} Mo : les candidats ne peuvent pas déposer un dossier ordinaire. Dans la configuration nginx : client_max_body_size 0;`
                  : `La sonde a reçu une erreur ${sonde.data.statut}.`,
            }
      }
    }
    if (v.code === 'ia' && ia.data) {
      return ia.data.ok
        ? { ...v, etat: 'ok', detail: `${ia.data.detail} (${ia.data.secondes} s) La clé est acceptée.` }
        : { ...v, etat: 'a_regler', detail: `Essai échoué : ${ia.data.detail}` }
    }
    return v
  })

  const aRegler = verifications.filter((v) => v.etat === 'a_regler').length
  const aVerifier = verifications.filter((v) => v.etat === 'a_verifier').length
  const f = donnees.frequentation

  return (
    <div className="space-y-6">
      {/* La réponse d'abord : tout va bien, ou combien de choses restent. */}
      <section className="card p-5">
        <div className="flex flex-wrap items-center gap-3">
          <Pastille etat={aRegler ? 'a_regler' : aVerifier ? 'a_verifier' : 'ok'} />
          <h2 className="text-base font-semibold text-ink-900">
            {aRegler
              ? `${aRegler} point${aRegler > 1 ? 's' : ''} à régler`
              : aVerifier
                ? 'Mesure en cours'
                : 'Tout est en place'}
          </h2>
          <button
            type="button"
            className="btn-ghost ml-auto px-3 py-1.5 text-xs"
            disabled={etat.isFetching}
            onClick={() => {
              void etat.refetch()
              setTailleSondee(SONDE_OCTETS)
              sonde.mutate(SONDE_OCTETS)
            }}
          >
            {etat.isFetching && <Spinner />}
            Revérifier
          </button>
        </div>

        <ul className="mt-4 divide-y divide-ink-100">
          {verifications.map((v) => (
            // Sur un téléphone, l'état et l'action partagent la première ligne
            // et le texte prend toute la largeur dessous : en colonne, il
            // n'avait plus que quelques lettres de large.
            <li key={v.code} className="flex flex-wrap items-start gap-x-4 gap-y-2 py-3">
              <div className="shrink-0 pt-0.5 sm:w-28">
                <Pastille etat={v.etat} />
              </div>
              <div className="order-last min-w-0 basis-full sm:order-none sm:flex-1 sm:basis-0">
                <p className="text-sm font-medium text-ink-900">{v.libelle}</p>
                <p className="mt-0.5 break-words text-xs leading-relaxed text-ink-600">{v.detail}</p>
              </div>
              <div className="ml-auto shrink-0 sm:ml-0">
                {v.code === 'ia' && (
                  <button
                    type="button"
                    className="btn-ghost px-3 py-1.5 text-xs"
                    disabled={ia.isPending}
                    onClick={() => ia.mutate()}
                  >
                    {ia.isPending && <Spinner />}
                    Essayer
                  </button>
                )}
                {v.code === 'depot' && sonde.data?.passe && tailleSondee < SONDE_GRANDE && (
                  <button
                    type="button"
                    className="btn-ghost px-3 py-1.5 text-xs"
                    disabled={sonde.isPending}
                    onClick={() => {
                      setTailleSondee(SONDE_GRANDE)
                      sonde.mutate(SONDE_GRANDE)
                    }}
                  >
                    Mesurer avec 10 Mo
                  </button>
                )}
                {v.etat !== 'ok' && v.ou && v.ou !== 'serveur' && ONGLETS_LIBELLES[v.ou] && (
                  <button
                    type="button"
                    className="text-xs font-medium text-brand-700 underline"
                    onClick={() => onAller(v.ou as Onglet)}
                  >
                    {ONGLETS_LIBELLES[v.ou]}
                  </button>
                )}
                {v.etat === 'a_regler' && v.ou === 'serveur' && (
                  <span className="text-xs text-ink-500">Sur le serveur</span>
                )}
              </div>
            </li>
          ))}
        </ul>
      </section>

      {/* La fréquentation : les candidats arrivent-ils, et repartent-ils sans déposer ? */}
      <section className="card p-5">
        <h2 className="text-sm font-semibold text-ink-900">Fréquentation — 30 derniers jours</h2>
        <p className="mt-1 text-xs text-ink-500">
          Compté depuis la mise en service de cet onglet. Aucun visiteur n&apos;est identifié : un
          compteur par jour, sans adresse ni navigateur.
        </p>

        <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Tuile libelle="Visites" valeur={f.totaux.visites} />
          <Tuile libelle="Candidatures déposées" valeur={f.totaux.candidatures} />
          <Tuile
            libelle="Dépôts refusés (taille)"
            valeur={f.totaux.refus_taille}
            alerte={f.totaux.refus_taille > 0}
          />
          <Tuile libelle="Dépôts interrompus" valeur={f.totaux.echecs} alerte={f.totaux.echecs > 0} />
        </dl>

        <div className="mt-5 grid gap-5 md:grid-cols-3">
          <ColonnesJour
            titre="Visites par jour"
            unite="visites"
            points={f.jours.map((j) => ({ jour: j.jour, valeur: j.visites }))}
          />
          <ColonnesJour
            titre="Candidatures par jour"
            unite="candidatures"
            points={f.jours.map((j) => ({ jour: j.jour, valeur: j.candidatures }))}
          />
          <ColonnesJour
            titre="Dépôts refusés par jour"
            unite="dépôts refusés"
            points={f.jours.map((j) => ({ jour: j.jour, valeur: j.refus_taille }))}
          />
        </div>

        {f.par_poste.length > 0 && (
          <div className="mt-6 overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="mb-2 text-left text-xs font-medium text-ink-700">Par poste</caption>
              <thead>
                <tr className="border-b border-ink-200 text-left text-xs text-ink-500">
                  <th className="py-2 pr-3 font-medium">Poste</th>
                  <th className="py-2 pr-3 text-right font-medium">Visites</th>
                  <th className="py-2 pr-3 text-right font-medium">Candidatures</th>
                  <th className="py-2 pr-3 text-right font-medium">Refusés</th>
                  <th className="py-2 text-right font-medium" title="Candidatures pour 100 visites">
                    Taux
                  </th>
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {f.par_poste.map((l) => (
                  <tr key={l.poste_id} className="border-b border-ink-100">
                    <td className="max-w-[16rem] truncate py-2 pr-3 text-ink-800" title={l.intitule}>
                      {l.intitule}
                    </td>
                    <td className="py-2 pr-3 text-right text-ink-700">{l.visites}</td>
                    <td className="py-2 pr-3 text-right text-ink-700">{l.candidatures}</td>
                    <td className={`py-2 pr-3 text-right ${l.refus_taille ? 'font-semibold text-red-700' : 'text-ink-700'}`}>
                      {l.refus_taille}
                    </td>
                    <td className="py-2 text-right text-ink-700">
                      {l.visites ? `${Math.round((l.candidatures / l.visites) * 100)} %` : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* La même information, sans graphique : pour qui ne lit pas les couleurs,
            ou veut un chiffre précis sans survoler trente colonnes. */}
        <details className="mt-5">
          <summary className="cursor-pointer text-xs font-medium text-ink-600">
            Voir les chiffres jour par jour
          </summary>
          <div className="mt-2 max-h-72 overflow-auto">
            <table className="w-full text-xs tabular-nums">
              <thead className="sticky top-0 bg-white">
                <tr className="border-b border-ink-200 text-left text-ink-500">
                  <th className="py-1.5 pr-3 font-medium">Jour</th>
                  <th className="py-1.5 pr-3 text-right font-medium">Visites</th>
                  <th className="py-1.5 pr-3 text-right font-medium">Candidatures</th>
                  <th className="py-1.5 pr-3 text-right font-medium">Refusés</th>
                  <th className="py-1.5 text-right font-medium">Interrompus</th>
                </tr>
              </thead>
              <tbody>
                {[...f.jours].reverse().map((j) => (
                  <tr key={j.jour} className="border-b border-ink-100 text-ink-700">
                    <td className="py-1.5 pr-3">
                      {new Intl.DateTimeFormat('fr', { day: '2-digit', month: 'short', timeZone: 'UTC' }).format(
                        new Date(`${j.jour}T00:00:00Z`),
                      )}
                    </td>
                    <td className="py-1.5 pr-3 text-right">{j.visites}</td>
                    <td className="py-1.5 pr-3 text-right">{j.candidatures}</td>
                    <td className="py-1.5 pr-3 text-right">{j.refus_taille}</td>
                    <td className="py-1.5 text-right">{j.echecs}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </section>
    </div>
  )
}

function Tuile({ libelle, valeur, alerte = false }: { libelle: string; valeur: number; alerte?: boolean }) {
  return (
    <div className="rounded-lg border border-ink-200 px-3 py-2.5">
      <dt className="flex items-center gap-1.5 text-xs text-ink-500">
        {alerte && (
          <span className="text-red-700">
            <Icone etat="a_regler" />
          </span>
        )}
        {libelle}
      </dt>
      <dd className="mt-1 text-2xl font-semibold text-ink-900">{valeur.toLocaleString('fr')}</dd>
    </div>
  )
}
