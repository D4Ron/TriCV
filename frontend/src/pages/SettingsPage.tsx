import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { recrutementApi, settingsApi } from '@/lib/api'
import { useAuthStore } from '@/store/auth'
import { Callout, ErrorState, Field, PageLoader, Spinner, Toggle } from '@/components/ui'

/**
 * Paramètres du cabinet.
 *
 * Uniquement ce qui se règle : seuil, expurgation des données sensibles,
 * inscription libre, boîte de candidatures. La configuration du déploiement —
 * fournisseur de modèle, stockage, modèles de reconnaissance — n'est pas
 * affichée : elle se change dans le fichier de configuration du serveur, et
 * l'exposer en lecture seule n'aidait personne à agir.
 *
 * La boîte fait exception à la règle « pas de secret dans un écran » : son mot
 * de passe se règle ici parce que l'adresse de recrutement change avec les
 * campagnes et qu'un mot de passe d'application se révoque. Il part vers le
 * serveur et n'en revient jamais — le champ affiche « déjà défini », pas la
 * valeur.
 */
export default function SettingsPage() {
  const queryClient = useQueryClient()
  const user = useAuthStore((state) => state.user)
  const estAdmin = user?.role === 'ADMIN'

  const reglages = useQuery({ queryKey: ['settings'], queryFn: settingsApi.get })

  const [seuil, setSeuil] = useState('20')
  const [demographiques, setDemographiques] = useState(true)
  const [inscription, setInscription] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)

  // Boîte de candidatures.
  const [courriel, setCourriel] = useState(false)
  const [hote, setHote] = useState('')
  const [port, setPort] = useState('993')
  const [adresse, setAdresse] = useState('')
  const [motDePasse, setMotDePasse] = useState('')
  const [dossier, setDossier] = useState('INBOX')
  const [testResultat, setTestResultat] = useState<string | null>(null)
  const [testErreur, setTestErreur] = useState<string | null>(null)

  // Le formulaire part de l'état du serveur, pas d'une valeur inventée.
  useEffect(() => {
    if (!reglages.data) return
    setSeuil(String(reglages.data.seuil_preselection_defaut))
    setDemographiques(reglages.data.redact_demographics)
    setInscription(reglages.data.allow_self_registration)
    setCourriel(reglages.data.courriel_actif)
    setHote(reglages.data.imap_host)
    setPort(String(reglages.data.imap_port))
    setAdresse(reglages.data.imap_user)
    setDossier(reglages.data.imap_folder)
    // Jamais réhydraté : le serveur ne renvoie pas le secret.
    setMotDePasse('')
  }, [reglages.data])

  const enregistrer = useMutation({
    mutationFn: () =>
      settingsApi.modifier({
        seuil_preselection_defaut: Number(seuil),
        redact_demographics: demographiques,
        allow_self_registration: inscription,
        courriel_actif: courriel,
        imap_host: hote.trim(),
        imap_port: Number(port) || 993,
        imap_user: adresse.trim(),
        // Vide = inchangé, côté serveur comme ici.
        imap_password: motDePasse,
        imap_folder: dossier.trim() || 'INBOX',
      }),
    onSuccess: () => {
      setErreur(null)
      setMessage('Réglages enregistrés.')
      setMotDePasse('')
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
      void queryClient.invalidateQueries({ queryKey: ['courriel', 'etat'] })
    },
    onError: (e) => {
      setMessage(null)
      setErreur(e instanceof Error ? e.message : 'Enregistrement impossible')
    },
  })

  // Tester porte sur ce qui est *enregistré*, pas sur ce qui est à l'écran :
  // c'est la connexion réelle que les RH veulent voir aboutir.
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
        Les réglages du cabinet s'appliquent aux nouveaux postes ; les fiches existantes gardent
        les leurs.
      </p>

      {!s.redact_demographics && (
        <div className="mt-5">
          <Callout tone="warning" title="Données démographiques transmises au modèle">
            L'âge, le sexe et la nationalité ne sont plus retirés des documents avant analyse.
            C'est une décision, pas un oubli — remettez-la en place si ce n'est pas voulu.
          </Callout>
        </div>
      )}

      <section className="card mt-5 p-5">
        <h2 className="text-sm font-semibold text-ink-900">Pratique de recrutement</h2>
        <p className="mt-1 text-xs text-ink-500">
          {estAdmin
            ? 'Modifiable ici, sans redémarrage.'
            : "Réservé aux administrateurs. Vous pouvez consulter ces réglages sans les modifier."}
        </p>

        <div className="mt-4 space-y-4">
          <Field
            label="Seuil de présélection par défaut (sur 30)"
            htmlFor="seuil"
            hint="Appliqué aux nouveaux postes. L'abaisser sur un poste donné exige toujours une justification écrite."
          >
            <input
              id="seuil"
              type="number"
              min={0}
              max={30}
              step={0.5}
              className="input"
              value={seuil}
              disabled={!estAdmin}
              onChange={(e) => setSeuil(e.target.value)}
            />
          </Field>

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
                disabled={tester.isPending || !s.imap_host}
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
