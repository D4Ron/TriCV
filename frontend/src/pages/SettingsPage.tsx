import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { recrutementApi, settingsApi } from '@/lib/api'
import { useAuthStore } from '@/store/auth'
import { Callout, ErrorState, Field, PageLoader, Spinner, Toggle } from '@/components/ui'
import PanneauUtilisateurs from '@/components/PanneauUtilisateurs'
import AssistantMicrosoft365 from '@/components/AssistantMicrosoft365'

/**
 * Paramètres du cabinet.
 *
 * Uniquement ce qui se règle : expurgation des données sensibles, inscription
 * libre, candidatures spontanées, boîtes de courriel. La configuration du
 * déploiement — fournisseur de modèle, stockage, modèles de reconnaissance —
 * n'est pas affichée : elle se change dans le fichier de configuration du
 * serveur, et l'exposer en lecture seule n'aidait personne à agir.
 *
 * Le seuil de présélection n'y figure plus. Il variait trop d'un mandat à
 * l'autre pour qu'une valeur d'établissement ait un sens, et le fixer avant
 * d'avoir vu la distribution des notes revenait à décider à l'aveugle. Il se
 * trace maintenant sur la grille du poste, une fois les dossiers notés.
 *
 * Les boîtes font exception à la règle « pas de secret dans un écran » : leurs
 * mots de passe se règlent ici parce que l'adresse de recrutement change avec
 * les campagnes et qu'un mot de passe d'application se révoque. Ils partent
 * vers le serveur et n'en reviennent jamais — le champ affiche « déjà défini »,
 * pas la valeur.
 */
/** Un choix exclusif présenté en toutes lettres, pas en liste déroulante. */
function Choix({
  actif,
  titre,
  detail,
  disabled,
  onClick,
}: {
  actif: boolean
  titre: string
  detail: string
  disabled?: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      aria-pressed={actif}
      className={`w-full rounded-lg border px-4 py-3 text-left transition disabled:opacity-60 ${
        actif ? 'border-brand-400 bg-brand-50' : 'border-ink-200 bg-white hover:border-ink-300'
      }`}
    >
      <span className="block text-sm font-semibold text-ink-900">{titre}</span>
      <span className="mt-0.5 block text-xs leading-relaxed text-ink-500">{detail}</span>
    </button>
  )
}

const ONGLETS: Array<['general' | 'courriel' | 'comptes', string]> = [
  ['general', 'Général'],
  ['courriel', 'Courriel'],
  ['comptes', 'Utilisateurs'],
]

