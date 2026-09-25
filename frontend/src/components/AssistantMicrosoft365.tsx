import { Callout, CopyField, Field, Modal } from '@/components/ui'

/**
 * Brancher une boîte Microsoft 365, étape par étape.
 *
 * L'écran demandait trois valeurs — locataire, application, secret — sans dire
 * où les prendre, et la marche à suivre dormait dans un PDF que personne
 * n'ouvre en configurant. L'administrateur voyait trois champs vides et un
 * message expliquant que son mot de passe ne marcherait pas.
 *
 * Cette fenêtre s'ouvre d'elle-même au moment où l'on choisit Microsoft 365 :
 * c'est là qu'on en a besoin, pas dans un guide à retrouver. Elle donne les
 * liens à ouvrir, les champs à remplir, et surtout **le lien de consentement**,
 * fabriqué à mesure qu'on tape — c'est le seul geste de toute l'opération qui
 * tient vraiment en un clic, et il était jusqu'ici décrit en prose.
 *
 * Deux précautions de rédaction :
 *
 * L'administrateur d'Entra ID n'est pas toujours celui qui configure TriCV. Le
 * lien de consentement se copie donc aussi bien qu'il se clique, avec de quoi
 * l'envoyer à qui détient les droits.
 *
 * Les libellés du portail Microsoft changent, et cette fenêtre ne peut pas
 * changer avec eux. Chaque étape nomme donc ce qu'on cherche plutôt que le
 * chemin exact pour y arriver, et dit ce qu'on doit en rapporter — quelqu'un
 * qui ne retrouve pas un bouton sait au moins ce qu'il cherche.
 */

const PORTAIL_ENTRA = 'https://entra.microsoft.com/'

/** Le lien de consentement administrateur, tel que Microsoft l'attend. */
export function lienConsentement(tenant: string, clientId: string, retour: string): string {
  const t = encodeURIComponent(tenant.trim())
  const params = new URLSearchParams({ client_id: clientId.trim() })
  if (retour.trim()) params.set('redirect_uri', retour.trim())
  return `https://login.microsoftonline.com/${t}/adminconsent?${params.toString()}`
}

