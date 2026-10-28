import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { recrutementApi, settingsApi } from '@/lib/api'
import type { DeploymentSettings, FournisseurIa } from '@/types'
import { useAuthStore } from '@/store/auth'
import { Callout, ErrorState, Field, PageLoader, Spinner, Toggle } from '@/components/ui'
import PanneauUtilisateurs from '@/components/PanneauUtilisateurs'
import AssistantMicrosoft365 from '@/components/AssistantMicrosoft365'
import EtatApplication from '@/components/EtatApplication'

/**
 * Paramètres du cabinet.
 *
 * Uniquement ce qui se règle : expurgation des données sensibles, inscription
 * libre, candidatures spontanées, clé du modèle d'IA, boîte Microsoft 365. Le
 * reste du déploiement — choix du fournisseur de modèle, stockage, modèles de
 * reconnaissance — n'est pas affiché : il se change dans le fichier de
 * configuration du serveur, et l'exposer en lecture seule n'aidait personne.
 *
 * Le seuil de présélection n'y figure plus. Il variait trop d'un mandat à
 * l'autre pour qu'une valeur d'établissement ait un sens, et le fixer avant
 * d'avoir vu la distribution des notes revenait à décider à l'aveugle. Il se
 * trace maintenant sur la grille du poste, une fois les dossiers notés.
 *
 * Deux secrets font exception à la règle « pas de secret dans un écran » : le
 * secret de l'application Microsoft et la clé du modèle d'IA. Les coller ici
 * évite un accès au serveur à chaque renouvellement. Ils partent vers le
 * serveur et n'en reviennent jamais — le champ affiche « déjà défini », pas la
 * valeur.
 */

const FOURNISSEURS: Array<{ cle: FournisseurIa; libelle: string; aide: string }> = [
  { cle: 'gemini', libelle: 'Google Gemini', aide: 'Clé sur aistudio.google.com › Get API key.' },
  { cle: 'anthropic', libelle: 'Anthropic (Claude)', aide: 'Clé sur console.anthropic.com › API keys.' },
  {
    cle: 'openai',
    libelle: 'Compatible OpenAI',
    aide: 'Groq, Mistral, OpenRouter, OpenAI… : l’adresse de l’API, la clé et le nom du modèle.',
  },
  { cle: 'ollama', libelle: 'Ollama (modèle local)', aide: 'Un modèle installé sur le serveur, sans clé.' },
]

const LIBELLE_FOURNISSEUR: Record<string, string> = Object.fromEntries(
  FOURNISSEURS.map((f) => [f.cle, f.libelle]),
)

/**
 * Le modèle d'IA : le fournisseur et ses clés, réglés sans toucher au serveur.
 *
 * Ce qui est réglé ici prime sur le fichier du serveur, quoi qu'il porte. Une
 * clé collée sans choisir de fournisseur fait servir le sien. « Celui du
 * serveur » rend la main au fichier.
 */
