import { useState } from 'react'

/**
 * Le mode d'emploi de l'application.
 *
 * Sans lui, la chaîne mandat → fiche de poste → avis n'est devinable que si on
 * connaît déjà le modèle : les boutons existent, mais rien ne dit où cliquer
 * ni dans quel ordre. Le panneau s'ouvre de lui-même quand il n'y a encore
 * aucun mandat, c'est-à-dire exactement quand on en a besoin.
 */

function Etape({
  numero,
  titre,
  children,
  ou,
}: {
  numero: number
  titre: string
  children: React.ReactNode
  ou?: string
}) {
  return (
    <li className="flex gap-3">
      <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-ink-900 text-xs font-semibold text-white">
        {numero}
      </span>
      <div className="min-w-0">
        <p className="text-sm font-medium text-ink-900">{titre}</p>
        <p className="mt-0.5 text-sm text-ink-600">{children}</p>
        {ou && <p className="mt-1 text-xs font-medium text-ink-500">Où : {ou}</p>}
      </div>
    </li>
  )
}

export default function GuidePipeline({ ouvertParDefaut = false }: { ouvertParDefaut?: boolean }) {
  const [ouvert, setOuvert] = useState(ouvertParDefaut)

  return (
    <section className="card mb-6 overflow-hidden">
      <button
        type="button"
        className="flex w-full items-center gap-3 px-5 py-4 text-left hover:bg-ink-50"
        onClick={() => setOuvert((o) => !o)}
        aria-expanded={ouvert}
      >
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-ink-900">Comment ça marche</p>
          <p className="mt-0.5 text-xs text-ink-500">
            De la manifestation d'intérêt à la grille de présélection.
          </p>
        </div>
        <span className="shrink-0 text-xs font-medium text-ink-500">
          {ouvert ? 'Masquer' : 'Afficher'}
        </span>
      </button>

      {ouvert && (
        <div className="space-y-6 border-t border-ink-200 px-5 py-5">
          <div>
            <h3 className="text-sm font-semibold text-ink-900">
              Phase amont — décrocher le mandat
              <span className="ml-2 rounded bg-ink-100 px-1.5 py-0.5 text-xs font-normal text-ink-600">
                facultative
              </span>
            </h3>
            <p className="mt-1 text-sm text-ink-600">
              Cette phase ne concerne <strong>pas les candidats</strong> : elle met en concurrence
              des <strong>cabinets</strong>. Elle n'existe que lorsque le client passe par un
              marché. Un mandat attribué de gré à gré la saute entièrement.
            </p>
            <ul className="mt-3 space-y-3">
              <Etape
                numero={1}
                titre="AMI — Appel à Manifestation d'Intérêt"
                ou="Statut du mandat : « Manifestation d'intérêt soumise »"
              >
                Le client publie un avis annonçant son besoin ; les cabinets intéressés déposent
                leurs références. C'est un filtre destiné à retenir une liste restreinte de
                cabinets. Aucun poste n'est encore ouvert, aucun candidat n'est concerné.
              </Etape>
              <Etape
                numero={2}
                titre="Appel d'offre"
                ou="Statut du mandat : « Offre soumise »"
              >
                Le vrai marché, lancé auprès des cabinets présélectionnés. Le cabinet remet une
                proposition technique et financière.
              </Etape>
              <Etape
                numero={3}
                titre="Attribution"
                ou="Statut du mandat : « Gagné » ou « Perdu »"
              >
                Le marché est attribué. Il peut aussi l'être{' '}
                <strong>de gré à gré</strong> — directement, sans mise en concurrence : dans ce
                cas on crée le mandat déjà gagné et on passe à la suite.
              </Etape>
            </ul>
          </div>

          <div className="border-t border-ink-100 pt-5">
            <h3 className="text-sm font-semibold text-ink-900">
              Phase aval — exécuter le recrutement
            </h3>
            <p className="mt-1 text-sm text-ink-600">
              C'est ici que les candidats entrent en scène, et c'est le cœur de l'application.
            </p>
            <ul className="mt-3 space-y-3">
              <Etape numero={1} titre="Créer le mandat" ou="Bouton « Nouveau mandat », ci-dessus">
                Un mandat = un client + un engagement. Il regroupe tous les postes à pourvoir
                pour ce client.
              </Etape>
              <Etape
                numero={2}
                titre="Rédiger la fiche de poste"
                ou="Ouvrir le mandat, puis « Nouveau poste »"
              >
                Document <strong>interne</strong> : niveau de diplôme, domaines acceptés, années
                d'expérience, pièces exigées. C'est lui qui rend la présélection calculable — tout
                ce qui y figure devient une règle.
              </Etape>
              <Etape
                numero={3}
                titre="Publier l'avis de recrutement"
                ou="Ouvrir le poste, panneau « Avis de recrutement »"
              >
                Document <strong>public</strong>, tiré de la fiche de poste. À ne pas confondre
                avec elle : l'avis reprend le profil recherché et y ajoute ce que la fiche ne
                contient pas — composition du dossier, date de clôture, déroulement de la
                sélection. Un même poste peut avoir plusieurs avis (national, international, ou
                republication).
              </Etape>
              <Etape
                numero={4}
                titre="Recevoir les candidatures"
                ou="Lien public de l'avis, « Relever la boîte », ou saisie manuelle"
              >
                Trois voies : le formulaire public, la boîte email (l'objet doit contenir la
                référence de l'avis entre crochets), ou une saisie directe.
              </Etape>
              <Etape
                numero={5}
                titre="Dépouiller et vérifier"
                ou="Onglet « À vérifier » du poste"
              >
                Les dossiers arrivés en pièces jointes attendent d'être lus. Tant qu'un relecteur
                n'a pas confirmé leurs données, ils ne peuvent <strong>ni</strong> être éliminés,{' '}
                <strong>ni</strong> rejoindre la présélection.
              </Etape>
              <Etape
                numero={6}
                titre="Éditer la grille"
                ou="Bouton « Exporter la grille (Excel) »"
              >
                Notation sur 30, seuil à 20 par défaut, tableau d'élimination subdivisé par motif.
                Le fichier remis au client rappelle le seuil, la date de clôture et toute
                justification de dérogation.
              </Etape>
            </ul>
          </div>

          <p className="border-t border-ink-100 pt-4 text-xs text-ink-500">
            L'outil classe et recommande. Les décisions restent aux RH : chaque note est
            détaillée ligne à ligne, chaque élimination porte la comparaison qui l'a produite, et
            tout motif peut être levé avec une justification écrite.
          </p>
        </div>
      )}
    </section>
  )
}
