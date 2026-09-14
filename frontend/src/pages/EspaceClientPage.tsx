import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { espaceClientApi } from '@/lib/api'
import { LogoKapi, Marque } from '@/components/Marque'
import { Callout, EmptyState, Field, PageLoader, Spinner } from '@/components/ui'
import { formatDate } from '@/lib/format'

/**
 * L'espace du promoteur.
 *
 * Ce que le commanditaire voit de son recrutement : où il en est, et de quoi
 * écrire à son interlocuteur. **Aucun nom de candidat, aucune note, aucun
 * motif d'élimination** — la confidentialité des candidatures est due aux
 * candidats, pas au client. L'avancement est volontairement grossier : il
 * renseigne sans exposer, et reste juste même quand le dossier prend un chemin
 * imprévu.
 *
 * Le jeton est conservé ici, séparément du store d'authentification du
 * personnel. Mêler les deux ferait qu'une session cabinet ouverte dans le même
 * navigateur détournerait les requêtes de cet espace, et réciproquement.
 */

const CLE_JETON = 'tricv.espace-client.jeton'

function lireJeton(): string {
  try {
    return sessionStorage.getItem(CLE_JETON) ?? ''
  } catch {
    // Navigation privée, stockage bloqué : la session vit alors le temps de
    // l'onglet, ce qui reste utilisable.
    return ''
  }
}

function ecrireJeton(jeton: string): void {
  try {
    if (jeton) sessionStorage.setItem(CLE_JETON, jeton)
    else sessionStorage.removeItem(CLE_JETON)
  } catch {
    /* rien à faire : l'état en mémoire suffit pour cette session */
  }
}

function Enveloppe({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-ink-50">
      <div className="h-1 bg-gradient-to-r from-or-500 via-or-400 to-or-500" />
      <header className="border-b border-ink-200 bg-white">
        <div className="mx-auto flex h-16 max-w-3xl items-center px-4">
          <Marque sousTitre="Espace de suivi" />
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-4 py-10">{children}</main>
      <footer className="mx-auto max-w-3xl px-4 pb-10">
        <p className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-ink-200 pt-5 text-xs text-ink-400">
          <LogoKapi taille={18} />
          <span className="font-medium text-ink-500">Kapi Consult</span>
          <span aria-hidden="true">·</span>
          <span>Immeuble D&amp;D, Agoè BKS, Lomé, Togo</span>
          <span aria-hidden="true">·</span>
          <span>info@kapiconsult.tg</span>
        </p>
      </footer>
    </div>
  )
}

const ETAT_LIBELLE: Record<string, string> = {
  A_VENIR: 'À venir',
  EN_COURS: 'En cours',
  TERMINEE: 'Terminée',
}

const ETAT_STYLE: Record<string, string> = {
  A_VENIR: 'bg-ink-100 text-ink-600',
  EN_COURS: 'bg-brand-100 text-brand-800',
  TERMINEE: 'bg-emerald-100 text-emerald-800',
}

