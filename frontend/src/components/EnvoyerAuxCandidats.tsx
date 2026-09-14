import { useEffect, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { collaborationApi, type MessagePrepare } from '@/lib/api'
import { Callout, Field, Modal, Spinner } from '@/components/ui'

/**
 * Écrire aux candidats depuis la grille.
 *
 * Deux temps, et l'ordre compte. **On rédige, on montre, puis on envoie.** Les
 * messages affichés ici sont exactement ceux qui partiront — pas un modèle qui
 * sera rerendu côté serveur au dernier moment. Un courriel ne se rattrape pas,
 * et un modèle correct dans le cas général reste faux sur un cas particulier ;
 * la relecture est le seul endroit où cela se voit.
 *
 * Les variables que le modèle ne peut pas deviner — date d'entretien, lieu,
 * signature — se remplissent en tête, et celles restées vides sont signalées
 * dossier par dossier plutôt que de partir en clair dans le message.
 */
export default function EnvoyerAuxCandidats({
  candidatureIds,
  onClose,
}: {
  candidatureIds: string[]
  onClose: () => void
}) {
  // Seulement ceux qui s'adressent à un candidat : proposer ici le message
  // d'accès du commanditaire livrerait à un candidat un lien vers l'espace de
  // suivi du mandat.
  const modeles = useQuery({
    queryKey: ['modeles-courriel', 'CANDIDAT'],
    queryFn: () => collaborationApi.modeles('CANDIDAT'),
  })

  const [modele, setModele] = useState('')
  const [valeurs, setValeurs] = useState<Record<string, string>>({})
  const [messages, setMessages] = useState<MessagePrepare[]>([])
  const [erreur, setErreur] = useState<string | null>(null)
  const [resultat, setResultat] = useState<{ envoyes: number; echecs: number } | null>(null)
  const [echecs, setEchecs] = useState<Array<{ candidature_id: string; erreur?: string }>>([])

  // Le premier modèle sert de point de départ : ouvrir sur une liste vide
  // obligerait à un clic avant de voir quoi que ce soit.
  useEffect(() => {
    if (!modele && modeles.data?.length) setModele(modeles.data[0].code)
  }, [modeles.data, modele])

  const choisi = modeles.data?.find((m) => m.code === modele)
  // Ce que le contexte du dossier ne fournit pas : à saisir une fois pour tous.
  const aRemplir = (choisi?.variables ?? []).filter(
    (v) =>
      ![
        'nom',
        'nom_famille',
        'prenom',
        'email',
        'poste',
        'client',
        'mandat',
        'reference',
        'pieces_manquantes',
        'date_du_jour',
      ].includes(v),
  )

  const preparer = useMutation({
    mutationFn: () => collaborationApi.apercu(modele, candidatureIds, valeurs),
    onSuccess: (r) => {
      setErreur(null)
      setMessages(r)
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Préparation impossible'),
  })

  const envoyer = useMutation({
    mutationFn: () =>
      collaborationApi.envoyer(
        modele,
        messages.map((m) => ({
          candidature_id: m.candidature_id,
          destinataire: m.destinataire,
          sujet: m.sujet,
          corps: m.corps,
        })),
      ),
    onSuccess: (r) => {
      setErreur(null)
      setResultat({ envoyes: r.envoyes, echecs: r.echecs })
      setEchecs(r.details.filter((d) => !d.ok))
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Envoi impossible'),
  })

  const sansAdresse = messages.filter((m) => !m.destinataire)
  const incomplets = messages.filter((m) => m.variables_manquantes.length > 0)

  return (
    <Modal open title={`Écrire à ${candidatureIds.length} candidat(s)`} onClose={onClose}>
      {resultat ? (
        <div className="space-y-4">
          {resultat.envoyes > 0 && (
            <Callout tone="success">
              {resultat.envoyes} message{resultat.envoyes > 1 ? 's' : ''} envoyé
              {resultat.envoyes > 1 ? 's' : ''}.
            </Callout>
          )}
          {resultat.echecs > 0 && (
            <Callout tone="danger" title={`${resultat.echecs} envoi(s) en échec`}>
              <ul className="mt-1 space-y-1">
                {echecs.map((e) => (
                  <li key={e.candidature_id}>
                    {messages.find((m) => m.candidature_id === e.candidature_id)?.nom ??
                      e.candidature_id}{' '}
                    — {e.erreur}
                  </li>
                ))}
              </ul>
            </Callout>
          )}
          <div className="flex justify-end">
            <button type="button" className="btn-primary" onClick={onClose}>
              Fermer
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <Field label="Modèle" htmlFor="modele-courriel" hint={choisi?.description}>
            <select
              id="modele-courriel"
              className="input"
              value={modele}
              onChange={(e) => {
                setModele(e.target.value)
                setMessages([])
              }}
            >
              {modeles.data?.map((m) => (
                <option key={m.code} value={m.code}>
                  {m.libelle}
                </option>
              ))}
            </select>
          </Field>

          {aRemplir.length > 0 && (
            <div className="grid gap-3 sm:grid-cols-2">
              {aRemplir.map((variable) => (
                <Field key={variable} label={variable.replace(/_/g, ' ')}>
                  <input
                    className="input py-1.5 text-sm"
                    value={valeurs[variable] ?? ''}
                    onChange={(e) =>
                      setValeurs((v) => ({ ...v, [variable]: e.target.value }))
                    }
                  />
                </Field>
              ))}
            </div>
          )}

          <button
            type="button"
            className="btn-ghost px-3 py-1.5 text-xs"
            disabled={preparer.isPending || !modele}
            onClick={() => preparer.mutate()}
          >
            {preparer.isPending && <Spinner />}
            {messages.length ? 'Recalculer les messages' : 'Préparer les messages'}
          </button>

          {sansAdresse.length > 0 && (
            <Callout tone="warning" title="Adresse manquante">
              {sansAdresse.map((m) => m.nom).join(', ')} — ces dossiers n&apos;ont pas
              d&apos;adresse électronique et ne recevront rien.
            </Callout>
          )}
          {incomplets.length > 0 && (
            <Callout tone="warning" title="Variables non remplies">
              Certains messages contiennent encore des repères entre accolades. Complétez les
              champs ci-dessus, ou corrigez le texte directement.
            </Callout>
          )}

          {messages.length > 0 && (
            <div className="max-h-80 space-y-3 overflow-y-auto rounded-lg border border-ink-200 p-3">
              {messages.map((message, index) => (
                <div key={message.candidature_id}>
                  <p className="text-xs font-medium text-ink-700">
                    {message.nom}
                    <span className="ml-1 font-normal text-ink-500">
                      {message.destinataire || '— sans adresse'}
                    </span>
                  </p>
                  <input
                    className="input mt-1 py-1 text-xs"
                    value={message.sujet}
                    aria-label={`Objet — ${message.nom}`}
                    onChange={(e) =>
                      setMessages((tous) =>
                        tous.map((m, i) => (i === index ? { ...m, sujet: e.target.value } : m)),
                      )
                    }
                  />
                  <textarea
                    className="input mt-1 text-xs"
                    rows={8}
                    value={message.corps}
                    aria-label={`Message — ${message.nom}`}
                    onChange={(e) =>
                      setMessages((tous) =>
                        tous.map((m, i) => (i === index ? { ...m, corps: e.target.value } : m)),
                      )
                    }
                  />
                </div>
              ))}
            </div>
          )}

          {erreur && <Callout tone="danger">{erreur}</Callout>}

          <div className="flex justify-end gap-2">
            <button type="button" className="btn-ghost" onClick={onClose}>
              Annuler
            </button>
            <button
              type="button"
              className="btn-primary"
              disabled={
                envoyer.isPending ||
                messages.length === 0 ||
                messages.every((m) => !m.destinataire)
              }
              onClick={() => envoyer.mutate()}
            >
              {envoyer.isPending && <Spinner />}
              Envoyer {messages.filter((m) => m.destinataire).length} message(s)
            </button>
          </div>
          <p className="text-xs text-ink-500">
            Ce qui part est exactement ce qui est affiché ci-dessus.
          </p>
        </div>
      )}
    </Modal>
  )
}