export default function AssistantMicrosoft365({
  tenant,
  clientId,
  secretDefini,
  urlPublique,
  onTenant,
  onClientId,
  onSecret,
  onClose,
}: {
  tenant: string
  clientId: string
  secretDefini: boolean
  urlPublique: string
  onTenant: (v: string) => void
  onClientId: (v: string) => void
  onSecret: (v: string) => void
  onClose: () => void
}) {
  const complet = Boolean(tenant.trim() && clientId.trim())
  // Microsoft renvoie l'administrateur quelque part après son consentement. À
  // défaut d'adresse publique renseignée, on ne met pas de `redirect_uri` :
  // Microsoft retombe alors sur celle de l'inscription, et une adresse fausse
  // ferait échouer le consentement juste après qu'il a été donné.
  const retour = urlPublique.trim() ? `${urlPublique.trim().replace(/\/+$/, '')}/settings` : ''
  const lien = complet ? lienConsentement(tenant, clientId, retour) : ''

  const message =
    `Bonjour,\n\n` +
    `Nous mettons en service l'outil de recrutement du cabinet, qui doit relever ` +
    `et envoyer le courriel depuis notre boîte de recrutement.\n\n` +
    `Pourriez-vous ouvrir le lien ci-dessous et accorder le consentement ` +
    `administrateur ? Il n'accorde que la lecture et l'envoi de courriel à ` +
    `l'application déjà inscrite dans notre annuaire.\n\n` +
    `${lien}\n\n` +
    `Idéalement, restreindre ensuite l'application à la seule boîte de ` +
    `recrutement, avec la commande Exchange Online :\n` +
    `New-ApplicationAccessPolicy -AppId ${clientId.trim() || '<ID application>'} ` +
    `-PolicyScopeGroupId <adresse de la boîte> -AccessRight RestrictAccess ` +
    `-Description "Outil de recrutement"\n\n` +
    `Merci.`

  return (
    <Modal open title="Connecter une boîte Microsoft 365" onClose={onClose}>
      <div className="space-y-5">
        <Callout tone="info">
          Microsoft n&apos;accepte plus de mot de passe pour relever une boîte professionnelle,
          quel qu&apos;il soit. Il faut déclarer TriCV une fois dans votre annuaire, puis lui
          accorder l&apos;accès à la boîte. Comptez une dizaine de minutes, et les droits
          d&apos;administrateur de l&apos;annuaire — si vous ne les avez pas, l&apos;étape 4 se
          délègue.
        </Callout>

        <Etape numero={1} titre="Déclarer TriCV dans votre annuaire">
          <p>
            Ouvrez{' '}
            <a
              className="font-medium underline"
              href={PORTAIL_ENTRA}
              target="_blank"
              rel="noreferrer noopener"
            >
              le portail Microsoft Entra
            </a>{' '}
            puis <b>Applications</b> › <b>Inscriptions d&apos;applications</b> › <b>Nouvelle
            inscription</b>. Un nom suffit — « TriCV — recrutement » par exemple. Laissez le
            reste tel quel.
          </p>
          {retour && (
            <div className="mt-2">
              <p className="mb-1 text-xs text-ink-500">
                Ajoutez cette adresse de redirection (type « Web ») : elle ramène ici après le
                consentement.
              </p>
              <CopyField value={retour} label="Adresse de redirection" />
            </div>
          )}
        </Etape>

        <Etape numero={2} titre="Relever les deux identifiants">
          <p>
            Sur la page <b>Vue d&apos;ensemble</b> de l&apos;application, relevez
            l&apos;<b>ID de l&apos;annuaire (locataire)</b> et l&apos;<b>ID
            d&apos;application (client)</b>, puis collez-les ici.
          </p>
          <div className="mt-3 space-y-3">
            <Field label="ID du locataire (tenant)" htmlFor="assistant-tenant">
              <input
                id="assistant-tenant"
                className="input font-mono text-xs"
                value={tenant}
                placeholder="00000000-0000-0000-0000-000000000000"
                onChange={(e) => onTenant(e.target.value)}
              />
            </Field>
            <Field label="ID de l'application (client)" htmlFor="assistant-client">
              <input
                id="assistant-client"
                className="input font-mono text-xs"
                value={clientId}
                placeholder="00000000-0000-0000-0000-000000000000"
                onChange={(e) => onClientId(e.target.value)}
              />
            </Field>
          </div>
        </Etape>

        <Etape numero={3} titre="Créer un secret, et le coller tout de suite">
          <p>
            <b>Certificats et secrets</b> › <b>Nouveau secret client</b>. Choisissez la durée la
            plus longue proposée, puis copiez la <b>valeur</b> — pas son identifiant. Microsoft
            ne la réaffiche jamais ; si elle est perdue, il faut en créer une autre.
          </p>
          <div className="mt-3">
            <Field
              label="Secret client"
              htmlFor="assistant-secret"
              hint={
                secretDefini
                  ? 'Un secret est déjà enregistré. Laissez vide pour le conserver.'
                  : 'Notez aussi sa date d’échéance quelque part : le jour où il expire, le relevé s’arrête.'
              }
            >
              <input
                id="assistant-secret"
                type="password"
                className="input"
                autoComplete="new-password"
                placeholder={secretDefini ? '•••••••• (inchangé)' : ''}
                onChange={(e) => onSecret(e.target.value)}
              />
            </Field>
          </div>
        </Etape>

        <Etape numero={4} titre="Accorder le consentement — le lien">
          <p>
            Dans <b>API autorisées</b>, ajoutez à Microsoft Graph les{' '}
            <b>autorisations d&apos;application</b> <code>Mail.ReadWrite</code> et{' '}
            <code>Mail.Send</code>. Le consentement se donne ensuite par ce lien :
          </p>
          {complet ? (
            <div className="mt-3 space-y-2">
              <a
                className="btn-primary inline-flex"
                href={lien}
                target="_blank"
                rel="noreferrer noopener"
              >
                Ouvrir le consentement administrateur
              </a>
              <p className="text-xs text-ink-500">
                Ou, si les droits d&apos;annuaire appartiennent à quelqu&apos;un d&apos;autre,
                envoyez-lui ce message :
              </p>
              <textarea className="input font-mono text-xs" rows={6} readOnly value={message} />
              <button
                type="button"
                className="btn-ghost px-3 py-1.5 text-xs"
                onClick={() => void navigator.clipboard.writeText(message)}
              >
                Copier le message
              </button>
            </div>
          ) : (
            <Callout tone="warning">
              Le lien se fabrique dès que les deux identifiants de l&apos;étape 2 sont remplis.
            </Callout>
          )}
        </Etape>

        <Etape numero={5} titre="Restreindre à la seule boîte de recrutement">
          <p>
            Les autorisations accordées portent sur <b>toutes</b> les boîtes de
            l&apos;organisation. Un administrateur Exchange les ramène à la seule boîte de
            recrutement avec cette commande — vivement recommandé, et sans effet sur TriCV :
          </p>
          <div className="mt-2">
            <CopyField
              value={`New-ApplicationAccessPolicy -AppId ${
                clientId.trim() || '<ID application>'
              } -PolicyScopeGroupId <adresse de la boîte> -AccessRight RestrictAccess -Description "TriCV"`}
              label="Commande Exchange Online"
            />
          </div>
        </Etape>

        <Etape numero={6} titre="Enregistrer, puis tester">
          <p>
            Fermez cette fenêtre, vérifiez l&apos;adresse de la boîte plus bas, puis{' '}
            <b>Enregistrez</b>. Le bouton <b>Tester la connexion</b> ouvre alors une vraie
            session : c&apos;est lui qui dit si le consentement est bien passé.
          </p>
        </Etape>

        <div className="flex justify-end">
          <button type="button" className="btn-primary" onClick={onClose}>
            Revenir aux réglages
          </button>
        </div>
      </div>
    </Modal>
  )
}

function Etape({
  numero,
  titre,
  children,
}: {
  numero: number
  titre: string
  children: React.ReactNode
}) {
  return (
    <div className="flex gap-3">
      <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-100 text-xs font-semibold text-brand-800">
        {numero}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-ink-900">{titre}</p>
        <div className="mt-1 text-xs leading-relaxed text-ink-600">{children}</div>
      </div>
    </div>
  )
}
