import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { avisPublicApi } from '@/lib/api'
import { LogoKapi, Marque } from '@/components/Marque'
import { Callout, Field, PageLoader, Spinner } from '@/components/ui'
import { formatDate } from '@/lib/format'
import SaisieParcoursDeclare, {
  PARCOURS_VIDE,
  parcoursRempli,
  versParcours,
  type SaisieParcours,
} from '@/components/ParcoursDeclare'

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
  const [adresse, setAdresse] = useState('')
  // État civil déclaré. La date de naissance et la nationalité décident de
  // deux conditions éliminatoires : sans elles, ces conditions ne
  // s'appliquaient qu'aux dossiers déjà dépouillés — donc pas à tous.
  const [dateNaissance, setDateNaissance] = useState('')
  const [sexe, setSexe] = useState('')
  const [nationalites, setNationalites] = useState('')
  const [parcours, setParcours] = useState<SaisieParcours>(PARCOURS_VIDE)
  const [fichiers, setFichiers] = useState<Record<string, File>>({})
  // Ce que le candidat a choisi dans un groupe « l'une ou l'autre » : la CNI
  // ou le passeport. On mémorise son choix pour n'afficher qu'un champ.
  const [choixGroupe, setChoixGroupe] = useState<Record<number, string>>({})
  // Les documents que le candidat juge utiles et que l'avis n'a pas prévus :
  // une lettre de recommandation, une attestation. Il les nomme lui-même.
  const [libres, setLibres] = useState<Array<{ intitule: string; fichier: File | null }>>([])
  const [erreurs, setErreurs] = useState<Record<string, string>>({})
  const [erreurEnvoi, setErreurEnvoi] = useState<string | null>(null)
  const [envoi, setEnvoi] = useState(false)
  const [termine, setTermine] = useState(false)

  const enveloppe = (contenu: React.ReactNode) => (
    <div className="min-h-screen bg-ink-50">
      <div className="h-1 bg-gradient-to-r from-or-500 via-or-400 to-or-500" />
      <header className="border-b border-ink-200 bg-white">
        <div className="mx-auto flex h-16 max-w-3xl items-center px-4">
          <Marque sousTitre="Recrutement" />
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-4 py-10">{contenu}</main>
      {/* Le candidat dépose des pièces personnelles : il doit voir sans
          chercher à qui il les confie. */}
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
    // Les groupes : « la CNI ou le passeport » se satisfait d'une seule pièce,
    // « le diplôme et son attestation » les exige toutes.
    a.groupes_pieces.forEach((groupe, index) => {
      if (groupe.mode === 'AU_MOINS_UNE') {
        const choisi = choixGroupe[index]
        if (!choisi || !fichiers[choisi]) {
          trouvees[`groupe-${index}`] = 'Fournissez l’un de ces documents'
        }
      } else {
        for (const piece of groupe.pieces) {
          if (!fichiers[piece.code]) trouvees[piece.code] = 'Pièce obligatoire'
        }
      }
    })
    // Refuser ici évite un aller-retour et un message d'erreur générique.
    for (const [code, fichier] of Object.entries(fichiers)) {
      if (fichier.size > a.taille_max_mo * 1024 * 1024) {
        trouvees[code] = `Fichier trop volumineux (maximum ${a.taille_max_mo} Mo)`
      }
      const imposes = a.formats_pieces[code]
      if (imposes?.length) {
        const extension = fichier.name.split('.').pop()?.toLowerCase() ?? ''
        if (!imposes.map((f) => f.toLowerCase()).includes(extension)) {
          trouvees[code] = `Ce document doit être fourni au format ${imposes
            .join(' ou ')
            .toUpperCase()}`
        }
      }
    }
    libres.forEach((libre, index) => {
      if (libre.fichier && !libre.intitule.trim()) {
        trouvees[`libre-${index}`] = 'Nommez ce document'
      }
      if (libre.fichier && libre.fichier.size > a.taille_max_mo * 1024 * 1024) {
        trouvees[`libre-${index}`] = `Fichier trop volumineux (maximum ${a.taille_max_mo} Mo)`
      }
    })
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
        adresse: adresse.trim() || undefined,
        date_naissance: dateNaissance || undefined,
        sexe: sexe || undefined,
        nationalites: nationalites.trim() || undefined,
        // Un parcours vide ne part pas : il n'y a rien à déclarer.
        parcours: parcoursRempli(parcours) ? versParcours(parcours) : undefined,
        // Les exigées sont toutes présentes (validées ci-dessus) ; les
        // facultatives et celles des groupes ne partent que si le candidat en
        // a joint une.
        pieces: [
          ...[
            ...a.pieces_attendues,
            ...a.pieces_facultatives,
            ...a.groupes_pieces.flatMap((g) => g.pieces),
          ]
            .filter((p) => fichiers[p.code])
            // Un même code peut figurer dans deux listes ; ne l'envoyer qu'une fois.
            .filter((p, i, tous) => tous.findIndex((x) => x.code === p.code) === i)
            .map((p) => ({ code: p.code, fichier: fichiers[p.code] })),
          ...libres
            .filter((l) => l.fichier)
            .map((l) => ({ code: 'AUTRE', fichier: l.fichier!, intitule: l.intitule.trim() })),
        ],
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

      {/* Les conditions éliminatoires, dites avant le dépôt. Le formulaire
          demande maintenant la date de naissance et la nationalité, et elles
          sont opposables dès l'enregistrement : laisser quelqu'un composer un
          dossier complet pour l'écarter ensuite sur un critère qu'il n'avait
          jamais vu serait le traiter avec désinvolture. */}
      {a.conditions.length > 0 && (
        <section className="mt-6">
          <h2 className="text-sm font-semibold text-ink-900">Conditions à remplir</h2>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-700">
            {a.conditions.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-ink-500">
            Ces conditions écartent un dossier qui ne les remplit pas.
            {a.justification_conditions
              ? ` Motif indiqué par le commanditaire : ${a.justification_conditions}`
              : ''}
          </p>
        </section>
      )}

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

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Téléphone" htmlFor="tel">
              <input
                id="tel"
                className="input"
                value={telephone}
                onChange={(e) => setTelephone(e.target.value)}
                autoComplete="tel"
              />
            </Field>
            <Field label="Adresse (facultatif)" htmlFor="adresse">
              <input
                id="adresse"
                className="input"
                value={adresse}
                onChange={(e) => setAdresse(e.target.value)}
                autoComplete="street-address"
              />
            </Field>
          </div>

          {/* L'état civil décide des conditions éliminatoires du poste. Il
              figure dans les pièces jointes, mais y accéder suppose de les
              avoir lues : tant que personne ne l'a fait, la condition ne
              s'applique à personne. */}
          <div className="grid gap-4 sm:grid-cols-3">
            <Field
              label="Date de naissance"
              htmlFor="naissance"
              error={erreurs.date_naissance}
            >
              <input
                id="naissance"
                type="date"
                className="input"
                value={dateNaissance}
                max={new Date().toISOString().slice(0, 10)}
                onChange={(e) => setDateNaissance(e.target.value)}
                autoComplete="bday"
              />
            </Field>
            <Field label="Nationalité(s)" htmlFor="nationalites">
              <input
                id="nationalites"
                className="input"
                value={nationalites}
                placeholder="togolaise"
                onChange={(e) => setNationalites(e.target.value)}
              />
            </Field>
            <Field label="Sexe (facultatif)" htmlFor="sexe">
              <select
                id="sexe"
                className="input"
                value={sexe}
                onChange={(e) => setSexe(e.target.value)}
              >
                <option value="">Ne pas préciser</option>
                <option value="M">Masculin</option>
                <option value="F">Féminin</option>
              </select>
            </Field>
          </div>

          <SaisieParcoursDeclare valeur={parcours} onChange={setParcours} erreurs={erreurs} />

          <div className="space-y-3 border-t border-ink-100 pt-4">
            <p className="text-sm font-medium text-ink-800">
              Pièces à fournir ({a.formats_acceptes.join(' ou ')}, {a.taille_max_mo} Mo maximum
              par fichier)
            </p>
            {a.pieces_attendues.map((piece) => (
              <Field
                key={piece.code}
                label={
                  a.formats_pieces[piece.code]?.length
                    ? `${piece.libelle} (${a.formats_pieces[piece.code]
                        .join(' ou ')
                        .toUpperCase()} exigé)`
                    : piece.libelle
                }
                error={erreurs[piece.code]}
              >
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
            {a.pieces_attendues.length === 0 && a.groupes_pieces.length === 0 && (
              <p className="text-sm text-ink-500">Aucune pièce n'est exigée pour cet avis.</p>
            )}

            {/* Un groupe « l'une ou l'autre » se présente comme un choix, pas
                comme deux exigences : demander les deux obligerait un candidat
                qui n'a qu'un passeport valide à refaire une carte d'identité. */}
            {a.groupes_pieces.map((groupe, index) =>
              groupe.mode === 'AU_MOINS_UNE' ? (
                <Field
                  key={`groupe-${index}`}
                  label={groupe.libelle || 'Au choix'}
                  error={erreurs[`groupe-${index}`]}
                >
                  <select
                    className="input"
                    value={choixGroupe[index] ?? ''}
                    aria-label={`Type de document — ${groupe.libelle || 'au choix'}`}
                    onChange={(e) => {
                      const code = e.target.value
                      setChoixGroupe((c) => ({ ...c, [index]: code }))
                      // Changer d'option retire le fichier déposé pour l'autre.
                      setFichiers((actuels) =>
                        Object.fromEntries(
                          Object.entries(actuels).filter(
                            ([c]) => !groupe.pieces.some((pc) => pc.code === c && pc.code !== code),
                          ),
                        ),
                      )
                    }}
                  >
                    <option value="">Choisissez un document…</option>
                    {groupe.pieces.map((piece) => (
                      <option key={piece.code} value={piece.code}>
                        {piece.libelle}
                      </option>
                    ))}
                  </select>
                  {choixGroupe[index] && (
                    <input
                      type="file"
                      accept=".pdf,.docx,.doc"
                      className="input mt-2"
                      aria-label={groupe.libelle || 'Document au choix'}
                      onChange={(e) => {
                        const fichier = e.target.files?.[0]
                        const code = choixGroupe[index]
                        setFichiers((actuels) =>
                          fichier
                            ? { ...actuels, [code]: fichier }
                            : Object.fromEntries(
                                Object.entries(actuels).filter(([c]) => c !== code),
                              ),
                        )
                      }}
                    />
                  )}
                </Field>
              ) : (
                <div key={`groupe-${index}`} className="space-y-3">
                  {groupe.libelle && (
                    <p className="text-sm font-medium text-ink-800">{groupe.libelle}</p>
                  )}
                  {groupe.pieces.map((piece) => (
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
                </div>
              ),
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

            {/* Le candidat peut joindre ce qu'il juge utile — une lettre de
                recommandation, une attestation — sans que l'avis ait eu à le
                prévoir. Il nomme le document lui-même. */}
            {a.pieces_libres_autorisees && (
              <div className="space-y-3 border-t border-ink-100 pt-3">
                <p className="text-sm font-medium text-ink-800">
                  Autres documents
                  <span className="ml-1 font-normal text-ink-500">
                    — tout ce que vous jugez utile : lettre de recommandation, attestation…
                  </span>
                </p>
                {libres.map((libre, index) => (
                  <div key={index} className="grid gap-2 sm:grid-cols-2">
                    <Field label="Intitulé" error={erreurs[`libre-${index}`]}>
                      <input
                        className="input"
                        value={libre.intitule}
                        placeholder="Lettre de recommandation…"
                        onChange={(e) =>
                          setLibres((tous) =>
                            tous.map((l, i) =>
                              i === index ? { ...l, intitule: e.target.value } : l,
                            ),
                          )
                        }
                      />
                    </Field>
                    <Field label="Fichier">
                      <input
                        type="file"
                        accept=".pdf,.docx,.doc"
                        className="input"
                        aria-label={`Fichier — document ${index + 1}`}
                        onChange={(e) =>
                          setLibres((tous) =>
                            tous.map((l, i) =>
                              i === index ? { ...l, fichier: e.target.files?.[0] ?? null } : l,
                            ),
                          )
                        }
                      />
                    </Field>
                  </div>
                ))}
                <button
                  type="button"
                  className="btn-ghost px-3 py-1.5 text-xs"
                  onClick={() => setLibres((tous) => [...tous, { intitule: '', fichier: null }])}
                >
                  + Ajouter un document
                </button>
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
