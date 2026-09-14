import { useState } from 'react'
import { avisPublicApi } from '@/lib/api'
import { Callout, Field, Spinner } from '@/components/ui'
import SaisieParcoursDeclare, {
  PARCOURS_VIDE,
  parcoursRempli,
  versParcours,
  type SaisieParcours,
} from '@/components/ParcoursDeclare'

/**
 * « Déposer votre CV » — la candidature hors avis.
 *
 * Le cabinet reçoit des dossiers en dehors de toute campagne : quelqu'un écrit
 * à l'adresse de recrutement, ou passe par le site. Ces profils n'étaient
 * jusqu'ici rattachables à rien et se perdaient. Ils rejoignent maintenant le
 * vivier, où une recherche par profil les retrouve le jour où un mandat leur
 * correspond.
 *
 * Le formulaire ne promet rien qu'il ne tienne : aucune réponse n'est annoncée,
 * parce qu'aucun poste n'est en jeu. Il dit exactement ce qui va se passer —
 * le dossier est conservé et ressortira si un profil correspond.
 */
export default function CandidatureSpontanee() {
  const [ouvert, setOuvert] = useState(false)
  const [nom, setNom] = useState('')
  const [prenom, setPrenom] = useState('')
  const [email, setEmail] = useState('')
  const [telephone, setTelephone] = useState('')
  const [domaine, setDomaine] = useState('')
  const [message, setMessage] = useState('')
  // Un profil du vivier ne vaut que par ce qu'on peut y chercher. Sans parcours
  // déclaré, le dossier n'est qu'un fichier joint à un nom, et il faut le lire
  // avant de savoir s'il correspond au mandat qui vient d'arriver.
  const [dateNaissance, setDateNaissance] = useState('')
  const [nationalites, setNationalites] = useState('')
  const [parcours, setParcours] = useState<SaisieParcours>(PARCOURS_VIDE)
  const [cv, setCv] = useState<File | null>(null)
  const [erreurs, setErreurs] = useState<Record<string, string>>({})
  const [erreurEnvoi, setErreurEnvoi] = useState<string | null>(null)
  const [envoi, setEnvoi] = useState(false)
  const [termine, setTermine] = useState(false)

  async function envoyer(event: React.FormEvent) {
    event.preventDefault()
    const trouvees: Record<string, string> = {}
    if (!nom.trim()) trouvees.nom = 'Champ obligatoire'
    if (!prenom.trim()) trouvees.prenom = 'Champ obligatoire'
    if (!email.trim()) trouvees.email = 'Champ obligatoire'
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim()))
      trouvees.email = 'Adresse email invalide'
    if (!cv) trouvees.cv = 'Votre curriculum vitae est nécessaire'
    setErreurs(trouvees)
    if (Object.keys(trouvees).length > 0) return

    setEnvoi(true)
    setErreurEnvoi(null)
    try {
      await avisPublicApi.candidatureSpontanee({
        nom: nom.trim(),
        prenom: prenom.trim(),
        email: email.trim(),
        telephone: telephone.trim() || undefined,
        domaine: domaine.trim() || undefined,
        message: message.trim() || undefined,
        date_naissance: dateNaissance || undefined,
        nationalites: nationalites.trim() || undefined,
        parcours: parcoursRempli(parcours) ? versParcours(parcours) : undefined,
        pieces: [{ code: 'CV', fichier: cv! }],
      })
      setTermine(true)
    } catch (caught) {
      setErreurEnvoi(caught instanceof Error ? caught.message : 'Une erreur est survenue')
    } finally {
      setEnvoi(false)
    }
  }

  if (termine) {
    return (
      <div className="card mt-10 p-6">
        <h2 className="text-base font-semibold text-ink-900">Dossier enregistré</h2>
        <p className="mt-2 text-sm text-ink-600">
          Votre profil est conservé dans notre base. Nous vous contacterons si un recrutement
          correspond à votre parcours. Aucun poste n&apos;étant ouvert sur ce dépôt, il n&apos;y a
          pas de suite immédiate à en attendre.
        </p>
      </div>
    )
  }

  if (!ouvert) {
    return (
      <div className="card mt-10 p-6">
        <h2 className="text-base font-semibold text-ink-900">Aucun poste ne correspond ?</h2>
        <p className="mt-1 text-sm text-ink-600">
          Déposez votre curriculum vitae. Votre profil sera conservé et réexaminé lors de nos
          prochains recrutements.
        </p>
        <button type="button" className="btn-ghost mt-4" onClick={() => setOuvert(true)}>
          Déposer mon CV
        </button>
      </div>
    )
  }

  return (
    <form className="card mt-10 space-y-4 p-6" onSubmit={envoyer}>
      <div>
        <h2 className="text-base font-semibold text-ink-900">Candidature spontanée</h2>
        <p className="mt-1 text-sm text-ink-600">
          Votre profil rejoindra notre base et sera réexaminé lors de nos prochains recrutements.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Nom" htmlFor="sp-nom" error={erreurs.nom}>
          <input
            id="sp-nom"
            className="input"
            value={nom}
            autoComplete="family-name"
            onChange={(e) => setNom(e.target.value)}
          />
        </Field>
        <Field label="Prénom" htmlFor="sp-prenom" error={erreurs.prenom}>
          <input
            id="sp-prenom"
            className="input"
            value={prenom}
            autoComplete="given-name"
            onChange={(e) => setPrenom(e.target.value)}
          />
        </Field>
      </div>

      <Field label="Adresse email" htmlFor="sp-email" error={erreurs.email}>
        <input
          id="sp-email"
          type="email"
          className="input"
          value={email}
          autoComplete="email"
          onChange={(e) => setEmail(e.target.value)}
        />
      </Field>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Téléphone (facultatif)" htmlFor="sp-tel">
          <input
            id="sp-tel"
            className="input"
            value={telephone}
            autoComplete="tel"
            onChange={(e) => setTelephone(e.target.value)}
          />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Date de naissance (facultatif)" htmlFor="sp-naissance">
            <input
              id="sp-naissance"
              type="date"
              className="input"
              value={dateNaissance}
              max={new Date().toISOString().slice(0, 10)}
              onChange={(e) => setDateNaissance(e.target.value)}
              autoComplete="bday"
            />
          </Field>
          <Field label="Nationalité(s) (facultatif)" htmlFor="sp-nationalites">
            <input
              id="sp-nationalites"
              className="input"
              value={nationalites}
              placeholder="togolaise"
              onChange={(e) => setNationalites(e.target.value)}
            />
          </Field>
        </div>

        <Field
          label="Domaine visé (facultatif)"
          htmlFor="sp-domaine"
          hint="Ce qui aidera à vous retrouver le moment venu."
        >
          <input
            id="sp-domaine"
            className="input"
            value={domaine}
            placeholder="Gestion hôtelière, finance, ingénierie…"
            onChange={(e) => setDomaine(e.target.value)}
          />
        </Field>
      </div>

      <Field label="Curriculum vitae" htmlFor="sp-cv" error={erreurs.cv}>
        <input
          id="sp-cv"
          type="file"
          accept=".pdf,.docx,.doc"
          className="input"
          onChange={(e) => setCv(e.target.files?.[0] ?? null)}
        />
      </Field>

      <SaisieParcoursDeclare valeur={parcours} onChange={setParcours} erreurs={erreurs} />

      <Field label="Message (facultatif)" htmlFor="sp-message">
        <textarea
          id="sp-message"
          className="input"
          rows={3}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
        />
      </Field>

      {erreurEnvoi && <Callout tone="danger">{erreurEnvoi}</Callout>}

      <div className="flex flex-wrap gap-2">
        <button type="submit" className="btn-primary" disabled={envoi}>
          {envoi && <Spinner />}
          {envoi ? 'Envoi en cours…' : 'Envoyer mon dossier'}
        </button>
        <button type="button" className="btn-ghost" onClick={() => setOuvert(false)}>
          Annuler
        </button>
      </div>

      <p className="text-xs text-ink-500">
        Les informations transmises servent uniquement à l&apos;examen de votre profil.
      </p>
    </form>
  )
}