function PanneauIa({
  s,
  estAdmin,
  fournisseur,
  onFournisseur,
  modele,
  onModele,
  adresseOpenai,
  onAdresseOpenai,
  adresseOllama,
  onAdresseOllama,
  cles,
  onCle,
  revenirServeur,
}: {
  s: DeploymentSettings
  estAdmin: boolean
  fournisseur: '' | FournisseurIa
  onFournisseur: (v: '' | FournisseurIa) => void
  modele: string
  onModele: (v: string) => void
  adresseOpenai: string
  onAdresseOpenai: (v: string) => void
  adresseOllama: string
  onAdresseOllama: (v: string) => void
  cles: { gemini: string; anthropic: string; openai: string }
  onCle: (nom: 'gemini' | 'anthropic' | 'openai', valeur: string) => void
  revenirServeur: { isPending: boolean; mutate: () => void }
}) {
  // Les champs suivent le fournisseur retenu ; « celui du serveur » montre
  // ceux du fournisseur en service, pour pouvoir y coller une clé.
  const vise: FournisseurIa = (fournisseur || s.llm_provider) as FournisseurIa
  const aide = FOURNISSEURS.find((f) => f.cle === vise)?.aide
  const source = (nom: 'gemini' | 'anthropic' | 'openai') => s.ia_cles[nom] ?? ''
  const indication = (nom: 'gemini' | 'anthropic' | 'openai') =>
    source(nom) === 'ecran'
      ? 'Une clé est enregistrée ici. Laissez vide pour la conserver ; collez-en une autre pour la remplacer.'
      : source(nom) === 'serveur'
        ? 'La clé du serveur est en service. En coller une ici la remplace.'
        : `Aucune clé. ${aide ?? ''}`

  const champCle = (nom: 'gemini' | 'anthropic' | 'openai', libelle: string) => (
    <Field label={libelle} htmlFor={`cle-${nom}`} hint={indication(nom)}>
      <input
        id={`cle-${nom}`}
        type="password"
        className="input"
        value={cles[nom]}
        disabled={!estAdmin}
        autoComplete="off"
        spellCheck={false}
        placeholder={source(nom) ? '•••••••• (inchangée)' : ''}
        onChange={(e) => onCle(nom, e.target.value)}
      />
    </Field>
  )

  return (
    <div className="mt-6 border-t border-ink-100 pt-5">
      <h2 className="text-sm font-semibold text-ink-900">Modèle d&apos;IA</h2>
      <p className="mt-1 text-xs text-ink-500">
        Ce qui rédige les avis et les rapports et dépouille les dossiers. Réglé ici, il sert
        tout de suite, sans redémarrage, et prime sur le fichier de configuration du serveur.
      </p>
      <p className="mt-2 text-xs text-ink-700">
        En service : <strong>{LIBELLE_FOURNISSEUR[s.llm_provider] ?? s.llm_provider}</strong>
        {s.llm_model && !s.llm_model.startsWith('(') ? ` · ${s.llm_model}` : ''}
        {s.ia_regle_ecran ? ' — réglé ici' : ' — réglé sur le serveur'}
      </p>

      <div className="mt-4 space-y-3">
        <Field
          label="Fournisseur"
          htmlFor="ia-fournisseur"
          hint="« Celui du serveur » laisse le fichier de configuration décider. Une clé collée sans choisir fait servir son fournisseur."
        >
          <select
            id="ia-fournisseur"
            className="input"
            value={fournisseur}
            disabled={!estAdmin}
            onChange={(e) => onFournisseur(e.target.value as '' | FournisseurIa)}
          >
            <option value="">Celui du serveur</option>
            {FOURNISSEURS.map((f) => (
              <option key={f.cle} value={f.cle}>
                {f.libelle}
              </option>
            ))}
          </select>
        </Field>

        {vise === 'gemini' && champCle('gemini', 'Clé de l’API Gemini')}
        {vise === 'anthropic' && champCle('anthropic', 'Clé de l’API Anthropic')}
        {vise === 'openai' && (
          <>
            <Field
              label="Adresse de l'API"
              htmlFor="ia-adresse-openai"
              hint="Celle que donne le fournisseur, se terminant d'ordinaire par /v1."
            >
              <input
                id="ia-adresse-openai"
                className="input"
                value={adresseOpenai}
                disabled={!estAdmin}
                placeholder="https://api.groq.com/openai/v1"
                onChange={(e) => onAdresseOpenai(e.target.value)}
              />
            </Field>
            {champCle('openai', 'Clé de l’API')}
          </>
        )}
        {vise === 'ollama' && (
          <Field label="Adresse d'Ollama" htmlFor="ia-adresse-ollama">
            <input
              id="ia-adresse-ollama"
              className="input"
              value={adresseOllama}
              disabled={!estAdmin}
              placeholder="http://ollama:11434"
              onChange={(e) => onAdresseOllama(e.target.value)}
            />
          </Field>
        )}

        <Field
          label={vise === 'openai' ? 'Modèle' : 'Modèle (facultatif)'}
          htmlFor="ia-modele"
          hint={
            vise === 'openai'
              ? 'Obligatoire pour ce fournisseur : il n’a pas de modèle par défaut.'
              : 'Vide : le modèle par défaut du fournisseur.'
          }
        >
          <input
            id="ia-modele"
            className="input"
            value={modele}
            disabled={!estAdmin}
            spellCheck={false}
            onChange={(e) => onModele(e.target.value)}
          />
        </Field>

        {estAdmin && s.ia_regle_ecran && (
          <button
            type="button"
            className="btn-ghost px-3 py-1.5 text-xs"
            disabled={revenirServeur.isPending}
            onClick={() => revenirServeur.mutate()}
          >
            {revenirServeur.isPending && <Spinner />}
            Revenir au réglage du serveur
          </button>
        )}
        <p className="text-xs text-ink-500">
          Après l&apos;enregistrement, l&apos;onglet « État » vérifie la clé : bouton
          « Essayer » sur la ligne Modèle d&apos;IA.
        </p>
      </div>
    </div>
  )
}

type Onglet = 'etat' | 'general' | 'courriel' | 'comptes'