export default function SettingsPage() {
  const queryClient = useQueryClient()
  const user = useAuthStore((state) => state.user)
  const estAdmin = user?.role === 'ADMIN'

  const reglages = useQuery({ queryKey: ['settings'], queryFn: settingsApi.get })

  const [demographiques, setDemographiques] = useState(true)
  const [inscription, setInscription] = useState(false)
  const [spontanees, setSpontanees] = useState(true)
  const [message, setMessage] = useState<string | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)

  // Boîte de candidatures (réception).
  const [courriel, setCourriel] = useState(false)
  const [hote, setHote] = useState('')
  const [port, setPort] = useState('993')
  const [adresse, setAdresse] = useState('')
  const [motDePasse, setMotDePasse] = useState('')
  const [dossier, setDossier] = useState('INBOX')
  const [testResultat, setTestResultat] = useState<string | null>(null)
  const [testErreur, setTestErreur] = useState<string | null>(null)

  // Envoi. Serveur distinct : on relève sur la boîte de candidatures et on peut
  // vouloir écrire depuis l'adresse générale du cabinet.
  const [envoi, setEnvoi] = useState(false)
  const [smtpHote, setSmtpHote] = useState('')
  const [smtpPort, setSmtpPort] = useState('587')
  const [smtpUser, setSmtpUser] = useState('')
  const [smtpMotDePasse, setSmtpMotDePasse] = useState('')
  const [smtpTls, setSmtpTls] = useState(true)
  const [expediteur, setExpediteur] = useState('')
  const [urlPublique, setUrlPublique] = useState('')
  const [envoiResultat, setEnvoiResultat] = useState<string | null>(null)
  const [envoiErreur, setEnvoiErreur] = useState<string | null>(null)

  // Par où passe le courriel. Microsoft a fermé l'authentification par mot de
  // passe sur beaucoup de locataires : là où elle l'est, IMAP échoue quel que
  // soit le mot de passe, et l'écran ne disait pas pourquoi.
  const [fournisseur, setFournisseur] = useState<'imap' | 'microsoft365'>('imap')
  const [tenant, setTenant] = useState('')
  const [clientId, setClientId] = useState('')
  const [clientSecret, setClientSecret] = useState('')

  const [contactCandidats, setContactCandidats] = useState('')

  const [onglet, setOnglet] = useState<'general' | 'courriel' | 'comptes'>('general')
  // L'assistant s'ouvre au moment où l'on bascule sur Microsoft : c'est là
  // qu'on a besoin de la marche à suivre, pas dans un guide à retrouver.
  const [assistant, setAssistant] = useState(false)

  // Le formulaire part de l'état du serveur, pas d'une valeur inventée.
  useEffect(() => {
    if (!reglages.data) return
    setDemographiques(reglages.data.redact_demographics)
    setInscription(reglages.data.allow_self_registration)
    setSpontanees(reglages.data.candidatures_spontanees)
    setCourriel(reglages.data.courriel_actif)
    setHote(reglages.data.imap_host)
    setPort(String(reglages.data.imap_port))
    setAdresse(reglages.data.imap_user)
    setDossier(reglages.data.imap_folder)
    setEnvoi(reglages.data.smtp_actif)
    setSmtpHote(reglages.data.smtp_host)
    setSmtpPort(String(reglages.data.smtp_port))
    setSmtpUser(reglages.data.smtp_user)
    setSmtpTls(reglages.data.smtp_tls)
    setExpediteur(reglages.data.smtp_expediteur)
    setUrlPublique(reglages.data.url_publique)
    setFournisseur(reglages.data.fournisseur_courriel)
    setTenant(reglages.data.oauth_tenant)
    setClientId(reglages.data.oauth_client_id)
    setContactCandidats(reglages.data.contact_candidats)
    // Jamais réhydratés : le serveur ne renvoie aucun secret.
    setMotDePasse('')
    setSmtpMotDePasse('')
    setClientSecret('')
  }, [reglages.data])

  const enregistrer = useMutation({
    mutationFn: () =>
      settingsApi.modifier({
        redact_demographics: demographiques,
        allow_self_registration: inscription,
        candidatures_spontanees: spontanees,
        courriel_actif: courriel,
        imap_host: hote.trim(),
        imap_port: Number(port) || 993,
        imap_user: adresse.trim(),
        // Vide = inchangé, côté serveur comme ici.
        imap_password: motDePasse,
        imap_folder: dossier.trim() || 'INBOX',
        smtp_actif: envoi,
        smtp_host: smtpHote.trim(),
        smtp_port: Number(smtpPort) || 587,
        smtp_user: smtpUser.trim(),
        smtp_password: smtpMotDePasse,
        smtp_tls: smtpTls,
        smtp_expediteur: expediteur.trim(),
        url_publique: urlPublique.trim(),
        fournisseur_courriel: fournisseur,
        oauth_tenant: tenant.trim(),
        oauth_client_id: clientId.trim(),
        // Vide = inchangé, comme les mots de passe.
        oauth_client_secret: clientSecret,
        contact_candidats: contactCandidats.trim(),
      }),
    onSuccess: () => {
      setErreur(null)
      setMessage('Réglages enregistrés.')
      setMotDePasse('')
      setSmtpMotDePasse('')
      setClientSecret('')
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
      void queryClient.invalidateQueries({ queryKey: ['aide-publique'] })
      void queryClient.invalidateQueries({ queryKey: ['courriel', 'etat'] })
    },
    onError: (e) => {
      setMessage(null)
      setErreur(e instanceof Error ? e.message : 'Enregistrement impossible')
    },
  })

  // Tester porte sur ce qui est *enregistré*, pas sur ce qui est à l'écran :
  // c'est la connexion réelle que les RH veulent voir aboutir.
  const testerEnvoi = useMutation({
    mutationFn: settingsApi.testerEnvoi,
    onSuccess: (r) => {
      setEnvoiErreur(null)
      setEnvoiResultat(`Session ouverte. Les messages partiront de ${r.expediteur}.`)
    },
    onError: (e) => {
      setEnvoiResultat(null)
      setEnvoiErreur(e instanceof Error ? e.message : 'Connexion impossible')
    },
  })

  const tester = useMutation({
    mutationFn: recrutementApi.testerCourriel,
    onSuccess: (r) => {
      setTestErreur(null)
      setTestResultat(
        `Connexion établie à ${r.boite} (${r.dossier}) — ${r.messages} message(s), dont ${r.non_lus} non lu(s).`,
      )
    },
    onError: (e) => {
      setTestResultat(null)
      setTestErreur(e instanceof Error ? e.message : 'Connexion impossible')
    },
  })

  if (reglages.isLoading) return <PageLoader />
  if (reglages.isError)
    return <ErrorState error={reglages.error} onRetry={() => reglages.refetch()} />

  const s = reglages.data!
  // Chez Microsoft, rien ne passe par un serveur IMAP ni SMTP : ni hôte, ni
  // port, ni mot de passe. Les laisser à l'écran ferait croire qu'ils comptent,
  // et on les remplirait avant de chercher pourquoi le relevé échoue encore.
  const graph = fournisseur === 'microsoft365'

  return (
    <div className="max-w-2xl">
      <h1 className="text-xl font-semibold tracking-tight text-ink-900">Paramètres</h1>
      <p className="mt-1 text-sm text-ink-500">
        Ce qui relève de la pratique du cabinet et change avec l'usage. Le seuil de présélection
        n'est plus ici : il se trace sur la grille du poste, une fois les notes connues.
      </p>

      {!s.redact_demographics && (
        <div className="mt-5">
          <Callout tone="warning" title="Données démographiques transmises au modèle">
            L'âge, le sexe et la nationalité ne sont plus retirés des documents avant analyse.
            C'est une décision, pas un oubli — remettez-la en place si ce n'est pas voulu.
          </Callout>
        </div>
      )}

      {/* Trois onglets plutôt qu'une colonne de mille pixels : la pratique du
          cabinet se règle une fois, le courriel se débogue à plusieurs
          reprises, et les comptes s'ouvrent quand quelqu'un arrive. Rien ne
          gagnait à les empiler. */}
      <div className="mt-5 flex gap-1 border-b border-ink-200">
        {ONGLETS.filter(([cle]) => cle !== 'comptes' || estAdmin).map(([cle, libelle]) => (
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
            {libelle}
          </button>
        ))}
      </div>

      {assistant && (
        <AssistantMicrosoft365
          tenant={tenant}
          clientId={clientId}
          secretDefini={s.oauth_client_secret_defini}
          urlPublique={urlPublique}
          onTenant={setTenant}
          onClientId={setClientId}
          onSecret={setClientSecret}
          onClose={() => setAssistant(false)}
        />
      )}

      {onglet === 'comptes' && (
        <div className="mt-5">
          <PanneauUtilisateurs />
        </div>
      )}

      <section className={`card mt-5 p-5 ${onglet === 'comptes' ? 'hidden' : ''}`}>
        <div className={onglet === 'general' ? '' : 'hidden'}>
        <h2 className="text-sm font-semibold text-ink-900">Pratique de recrutement</h2>
        <p className="mt-1 text-xs text-ink-500">
          {estAdmin
            ? 'Modifiable ici, sans redémarrage.'
            : "Réservé aux administrateurs. Vous pouvez consulter ces réglages sans les modifier."}
        </p>

        <div className="mt-4 space-y-4">
          <Toggle
            checked={demographiques}
            onChange={setDemographiques}
            disabled={!estAdmin}
            label="Expurger les données démographiques"
            hint="Retire l'âge, le sexe et la nationalité des documents avant toute analyse externe. Ces données restent visibles des RH et servent aux conditions restrictives."
          />

          <Toggle
            checked={inscription}
            onChange={setInscription}
            disabled={!estAdmin}
            label="Autoriser la création de compte"
            hint="Un compte RH donne accès aux dossiers de tous les candidats. À n'ouvrir que le temps nécessaire."
          />

          <Toggle
            checked={spontanees}
            onChange={setSpontanees}
            disabled={!estAdmin}
            label="Accueillir les candidatures spontanées"
            hint="Un dossier reçu hors de tout avis — par la boîte de candidatures ou par le formulaire du site — rejoint le vivier sans être noté. Décoché, ces messages restent simplement signalés « non rattachés »."
          />
        </div>

        </div>

        <div className={onglet === 'courriel' ? '' : 'hidden'}>
        <div>
          <h2 className="text-sm font-semibold text-ink-900">Par où passe le courriel</h2>
          <p className="mt-1 text-xs text-ink-500">
            Microsoft a fermé l&apos;authentification par mot de passe sur beaucoup de
            locataires professionnels. Là où elle l&apos;est, IMAP échoue quel que soit le mot de
            passe saisi — y compris un mot de passe d&apos;application, que Microsoft n&apos;offre
            pas non plus. Ce n&apos;est pas une erreur de saisie : c&apos;est le mauvais chemin.
          </p>

          <div className="mt-4 space-y-2">
            <Choix
              actif={fournisseur === 'imap'}
              disabled={!estAdmin}
              titre="IMAP et SMTP"
              detail="Gmail avec un mot de passe d'application, une boîte OVH, Zoho, ou tout serveur classique."
              onClick={() => setFournisseur('imap')}
            />
            <Choix
              actif={fournisseur === 'microsoft365'}
              disabled={!estAdmin}
              titre="Microsoft 365 (Graph)"
              detail="Une boîte Exchange Online. Demande une inscription d'application dans Entra ID, et le consentement d'un administrateur du locataire."
              onClick={() => {
                setFournisseur('microsoft365')
                // Première bascule : on ouvre la marche à suivre. Revenir sur
                // un réglage déjà posé ne rouvre rien — le bouton « Reprendre
                // la marche à suivre » est là pour ça.
                if (fournisseur !== 'microsoft365') setAssistant(true)
              }}
            />
          </div>
        </div>

        {fournisseur === 'microsoft365' && (
          <div className="mt-6 border-t border-ink-100 pt-5">
            <h2 className="text-sm font-semibold text-ink-900">Accès Microsoft 365</h2>
            <p className="mt-1 text-xs text-ink-500">
              Ces trois valeurs viennent d&apos;une inscription d&apos;application dans Entra ID.
              L&apos;application relève et envoie <em>sans utilisateur connecté</em> : les
              permissions sont donc des permissions d&apos;application, pas déléguées, et elles
              demandent le consentement d&apos;un administrateur du locataire.
            </p>

            <button
              type="button"
              className="btn-secondary mt-3"
              onClick={() => setAssistant(true)}
            >
              Reprendre la marche à suivre
            </button>

            <div className="mt-4 space-y-4">
              <Field
                label="ID du locataire (tenant)"
                htmlFor="oauth-tenant"
                hint="L'« ID de l'annuaire (locataire) » de la page Vue d'ensemble. Un domaine — kapiconsult.onmicrosoft.com — est accepté aussi."
              >
                <input
                  id="oauth-tenant"
                  className="input"
                  value={tenant}
                  disabled={!estAdmin}
                  placeholder="00000000-0000-0000-0000-000000000000"
                  onChange={(e) => setTenant(e.target.value)}
                />
              </Field>

              <Field label="ID de l'application (client)" htmlFor="oauth-client">
                <input
                  id="oauth-client"
                  className="input"
                  value={clientId}
                  disabled={!estAdmin}
                  placeholder="00000000-0000-0000-0000-000000000000"
                  onChange={(e) => setClientId(e.target.value)}
                />
              </Field>

              <Field
                label="Secret client"
                htmlFor="oauth-secret"
                hint={
                  s.oauth_client_secret_defini
                    ? 'Déjà défini. Laissez vide pour le conserver. Un secret Entra expire — notez sa date d’échéance quelque part.'
                    : 'La « valeur » du secret, pas son identifiant. Elle n’est affichée qu’une fois par Entra ID.'
                }
              >
                <input
                  id="oauth-secret"
                  type="password"
                  className="input"
                  value={clientSecret}
                  disabled={!estAdmin}
                  autoComplete="new-password"
                  placeholder={s.oauth_client_secret_defini ? '•••••••• (inchangé)' : ''}
                  onChange={(e) => setClientSecret(e.target.value)}
                />
              </Field>
            </div>
          </div>
        )}

        <div className="mt-6 border-t border-ink-100 pt-5">
          <h2 className="text-sm font-semibold text-ink-900">Boîte de candidatures</h2>
          <p className="mt-1 text-xs text-ink-500">
            L'adresse à laquelle les avis demandent d'envoyer les dossiers. Le relevé va y
            chercher les messages non lus, en crée les candidatures et marque les messages
            traités.
          </p>

          <div className="mt-4 space-y-4">
            <Toggle
              checked={courriel}
              onChange={setCourriel}
              disabled={!estAdmin}
              label="Relever la boîte depuis l'application"
              hint="Décoché, les boutons de relevé disparaissent et les dossiers se déposent à la main depuis le poste."
            />

            <Field
              label="Adresse de la boîte"
              htmlFor="imap-user"
              hint="L'adresse dédiée au recrutement, celle qui figure dans les avis."
            >
              <input
                id="imap-user"
                type="email"
                className="input"
                value={adresse}
                disabled={!estAdmin}
                placeholder="recrutement@kapiconsult.tg"
                onChange={(e) => setAdresse(e.target.value)}
              />
            </Field>

            {!graph && (
              <>
            <Field
              label="Mot de passe"
              htmlFor="imap-password"
              hint={
                s.imap_password_defini
                  ? 'Déjà défini. Laissez vide pour le conserver ; saisissez-en un nouveau pour le remplacer.'
                  : "Chez Gmail, ce n'est pas le mot de passe du compte mais un « mot de passe d'application » à créer dans le compte Google."
              }
            >
              <input
                id="imap-password"
                type="password"
                className="input"
                value={motDePasse}
                disabled={!estAdmin}
                autoComplete="new-password"
                placeholder={s.imap_password_defini ? '•••••••• (inchangé)' : ''}
                onChange={(e) => setMotDePasse(e.target.value)}
              />
            </Field>

            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-2">
                <Field label="Serveur IMAP" htmlFor="imap-host">
                  <input
                    id="imap-host"
                    className="input"
                    value={hote}
                    disabled={!estAdmin}
                    placeholder="imap.gmail.com"
                    onChange={(e) => setHote(e.target.value)}
                  />
                </Field>
              </div>
              <Field label="Port" htmlFor="imap-port">
                <input
                  id="imap-port"
                  type="number"
                  className="input"
                  value={port}
                  disabled={!estAdmin}
                  onChange={(e) => setPort(e.target.value)}
                />
              </Field>
            </div>

              </>
            )}

            <Field
              label="Dossier à relever"
              htmlFor="imap-folder"
              hint="INBOX pour la boîte principale. Un libellé Gmail s'écrit tel quel."
            >
              <input
                id="imap-folder"
                className="input"
                value={dossier}
                disabled={!estAdmin}
                onChange={(e) => setDossier(e.target.value)}
              />
            </Field>

            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                className="btn-ghost px-3 py-1.5 text-xs"
                disabled={tester.isPending || !s.courriel_utilisable}
                onClick={() => tester.mutate()}
              >
                {tester.isPending && <Spinner />}
                Tester la connexion
              </button>
              <span className="text-xs text-ink-500">
                Porte sur les réglages enregistrés — pensez à enregistrer d'abord.
              </span>
            </div>

            {testResultat && (
              <Callout tone="success">{testResultat}</Callout>
            )}
            {testErreur && <Callout tone="danger">{testErreur}</Callout>}
          </div>
        </div>

        <div className="mt-6 border-t border-ink-100 pt-5">
          <h2 className="text-sm font-semibold text-ink-900">Envoi de courriels</h2>
          <p className="mt-1 text-xs text-ink-500">
            Pour écrire aux candidats — convocation, pièce manquante, réponse — et transmettre au
            promoteur son accès à l'espace de suivi. Sans cette configuration, ces boutons
            refusent l'envoi plutôt que de le perdre en silence.
          </p>

          <div className="mt-4 space-y-4">
            <Toggle
              checked={envoi}
              onChange={setEnvoi}
              disabled={!estAdmin}
              label="Envoyer les courriels depuis l'application"
              hint="Décoché, les messages se rédigent toujours mais se copient à la main dans votre messagerie."
            />

            <Field
              label="Adresse d'expédition"
              htmlFor="smtp-expediteur"
              hint="Ce que les candidats verront en « De : ». À défaut, le compte d'envoi est utilisé."
            >
              <input
                id="smtp-expediteur"
                type="email"
                className="input"
                value={expediteur}
                disabled={!estAdmin}
                placeholder="recrutement@kapiconsult.tg"
                onChange={(e) => setExpediteur(e.target.value)}
              />
            </Field>

            {!graph && (
              <>
            <Field label="Compte d'envoi" htmlFor="smtp-user">
              <input
                id="smtp-user"
                type="email"
                className="input"
                value={smtpUser}
                disabled={!estAdmin}
                onChange={(e) => setSmtpUser(e.target.value)}
              />
            </Field>

            <Field
              label="Mot de passe"
              htmlFor="smtp-password"
              hint={
                s.smtp_password_defini
                  ? 'Déjà défini. Laissez vide pour le conserver.'
                  : "Chez Gmail, un « mot de passe d'application », pas celui du compte."
              }
            >
              <input
                id="smtp-password"
                type="password"
                className="input"
                value={smtpMotDePasse}
                disabled={!estAdmin}
                autoComplete="new-password"
                placeholder={s.smtp_password_defini ? '•••••••• (inchangé)' : ''}
                onChange={(e) => setSmtpMotDePasse(e.target.value)}
              />
            </Field>

            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-2">
                <Field label="Serveur SMTP" htmlFor="smtp-host">
                  <input
                    id="smtp-host"
                    className="input"
                    value={smtpHote}
                    disabled={!estAdmin}
                    placeholder="smtp.gmail.com"
                    onChange={(e) => setSmtpHote(e.target.value)}
                  />
                </Field>
              </div>
              <Field label="Port" htmlFor="smtp-port">
                <input
                  id="smtp-port"
                  type="number"
                  className="input"
                  value={smtpPort}
                  disabled={!estAdmin}
                  onChange={(e) => setSmtpPort(e.target.value)}
                />
              </Field>
            </div>

            <Toggle
              checked={smtpTls}
              onChange={setSmtpTls}
              disabled={!estAdmin}
              label="Chiffrer la connexion (STARTTLS)"
              hint="À laisser coché. Le port 465 chiffre dès l'ouverture et ignore ce réglage."
            />

              </>
            )}

            <Field
              label="Adresse publique de l'application"
              htmlFor="url-publique"
              hint="Celle par laquelle candidats et clients atteignent l'application. Elle sert à construire les liens envoyés par courriel : sans elle, ils ne peuvent pas être écrits."
            >
              <input
                id="url-publique"
                className="input"
                value={urlPublique}
                disabled={!estAdmin}
                placeholder="https://recrutement.kapiconsult.tg"
                onChange={(e) => setUrlPublique(e.target.value)}
              />
            </Field>

            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                className="btn-ghost px-3 py-1.5 text-xs"
                disabled={testerEnvoi.isPending || !s.envoi_utilisable}
                onClick={() => testerEnvoi.mutate()}
              >
                {testerEnvoi.isPending && <Spinner />}
                Tester l&apos;envoi
              </button>
              <span className="text-xs text-ink-500">
                Ouvre une session sans rien expédier. Enregistrez d&apos;abord.
              </span>
            </div>

            {envoiResultat && <Callout tone="success">{envoiResultat}</Callout>}
            {envoiErreur && <Callout tone="danger">{envoiErreur}</Callout>}
          </div>
        </div>

        <div className="mt-6 border-t border-ink-100 pt-5">
          <h2 className="text-sm font-semibold text-ink-900">
            Adresse de contact des candidats
          </h2>
          <p className="mt-1 text-xs text-ink-500">
            Celle qui paraît sur les pages publiques et sur la page d&apos;aide, pour un
            candidat que le dépôt bloque. Mettez-y une boîte que quelqu&apos;un relève : une
            adresse affichée et jamais lue vaut moins qu&apos;aucune adresse.
          </p>

          <div className="mt-4">
            <Field
              label="Adresse affichée aux candidats"
              htmlFor="contact-candidats"
              hint={`Laissée vide, c'est l'adresse d'expédition qui sert, puis la boîte de candidatures. Actuellement servie : ${
                s.contact_effectif ||
                'aucune — les pages publiques n’affichent alors pas de contact'
              }.`}
            >
              <input
                id="contact-candidats"
                type="email"
                className="input"
                value={contactCandidats}
                disabled={!estAdmin}
                placeholder="recrutement@kapiconsult.tg"
                onChange={(e) => setContactCandidats(e.target.value)}
              />
            </Field>
          </div>
        </div>
        </div>

        {message && <p className="mt-4 text-sm font-medium text-emerald-700">{message}</p>}
        {erreur && (
          <p className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {erreur}
          </p>
        )}

        {estAdmin && (
          <button
            type="button"
            className="btn-primary mt-5"
            disabled={enregistrer.isPending}
            onClick={() => enregistrer.mutate()}
          >
            {enregistrer.isPending && <Spinner />}
            Enregistrer
          </button>
        )}
      </section>
    </div>
  )
}