/** Activation d'un accès : le destinataire choisit son mot de passe. */
export function ActivationEspaceClient() {
  const { jeton = '' } = useParams()
  const navigate = useNavigate()

  const invitation = useQuery({
    queryKey: ['espace-client', 'activation', jeton],
    queryFn: () => espaceClientApi.verifierLien(jeton),
    retry: false,
  })

  const [motDePasse, setMotDePasse] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [erreur, setErreur] = useState<string | null>(null)

  const activer = useMutation({
    mutationFn: () => espaceClientApi.activer(jeton, motDePasse),
    onSuccess: (session) => {
      ecrireJeton(session.token)
      navigate('/espace-client')
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Activation impossible'),
  })

  if (invitation.isLoading) return <Enveloppe><PageLoader /></Enveloppe>
  if (invitation.isError)
    return (
      <Enveloppe>
        <Callout tone="danger" title="Lien inutilisable">
          {invitation.error instanceof Error
            ? invitation.error.message
            : "Ce lien d'activation n'est pas valide."}
        </Callout>
      </Enveloppe>
    )

  const i = invitation.data!

  return (
    <Enveloppe>
      <div className="card p-6">
        <h1 className="text-lg font-semibold text-ink-900">Activer votre accès</h1>
        <p className="mt-1 text-sm text-ink-600">
          Bonjour {i.nom}. Cet accès concerne le mandat « {i.mandat} »
          {i.client ? ` pour ${i.client}` : ''}. Choisissez votre mot de passe : il ne sera connu
          que de vous.
        </p>

        <form
          className="mt-5 space-y-4"
          onSubmit={(e) => {
            e.preventDefault()
            if (motDePasse.length < 8) {
              setErreur('Le mot de passe doit comporter au moins 8 caractères.')
              return
            }
            if (motDePasse !== confirmation) {
              setErreur('Les deux mots de passe ne correspondent pas.')
              return
            }
            setErreur(null)
            activer.mutate()
          }}
        >
          <Field label="Identifiant" htmlFor="ec-email">
            <input id="ec-email" className="input" value={i.email} readOnly />
          </Field>
          <Field label="Mot de passe" htmlFor="ec-mdp" hint="8 caractères au minimum.">
            <input
              id="ec-mdp"
              type="password"
              className="input"
              value={motDePasse}
              autoComplete="new-password"
              onChange={(e) => setMotDePasse(e.target.value)}
            />
          </Field>
          <Field label="Confirmation" htmlFor="ec-mdp2">
            <input
              id="ec-mdp2"
              type="password"
              className="input"
              value={confirmation}
              autoComplete="new-password"
              onChange={(e) => setConfirmation(e.target.value)}
            />
          </Field>

          {erreur && <Callout tone="danger">{erreur}</Callout>}

          <button type="submit" className="btn-primary w-full" disabled={activer.isPending}>
            {activer.isPending && <Spinner />}
            Activer mon accès
          </button>
          <p className="text-xs text-ink-500">
            Ce lien ne peut être utilisé qu&apos;une seule fois.
          </p>
        </form>
      </div>
    </Enveloppe>
  )
}

function Connexion({ onConnecte }: { onConnecte: (jeton: string) => void }) {
  const [email, setEmail] = useState('')
  const [motDePasse, setMotDePasse] = useState('')
  const [erreur, setErreur] = useState<string | null>(null)

  const connexion = useMutation({
    mutationFn: () => espaceClientApi.connexion(email.trim(), motDePasse),
    onSuccess: (session) => onConnecte(session.token),
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Connexion impossible'),
  })

  return (
    <Enveloppe>
      <div className="card mx-auto max-w-md p-6">
        <h1 className="text-lg font-semibold text-ink-900">Espace de suivi</h1>
        <p className="mt-1 text-sm text-ink-600">
          L&apos;accès vous a été transmis par votre interlocuteur chez Kapi Consult.
        </p>

        <form
          className="mt-5 space-y-4"
          onSubmit={(e) => {
            e.preventDefault()
            setErreur(null)
            connexion.mutate()
          }}
        >
          <Field label="Adresse email" htmlFor="ec-login-email">
            <input
              id="ec-login-email"
              type="email"
              className="input"
              value={email}
              autoComplete="email"
              onChange={(e) => setEmail(e.target.value)}
            />
          </Field>
          <Field label="Mot de passe" htmlFor="ec-login-mdp">
            <input
              id="ec-login-mdp"
              type="password"
              className="input"
              value={motDePasse}
              autoComplete="current-password"
              onChange={(e) => setMotDePasse(e.target.value)}
            />
          </Field>

          {erreur && <Callout tone="danger">{erreur}</Callout>}

          <button type="submit" className="btn-primary w-full" disabled={connexion.isPending}>
            {connexion.isPending && <Spinner />}
            Se connecter
          </button>
        </form>
      </div>
    </Enveloppe>
  )
}

export default function EspaceClientPage() {
  const queryClient = useQueryClient()
  const [jeton, setJeton] = useState(lireJeton)
  const [onglet, setOnglet] = useState<'suivi' | 'messages'>('suivi')

  // Rédaction d'un message. Une demande de modification est suivie jusqu'à son
  // traitement, là où un simple message se lit et se classe.
  const [objet, setObjet] = useState('')
  const [corps, setCorps] = useState('')
  const [demande, setDemande] = useState(false)
  const [erreurEnvoi, setErreurEnvoi] = useState<string | null>(null)

  const suivi = useQuery({
    queryKey: ['espace-client', 'suivi', jeton],
    queryFn: () => espaceClientApi.suivi(jeton),
    enabled: Boolean(jeton),
    retry: false,
  })

  const messages = useQuery({
    queryKey: ['espace-client', 'messages', jeton],
    queryFn: () => espaceClientApi.messages(jeton),
    enabled: Boolean(jeton) && onglet === 'messages',
  })

  const rapports = useQuery({
    queryKey: ['espace-client', 'rapports', jeton],
    queryFn: () => espaceClientApi.rapports(jeton),
    enabled: Boolean(jeton),
  })

  const envoyer = useMutation({
    mutationFn: () =>
      espaceClientApi.ecrire(jeton, {
        corps: corps.trim(),
        objet: objet.trim() || undefined,
        demande_modification: demande,
      }),
    onSuccess: () => {
      setObjet('')
      setCorps('')
      setDemande(false)
      setErreurEnvoi(null)
      void queryClient.invalidateQueries({ queryKey: ['espace-client', 'messages'] })
      void queryClient.invalidateQueries({ queryKey: ['espace-client', 'suivi'] })
    },
    onError: (e) => setErreurEnvoi(e instanceof Error ? e.message : 'Envoi impossible'),
  })

  // Une session finie — jeton expiré, accès révoqué, mandat clos — ramène à
  // l'écran de connexion plutôt que d'afficher une erreur en boucle.
  useEffect(() => {
    if (suivi.isError && jeton) {
      const fini = suivi.error instanceof Error && /401|expir/i.test(suivi.error.message)
      if (fini) {
        ecrireJeton('')
        setJeton('')
      }
    }
  }, [suivi.isError, suivi.error, jeton])

  if (!jeton)
    return (
      <Connexion
        onConnecte={(nouveau) => {
          ecrireJeton(nouveau)
          setJeton(nouveau)
        }}
      />
    )

  if (suivi.isLoading) return <Enveloppe><PageLoader /></Enveloppe>
  if (suivi.isError)
    return (
      <Enveloppe>
        <Callout tone="warning" title="Espace indisponible">
          {suivi.error instanceof Error ? suivi.error.message : 'Une erreur est survenue.'}
        </Callout>
        <button
          type="button"
          className="btn-ghost mt-4"
          onClick={() => {
            ecrireJeton('')
            setJeton('')
          }}
        >
          Revenir à la connexion
        </button>
      </Enveloppe>
    )

  const s = suivi.data!

  return (
    <Enveloppe>
      <div className="flex flex-wrap items-baseline gap-2">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink-900">{s.mandat}</h1>
          <p className="mt-1 text-sm text-ink-500">
            {s.client}
            {s.reference ? ` · ${s.reference}` : ''}
          </p>
        </div>
        <button
          type="button"
          className="btn-ghost ml-auto px-3 py-1.5 text-xs"
          onClick={() => {
            ecrireJeton('')
            setJeton('')
          }}
        >
          Se déconnecter
        </button>
      </div>

      <div className="mt-6 flex gap-2 border-b border-ink-200">
        {(['suivi', 'messages'] as const).map((cle) => (
          <button
            key={cle}
            type="button"
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${
              onglet === cle
                ? 'border-brand-700 font-medium text-brand-800'
                : 'border-transparent text-ink-500 hover:text-ink-800'
            }`}
            onClick={() => setOnglet(cle)}
          >
            {cle === 'suivi' ? 'Avancement' : 'Échanges'}
            {cle === 'messages' && s.messages_non_lus > 0 && (
              <span className="ml-1.5 rounded-full bg-brand-700 px-1.5 text-[11px] text-white">
                {s.messages_non_lus}
              </span>
            )}
          </button>
        ))}
      </div>

      {onglet === 'suivi' && (
        <div className="mt-6 space-y-6">
          {s.etapes.length > 0 && (
            <section className="card p-5">
              <h2 className="text-sm font-semibold text-ink-900">Chronogramme</h2>
              <ol className="mt-3 space-y-2">
                {s.etapes.map((etape, index) => (
                  <li key={index} className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="min-w-0 flex-1 text-ink-800">{etape.libelle}</span>
                    {etape.date_prevue && (
                      <span className="text-xs text-ink-500">
                        {formatDate(etape.date_prevue, 'fr')}
                      </span>
                    )}
                    <span
                      className={`badge ${ETAT_STYLE[etape.etat] ?? 'bg-ink-100 text-ink-600'}`}
                    >
                      {ETAT_LIBELLE[etape.etat] ?? etape.etat}
                    </span>
                  </li>
                ))}
              </ol>
            </section>
          )}

          <section className="card p-5">
            <h2 className="text-sm font-semibold text-ink-900">Postes</h2>
            {s.postes.length === 0 ? (
              <p className="mt-2 text-sm text-ink-500">Aucun poste n&apos;est encore ouvert.</p>
            ) : (
              <ul className="mt-3 space-y-3">
                {s.postes.map((poste, index) => (
                  <li key={index} className="rounded-lg bg-ink-50 px-3 py-2">
                    <div className="flex flex-wrap items-baseline gap-2">
                      <span className="font-medium text-ink-900">{poste.intitule}</span>
                      <span className="text-xs text-ink-500">
                        {poste.nombre_a_pourvoir} poste
                        {poste.nombre_a_pourvoir > 1 ? 's' : ''} à pourvoir
                      </span>
                      <span className="badge ml-auto bg-brand-100 text-brand-800">
                        {poste.avancement}
                      </span>
                    </div>
                    {(poste.avis_publie_le || poste.date_cloture) && (
                      <p className="mt-1 text-xs text-ink-500">
                        {poste.avis_publie_le
                          ? `Avis publié le ${formatDate(poste.avis_publie_le, 'fr')}`
                          : ''}
                        {poste.date_cloture
                          ? `${poste.avis_publie_le ? ' · ' : ''}clôture le ${formatDate(
                              poste.date_cloture,
                              'fr',
                            )}`
                          : ''}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>

          {(rapports.data?.length ?? 0) > 0 && (
            <section className="card p-5">
              <h2 className="text-sm font-semibold text-ink-900">Rapports remis</h2>
              <ul className="mt-3 space-y-2">
                {rapports.data!.map((rapport) => (
                  <li key={rapport.id} className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="min-w-0 flex-1 text-ink-800">{rapport.titre}</span>
                    {rapport.partage_le && (
                      <span className="text-xs text-ink-500">
                        {formatDate(rapport.partage_le, 'fr')}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
              <p className="mt-3 text-xs text-ink-500">
                Demandez la transmission du document à votre interlocuteur depuis l&apos;onglet
                Échanges.
              </p>
            </section>
          )}
        </div>
      )}

      {onglet === 'messages' && (
        <div className="mt-6 space-y-6">
          <section className="card p-5">
            <h2 className="text-sm font-semibold text-ink-900">Écrire à Kapi Consult</h2>
            <form
              className="mt-3 space-y-3"
              onSubmit={(e) => {
                e.preventDefault()
                if (!corps.trim()) return
                envoyer.mutate()
              }}
            >
              <input
                className="input"
                value={objet}
                placeholder="Objet (facultatif)"
                aria-label="Objet"
                onChange={(e) => setObjet(e.target.value)}
              />
              <textarea
                className="input"
                rows={4}
                value={corps}
                placeholder="Votre message…"
                aria-label="Message"
                onChange={(e) => setCorps(e.target.value)}
              />
              <label className="flex items-start gap-2 text-sm text-ink-700">
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={demande}
                  onChange={(e) => setDemande(e.target.checked)}
                />
                <span>
                  C&apos;est une demande de modification
                  <span className="block text-xs text-ink-500">
                    Elle sera suivie jusqu&apos;à son traitement, et non simplement lue.
                  </span>
                </span>
              </label>

              {erreurEnvoi && <Callout tone="danger">{erreurEnvoi}</Callout>}

              <button
                type="submit"
                className="btn-primary"
                disabled={envoyer.isPending || !corps.trim()}
              >
                {envoyer.isPending && <Spinner />}
                Envoyer
              </button>
            </form>
          </section>

          {messages.isLoading && <PageLoader />}
          {messages.data?.length === 0 && (
            <EmptyState title="Aucun échange" hint="Vos messages apparaîtront ici." />
          )}
          <div className="space-y-3">
            {messages.data?.map((message) => (
              <article
                key={message.id}
                className={`card p-4 ${
                  message.auteur === 'CABINET' ? 'border-l-4 border-l-brand-700' : ''
                }`}
              >
                <div className="flex flex-wrap items-baseline gap-2 text-xs text-ink-500">
                  <span className="font-medium text-ink-800">{message.auteur_nom}</span>
                  <span>{formatDate(message.envoye_le, 'fr')}</span>
                  {message.type_echange === 'DEMANDE_MODIFICATION' && (
                    <span
                      className={`badge ${
                        message.traite_le
                          ? 'bg-emerald-100 text-emerald-800'
                          : 'bg-amber-100 text-amber-800'
                      }`}
                    >
                      {message.traite_le ? 'Traitée' : 'Demande en cours'}
                    </span>
                  )}
                </div>
                {message.objet && (
                  <p className="mt-1 text-sm font-medium text-ink-900">{message.objet}</p>
                )}
                <p className="mt-1 whitespace-pre-line text-sm text-ink-700">{message.corps}</p>
              </article>
            ))}
          </div>
        </div>
      )}
    </Enveloppe>
  )
}
