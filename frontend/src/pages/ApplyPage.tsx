import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { avisPublicApi } from '@/lib/api'
import { Logo } from '@/components/Layout'
import { Callout, Field, PageLoader, Spinner } from '@/components/ui'
import { formatDate } from '@/lib/format'

/**
 * La page candidat. Elle montre le poste et un formulaire — jamais une note,
 * un rang, ni quoi que ce soit sur les autres candidats.
 */
export default function ApplyPage() {
  const { publicKey = '' } = useParams()

  const avis = useQuery({
    queryKey: ['avis-public', publicKey],
    queryFn: () => avisPublicApi.detail(publicKey),
    retry: false,
  })

  const [nom, setNom] = useState('')
  const [prenom, setPrenom] = useState('')
  const [email, setEmail] = useState('')
  const [telephone, setTelephone] = useState('')
  const [fichiers, setFichiers] = useState<Record<string, File>>({})
  const [erreurs, setErreurs] = useState<Record<string, string>>({})
  const [erreurEnvoi, setErreurEnvoi] = useState<string | null>(null)
  const [envoi, setEnvoi] = useState(false)
  const [termine, setTermine] = useState(false)

  const enveloppe = (contenu: React.ReactNode) => (
    <div className="min-h-screen bg-ink-50">
      <header className="border-b border-ink-200 bg-white">
        <div className="mx-auto flex h-14 max-w-3xl items-center px-4">
          <Logo />
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-4 py-10">{contenu}</main>
    </div>
  )

  if (avis.isLoading) return enveloppe(<PageLoader />)
  if (avis.isError)
    return enveloppe(
      <div>
        <Callout tone="danger">Ce lien de candidature n'est pas valide ou a expiré.</Callout>
        <Link to="/careers" className="btn-ghost mt-4">
          Voir tous les postes ouverts
        </Link>
      </div>,
    )

  const a = avis.data!

  if (termine)
    return enveloppe(
      <div className="card p-8 text-center">
        <h1 className="text-lg font-semibold text-ink-900">Candidature enregistrée</h1>
        <p className="mt-2 text-sm text-ink-600">
          Votre dossier pour le poste de <strong>{a.intitule}</strong> a bien été reçu. Vous serez
          contacté si votre profil est retenu à l'issue de la présélection.
        </p>
        <Link to="/careers" className="btn-ghost mt-6">
          Voir les autres postes
        </Link>
      </div>,
    )

  async function envoyer(event: React.FormEvent) {
    event.preventDefault()
    const trouvees: Record<string, string> = {}
    if (!nom.trim()) trouvees.nom = 'Champ obligatoire'
    if (!prenom.trim()) trouvees.prenom = 'Champ obligatoire'
    if (!email.trim()) trouvees.email = 'Champ obligatoire'
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim()))
      trouvees.email = 'Adresse email invalide'
    for (const piece of a.pieces_attendues) {
      if (!fichiers[piece.code]) trouvees[piece.code] = 'Pièce obligatoire'
    }
    // Refuser ici évite un aller-retour et un message d'erreur générique.
    for (const [code, fichier] of Object.entries(fichiers)) {
      if (fichier.size > a.taille_max_mo * 1024 * 1024) {
        trouvees[code] = `Fichier trop volumineux (maximum ${a.taille_max_mo} Mo)`
      }
    }
    setErreurs(trouvees)
    if (Object.keys(trouvees).length > 0) return

    setEnvoi(true)
    setErreurEnvoi(null)
    try {
      await avisPublicApi.candidater(publicKey, {
        nom: nom.trim(),
        prenom: prenom.trim(),
        email: email.trim(),
        telephone: telephone.trim() || undefined,
        // Les exigées sont toutes présentes (validées ci-dessus) ; les
        // facultatives ne partent que si le candidat en a joint une.
        pieces: [...a.pieces_attendues, ...a.pieces_facultatives]
          .filter((p) => fichiers[p.code])
          .map((p) => ({ code: p.code, fichier: fichiers[p.code] })),
      })
      setTermine(true)
    } catch (caught) {
      setErreurEnvoi(caught instanceof Error ? caught.message : 'Une erreur est survenue')
    } finally {
      setEnvoi(false)
    }
  }

  return enveloppe(
    <div>
      <Link to="/careers" className="text-xs text-ink-500 hover:underline">
        ← Tous les postes ouverts
      </Link>

      <h1 className="mt-2 text-2xl font-semibold tracking-tight text-ink-900">{a.intitule}</h1>
      <p className="mt-1 text-sm text-ink-500">
        {a.departement ? `${a.departement} · ` : ''}
        {a.date_cloture ? `candidatures jusqu'au ${formatDate(a.date_cloture, 'fr')}` : ''}
      </p>

      {a.description && (
        <p className="mt-4 whitespace-pre-line text-sm text-ink-700">{a.description}</p>
      )}

      {a.missions.length > 0 && (
        <section className="mt-6">
          <h2 className="text-sm font-semibold text-ink-900">Missions</h2>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-700">
            {a.missions.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        </section>
      )}

      <section className="mt-6">
        <h2 className="text-sm font-semibold text-ink-900">Profil recherché</h2>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-700">
          {a.profil.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      </section>

      {!a.accepte_candidatures ? (
        <div className="mt-8">
          <Callout tone="warning">
            Cet avis n'accepte plus de candidatures. La date de clôture est passée.
          </Callout>
        </div>
      ) : (
        <form className="card mt-8 space-y-4 p-6" onSubmit={envoyer}>
          <h2 className="text-sm font-semibold text-ink-900">Votre dossier</h2>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Nom" htmlFor="nom" error={erreurs.nom}>
              <input
                id="nom"
                className="input"
                value={nom}
                onChange={(e) => setNom(e.target.value)}
                autoComplete="family-name"
              />
            </Field>
            <Field label="Prénom" htmlFor="prenom" error={erreurs.prenom}>
              <input
                id="prenom"
                className="input"
                value={prenom}
                onChange={(e) => setPrenom(e.target.value)}
                autoComplete="given-name"
              />
            </Field>
          </div>

          <Field label="Adresse email" htmlFor="email" error={erreurs.email}>
            <input
              id="email"
              type="email"
              className="input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
            />
          </Field>

          <Field label="Téléphone (facultatif)" htmlFor="tel">
            <input
              id="tel"
              className="input"
              value={telephone}
              onChange={(e) => setTelephone(e.target.value)}
              autoComplete="tel"
            />
          </Field>

          <div className="space-y-3 border-t border-ink-100 pt-4">
            <p className="text-sm font-medium text-ink-800">
              Pièces à fournir ({a.formats_acceptes.join(' ou ')}, {a.taille_max_mo} Mo maximum
              par fichier)
            </p>
            {a.pieces_attendues.map((piece) => (
              <Field key={piece.code} label={piece.libelle} error={erreurs[piece.code]}>
                <input
                  type="file"
                  accept=".pdf,.docx,.doc"
                  className="input"
                  onChange={(e) => {
                    const fichier = e.target.files?.[0]
                    setFichiers((actuels) =>
                      fichier
                        ? { ...actuels, [piece.code]: fichier }
                        : Object.fromEntries(
                            Object.entries(actuels).filter(([c]) => c !== piece.code),
                          ),
                    )
                  }}
                />
              </Field>
            ))}
            {a.pieces_attendues.length === 0 && (
              <p className="text-sm text-ink-500">Aucune pièce n'est exigée pour cet avis.</p>
            )}

            {a.pieces_facultatives.length > 0 && (
              <div className="space-y-3 border-t border-ink-100 pt-3">
                <p className="text-sm font-medium text-ink-800">
                  Pièces facultatives
                  <span className="ml-1 font-normal text-ink-500">
                    — leur absence ne pénalise pas votre dossier
                  </span>
                </p>
                {a.pieces_facultatives.map((piece) => (
                  <Field key={piece.code} label={piece.libelle}>
                    <input
                      type="file"
                      accept=".pdf,.docx,.doc"
                      className="input"
                      onChange={(e) => {
                        const fichier = e.target.files?.[0]
                        setFichiers((actuels) =>
                          fichier
                            ? { ...actuels, [piece.code]: fichier }
                            : Object.fromEntries(
                                Object.entries(actuels).filter(([c]) => c !== piece.code),
                              ),
                        )
                      }}
                    />
                  </Field>
                ))}
              </div>
            )}
          </div>

          {erreurEnvoi && <Callout tone="danger">{erreurEnvoi}</Callout>}

          <button type="submit" className="btn-primary w-full" disabled={envoi}>
            {envoi && <Spinner />}
            {envoi ? 'Envoi en cours…' : 'Envoyer ma candidature'}
          </button>

          <p className="text-xs text-ink-500">
            Les informations transmises servent uniquement à l'examen de votre candidature.
          </p>
        </form>
      )}
    </div>,
  )
}