// « État » d'abord : c'est ce qu'un administrateur vient vérifier, et ce
// qui dit vers quel autre onglet aller.
const ONGLETS: Array<[Onglet, string]> = [
  ['etat', 'État'],
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

  // Boîte de candidatures Microsoft 365 (réception).
  const [courriel, setCourriel] = useState(false)
  const [adresse, setAdresse] = useState('')
  const [dossier, setDossier] = useState('inbox')
  const [testResultat, setTestResultat] = useState<string | null>(null)
  const [testErreur, setTestErreur] = useState<string | null>(null)

  // Envoi, depuis la même boîte sauf adresse d'expédition réglée.
  const [envoi, setEnvoi] = useState(false)
  const [expediteur, setExpediteur] = useState('')
  const [urlPublique, setUrlPublique] = useState('')
  const [envoiResultat, setEnvoiResultat] = useState<string | null>(null)
  const [envoiErreur, setEnvoiErreur] = useState<string | null>(null)

  // Accès Microsoft 365 : les trois valeurs de l'inscription d'application.
  const [tenant, setTenant] = useState('')
  const [clientId, setClientId] = useState('')
  const [clientSecret, setClientSecret] = useState('')

  // Le modèle d'IA. Fournisseur vide : le fichier du serveur décide. Les
  // clés ne sont jamais réaffichées : vide veut dire « inchangée ».
  const [iaFournisseur, setIaFournisseur] = useState<'' | FournisseurIa>('')
  const [iaModele, setIaModele] = useState('')
  const [adresseOpenai, setAdresseOpenai] = useState('')
  const [adresseOllama, setAdresseOllama] = useState('')
  const [cles, setCles] = useState({ gemini: '', anthropic: '', openai: '' })

  const [contactCandidats, setContactCandidats] = useState('')

  const [onglet, setOnglet] = useState<Onglet>(estAdmin ? 'etat' : 'general')
  const [assistant, setAssistant] = useState(false)
  // L'assistant s'ouvre de lui-même la première fois qu'un administrateur
  // arrive sur l'onglet Courriel sans rien de réglé : c'est là qu'on a besoin
  // de la marche à suivre, pas dans un guide à retrouver. Une fois par visite
  // de la page — le bouton « Reprendre la marche à suivre » fait le reste.
  const [assistantPropose, setAssistantPropose] = useState(false)
  useEffect(() => {
    const s = reglages.data
    if (onglet !== 'courriel' || !estAdmin || !s || assistantPropose) return
    setAssistantPropose(true)
    if (!s.oauth_tenant && !s.oauth_client_id && !s.oauth_client_secret_defini) {
      setAssistant(true)
    }
  }, [onglet, estAdmin, reglages.data, assistantPropose])

  // Le formulaire part de l'état du serveur, pas d'une valeur inventée.
  useEffect(() => {
    if (!reglages.data) return
    setDemographiques(reglages.data.redact_demographics)
    setInscription(reglages.data.allow_self_registration)
    setSpontanees(reglages.data.candidatures_spontanees)
    setCourriel(reglages.data.courriel_actif)
    setAdresse(reglages.data.adresse_boite)
    setDossier(reglages.data.dossier_boite)
    setEnvoi(reglages.data.envoi_actif)
    setExpediteur(reglages.data.adresse_expediteur)
    setUrlPublique(reglages.data.url_publique)
    setTenant(reglages.data.oauth_tenant)
    setClientId(reglages.data.oauth_client_id)
    setContactCandidats(reglages.data.contact_candidats)
    // Jamais réhydratés : le serveur ne renvoie aucun secret.
    setClientSecret('')
    setIaFournisseur(reglages.data.ia_fournisseur_ecran)
    setIaModele(reglages.data.ia_modele_ecran)
    setAdresseOpenai(reglages.data.ia_adresse_openai)
    setAdresseOllama(reglages.data.ia_adresse_ollama)
    setCles({ gemini: '', anthropic: '', openai: '' })
  }, [reglages.data])

  const enregistrer = useMutation({
    mutationFn: () =>
      settingsApi.modifier({
        redact_demographics: demographiques,
        allow_self_registration: inscription,
        candidatures_spontanees: spontanees,
        courriel_actif: courriel,
        adresse_boite: adresse.trim(),
        dossier_boite: dossier.trim() || 'inbox',
        envoi_actif: envoi,
        adresse_expediteur: expediteur.trim(),
        url_publique: urlPublique.trim(),
        oauth_tenant: tenant.trim(),
        oauth_client_id: clientId.trim(),
        // Vide = inchangé, côté serveur comme ici.
        oauth_client_secret: clientSecret,
        llm_provider: iaFournisseur,
        llm_model: iaModele.trim(),
        gemini_api_key: cles.gemini.trim(),
        anthropic_api_key: cles.anthropic.trim(),
        llm_api_key: cles.openai.trim(),
        llm_base_url: adresseOpenai.trim(),
        ollama_base_url: adresseOllama.trim(),
        contact_candidats: contactCandidats.trim(),
      }),
    onSuccess: () => {
      setErreur(null)
      setMessage('Réglages enregistrés.')
      setClientSecret('')
      setCles({ gemini: '', anthropic: '', openai: '' })
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
      void queryClient.invalidateQueries({ queryKey: ['aide-publique'] })
      void queryClient.invalidateQueries({ queryKey: ['courriel', 'etat'] })
      void queryClient.invalidateQueries({ queryKey: ['sante'] })
    },
    onError: (e) => {
      setMessage(null)
      setErreur(e instanceof Error ? e.message : 'Enregistrement impossible')
    },
  })

  const revenirServeur = useMutation({
    mutationFn: settingsApi.revenirIaServeur,
    onSuccess: () => {
      setErreur(null)
      setMessage('Le modèle d’IA suit de nouveau le réglage du serveur.')
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
      void queryClient.invalidateQueries({ queryKey: ['sante'] })
    },
    onError: (e) => {
      setMessage(null)
      setErreur(e instanceof Error ? e.message : 'Retrait impossible')
    },
  })

  // Tester porte sur ce qui est *enregistré*, pas sur ce qui est à l'écran :
  // c'est la connexion réelle que les RH veulent voir aboutir.
  const testerEnvoi = useMutation({
    mutationFn: settingsApi.testerEnvoi,
    onSuccess: (r) => {
      setEnvoiErreur(null)
      setEnvoiResultat(`Accès vérifié. Les messages partiront de ${r.expediteur}.`)
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

      {/* Des onglets plutôt qu'une colonne de mille pixels : la pratique du
          cabinet se règle une fois, le courriel se débogue à plusieurs
          reprises, et les comptes s'ouvrent quand quelqu'un arrive. Rien ne
          gagnait à les empiler. */}
      <div className="mt-5 flex gap-1 border-b border-ink-200">
        {ONGLETS.filter(([cle]) => (cle !== 'comptes' && cle !== 'etat') || estAdmin).map(([cle, libelle]) => (
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

      {onglet === 'etat' && estAdmin && (
        <div className="mt-5">
          <EtatApplication onAller={setOnglet} />
        </div>
      )}

      {onglet === 'comptes' && (
        <div className="mt-5">
          <PanneauUtilisateurs />
        </div>
      )}

      <section
        className={`card mt-5 p-5 ${onglet === 'comptes' || onglet === 'etat' ? 'hidden' : ''}`}
      >
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

        <PanneauIa
          s={s}
          estAdmin={estAdmin}
          fournisseur={iaFournisseur}
          onFournisseur={setIaFournisseur}
          modele={iaModele}
          onModele={setIaModele}
          adresseOpenai={adresseOpenai}
          onAdresseOpenai={setAdresseOpenai}
          adresseOllama={adresseOllama}
          onAdresseOllama={setAdresseOllama}
          cles={cles}
          onCle={(nom, valeur) => setCles((c) => ({ ...c, [nom]: valeur }))}
          revenirServeur={revenirServeur}
        />

        </div>

        <div className={onglet === 'courriel' ? '' : 'hidden'}>
        <div>
          <h2 className="text-sm font-semibold text-ink-900">Accès Microsoft 365</h2>
          <p className="mt-1 text-xs text-ink-500">
            La boîte de recrutement est lue, et les messages envoyés, par Microsoft Graph. Ces
            trois valeurs viennent d&apos;une inscription d&apos;application dans Entra ID ; la
            marche à suivre les donne une à une.
          </p>

          {estAdmin && (
            <button
              type="button"
              className="btn-secondary mt-3"
              onClick={() => setAssistant(true)}
            >
              {s.oauth_client_secret_defini ? 'Reprendre la marche à suivre' : 'Ouvrir la marche à suivre'}
            </button>
          )}

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
              htmlFor="adresse-boite"
              hint="L'adresse dédiée au recrutement, celle qui figure dans les avis."
            >
              <input
                id="adresse-boite"
                type="email"
                className="input"
                value={adresse}
                disabled={!estAdmin}
                placeholder="recrutement@kapiconsult.tg"
                onChange={(e) => setAdresse(e.target.value)}
              />
            </Field>

            <Field
              label="Dossier à relever"
              htmlFor="dossier-boite"
              hint="« inbox » pour la boîte de réception. Un autre dossier s'écrit sous son nom affiché dans Outlook."
            >
              <input
                id="dossier-boite"
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
            promoteur son accès à l'espace de suivi. Les messages partent de la boîte Microsoft
            365 et restent dans ses éléments envoyés.
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
              htmlFor="adresse-expediteur"
              hint="Ce que les candidats verront en « De : ». Laissée vide, c'est la boîte de candidatures qui écrit."
            >
              <input
                id="adresse-expediteur"
                type="email"
                className="input"
                value={expediteur}
                disabled={!estAdmin}
                placeholder={adresse || 'recrutement@kapiconsult.tg'}
                onChange={(e) => setExpediteur(e.target.value)}
              />
            </Field>

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
                Vérifie l&apos;accès sans rien expédier. Enregistrez d&apos;abord.
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
