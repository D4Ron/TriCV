import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { collaborationApi, type EtapeMandat } from '@/lib/api'
import { Callout, CopyField, Field, Spinner, Toggle } from '@/components/ui'
import { formatDate } from '@/lib/format'

/**
 * L'espace du promoteur, côté cabinet.
 *
 * Trois choses s'y règlent : à qui l'accès est ouvert, ce que le client voit
 * de l'avancement, et le fil des échanges.
 *
 * Le lien d'activation n'apparaît qu'une fois, à l'ouverture. Il n'est jamais
 * relu depuis la base : l'afficher dans la liste ferait de cet écran une
 * distribution de clés. S'il faut le retransmettre, on rouvre l'accès — ce qui
 * en produit un nouveau et invalide l'ancien.
 */

const ETATS: Array<{ valeur: EtapeMandat['etat']; libelle: string }> = [
  { valeur: 'A_VENIR', libelle: 'À venir' },
  { valeur: 'EN_COURS', libelle: 'En cours' },
  { valeur: 'TERMINEE', libelle: 'Terminée' },
]

function Acces({ mandatId }: { mandatId: string }) {
  const queryClient = useQueryClient()
  const acces = useQuery({
    queryKey: ['acces-client', mandatId],
    queryFn: () => collaborationApi.acces(mandatId),
  })

  const [ouvert, setOuvert] = useState(false)
  const [email, setEmail] = useState('')
  const [nom, setNom] = useState('')
  const [fonction, setFonction] = useState('')
  const [parCourriel, setParCourriel] = useState(true)
  const [erreur, setErreur] = useState<string | null>(null)
  const [invitation, setInvitation] = useState<{
    lien: string | null
    envoye: boolean
    avertissement: string | null
  } | null>(null)

  const ouvrir = useMutation({
    mutationFn: () =>
      collaborationApi.ouvrirAcces(mandatId, {
        email: email.trim(),
        nom: nom.trim(),
        fonction: fonction.trim() || undefined,
        envoyer_courriel: parCourriel,
      }),
    onSuccess: (a) => {
      setErreur(null)
      setInvitation({
        lien: a.lien_activation ?? null,
        envoye: Boolean(a.courriel_envoye),
        avertissement: a.avertissement ?? null,
      })
      setOuvert(false)
      setEmail('')
      setNom('')
      setFonction('')
      void queryClient.invalidateQueries({ queryKey: ['acces-client', mandatId] })
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Ouverture impossible'),
  })

  const revoquer = useMutation({
    mutationFn: (id: string) => collaborationApi.revoquerAcces(id, 'Révoqué depuis le mandat'),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['acces-client', mandatId] })
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Révocation impossible'),
  })

  return (
    <section className="card p-5">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-sm font-semibold text-ink-900">Accès du promoteur</h2>
        <button
          type="button"
          className="btn-ghost ml-auto px-3 py-1.5 text-xs"
          onClick={() => setOuvert((o) => !o)}
        >
          {ouvert ? 'Annuler' : 'Ouvrir un accès'}
        </button>
      </div>
      <p className="mt-1 text-xs text-ink-500">
        L&apos;espace vit le temps du mandat : le clore ou l&apos;archiver ferme tous les accès.
        Le destinataire choisit son mot de passe lui-même.
      </p>

      {invitation && (
        <div className="mt-4 space-y-2">
          {invitation.envoye ? (
            <Callout tone="success">
              Le lien d&apos;activation a été envoyé. Il est valable quatorze jours et ne sert
              qu&apos;une fois.
            </Callout>
          ) : (
            invitation.avertissement && <Callout tone="warning">{invitation.avertissement}</Callout>
          )}
          {invitation.lien && (
            <CopyField value={invitation.lien} label="Lien d'activation (affiché une seule fois)" />
          )}
        </div>
      )}

      {ouvert && (
        <form
          className="mt-4 space-y-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (!email.trim() || !nom.trim()) return
            ouvrir.mutate()
          }}
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Nom du contact" htmlFor="ac-nom">
              <input
                id="ac-nom"
                className="input"
                value={nom}
                onChange={(e) => setNom(e.target.value)}
              />
            </Field>
            <Field label="Adresse email" htmlFor="ac-email">
              <input
                id="ac-email"
                type="email"
                className="input"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </Field>
          </div>
          <Field label="Fonction (facultatif)" htmlFor="ac-fonction">
            <input
              id="ac-fonction"
              className="input"
              value={fonction}
              placeholder="Directeur des ressources humaines"
              onChange={(e) => setFonction(e.target.value)}
            />
          </Field>
          <Toggle
            checked={parCourriel}
            onChange={setParCourriel}
            label="Envoyer le lien par courriel"
            hint="Décoché, le lien s'affiche ici pour être transmis autrement."
          />
          <button
            type="submit"
            className="btn-primary"
            disabled={ouvrir.isPending || !email.trim() || !nom.trim()}
          >
            {ouvrir.isPending && <Spinner />}
            Ouvrir l&apos;accès
          </button>
        </form>
      )}

      {erreur && (
        <div className="mt-3">
          <Callout tone="danger">{erreur}</Callout>
        </div>
      )}

      {acces.data && acces.data.length > 0 && (
        <ul className="mt-4 space-y-2">
          {acces.data.map((a) => (
            <li key={a.id} className="flex flex-wrap items-center gap-2 rounded-lg bg-ink-50 px-3 py-2">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-ink-900">{a.nom}</p>
                <p className="truncate text-xs text-ink-500">
                  {a.email}
                  {a.fonction ? ` · ${a.fonction}` : ''}
                </p>
              </div>
              {a.revoque_le ? (
                <span className="badge bg-ink-100 text-ink-600">Fermé</span>
              ) : a.active_le ? (
                <span className="badge bg-emerald-100 text-emerald-800">
                  Actif
                  {a.dernier_acces_le ? ` · vu le ${formatDate(a.dernier_acces_le, 'fr')}` : ''}
                </span>
              ) : (
                // « Invitation envoyée » serait faux quand l'envoi n'est pas
                // configuré : l'accès existe et attend, c'est tout ce qu'on
                // sait depuis la liste.
                <span className="badge bg-amber-100 text-amber-800">Pas encore activé</span>
              )}
              {!a.revoque_le && (
                <button
                  type="button"
                  className="text-xs text-red-700 hover:underline"
                  disabled={revoquer.isPending}
                  onClick={() => revoquer.mutate(a.id)}
                >
                  Fermer
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function Chronogramme({ mandatId }: { mandatId: string }) {
  const queryClient = useQueryClient()
  const chronogramme = useQuery({
    queryKey: ['chronogramme', mandatId],
    queryFn: () => collaborationApi.chronogramme(mandatId),
  })

  const [etapes, setEtapes] = useState<EtapeMandat[]>([])
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    if (chronogramme.data) setEtapes(chronogramme.data)
  }, [chronogramme.data])

  const enregistrer = useMutation({
    mutationFn: () => collaborationApi.ecrireChronogramme(mandatId, etapes),
    onSuccess: () => {
      setMessage('Chronogramme enregistré.')
      void queryClient.invalidateQueries({ queryKey: ['chronogramme', mandatId] })
    },
  })

  const modifier = (index: number, champ: Partial<EtapeMandat>) =>
    setEtapes((tous) => tous.map((e, i) => (i === index ? { ...e, ...champ } : e)))

  return (
    <section className="card p-5">
      <h2 className="text-sm font-semibold text-ink-900">Chronogramme</h2>
      <p className="mt-1 text-xs text-ink-500">
        Ce que le promoteur voit de l&apos;avancement. Volontairement grossier : il doit savoir où
        en est son recrutement, pas combien de dossiers ont été écartés ni sur quels critères.
      </p>

      <div className="mt-4 space-y-2">
        {etapes.map((etape, index) => (
          <div key={index} className="grid gap-2 rounded-lg bg-ink-50 p-3 sm:grid-cols-[1fr_auto_auto_auto]">
            <input
              className="input py-1 text-sm"
              value={etape.libelle}
              aria-label={`Étape ${index + 1}`}
              onChange={(e) => modifier(index, { libelle: e.target.value })}
            />
            <select
              className="input py-1 text-sm"
              value={etape.etat}
              aria-label={`État — ${etape.libelle}`}
              onChange={(e) => modifier(index, { etat: e.target.value as EtapeMandat['etat'] })}
            >
              {ETATS.map((e) => (
                <option key={e.valeur} value={e.valeur}>
                  {e.libelle}
                </option>
              ))}
            </select>
            <input
              type="date"
              className="input py-1 text-sm"
              value={etape.date_prevue ?? ''}
              aria-label={`Date prévue — ${etape.libelle}`}
              onChange={(e) => modifier(index, { date_prevue: e.target.value || null })}
            />
            <div className="flex items-center gap-2">
              <label className="flex items-center gap-1 text-xs text-ink-600">
                <input
                  type="checkbox"
                  checked={etape.visible_client}
                  onChange={(e) => modifier(index, { visible_client: e.target.checked })}
                />
                Visible
              </label>
              <button
                type="button"
                className="text-xs text-red-700 hover:underline"
                onClick={() => setEtapes((tous) => tous.filter((_, i) => i !== index))}
                aria-label={`Retirer ${etape.libelle}`}
              >
                ×
              </button>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          className="btn-ghost px-3 py-1.5 text-xs"
          onClick={() =>
            setEtapes((tous) => [
              ...tous,
              {
                libelle: '',
                etat: 'A_VENIR',
                date_prevue: null,
                date_reelle: null,
                visible_client: true,
              },
            ])
          }
        >
          + Ajouter une étape
        </button>
        <button
          type="button"
          className="btn-ghost px-3 py-1.5 text-xs"
          disabled={enregistrer.isPending || etapes.some((e) => !e.libelle.trim())}
          onClick={() => enregistrer.mutate()}
        >
          {enregistrer.isPending && <Spinner />}
          Enregistrer
        </button>
        {message && <span className="self-center text-xs text-emerald-700">{message}</span>}
      </div>
    </section>
  )
}

function Echanges({ mandatId }: { mandatId: string }) {
  const queryClient = useQueryClient()
  const echanges = useQuery({
    queryKey: ['echanges', mandatId],
    queryFn: () => collaborationApi.echanges(mandatId),
  })

  const [objet, setObjet] = useState('')
  const [corps, setCorps] = useState('')
  const [erreur, setErreur] = useState<string | null>(null)

  const ecrire = useMutation({
    mutationFn: () =>
      collaborationApi.ecrireAuClient(mandatId, {
        corps: corps.trim(),
        objet: objet.trim() || undefined,
      }),
    onSuccess: () => {
      setObjet('')
      setCorps('')
      setErreur(null)
      void queryClient.invalidateQueries({ queryKey: ['echanges', mandatId] })
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Envoi impossible'),
  })

  const traiter = useMutation({
    mutationFn: (id: string) => collaborationApi.marquerTraite(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['echanges', mandatId] })
    },
  })

  const enAttente = (echanges.data ?? []).filter(
    (e) => e.type_echange === 'DEMANDE_MODIFICATION' && !e.traite_le,
  ).length

  return (
    <section className="card p-5">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-sm font-semibold text-ink-900">Échanges avec le promoteur</h2>
        {enAttente > 0 && (
          <span className="badge bg-amber-100 text-amber-800">
            {enAttente} demande{enAttente > 1 ? 's' : ''} en attente
          </span>
        )}
      </div>
      <p className="mt-1 text-xs text-ink-500">
        Le fil vit à côté du dossier qu&apos;il concerne. Une demande de modification s&apos;y
        distingue d&apos;un message : elle se clôt par un changement effectif, pas par une réponse
        polie.
      </p>

      <form
        className="mt-4 space-y-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (!corps.trim()) return
          ecrire.mutate()
        }}
      >
        <input
          className="input py-1.5 text-sm"
          value={objet}
          placeholder="Objet (facultatif)"
          aria-label="Objet du message"
          onChange={(e) => setObjet(e.target.value)}
        />
        <textarea
          className="input text-sm"
          rows={3}
          value={corps}
          placeholder="Votre message au promoteur…"
          aria-label="Message au promoteur"
          onChange={(e) => setCorps(e.target.value)}
        />
        {erreur && <Callout tone="danger">{erreur}</Callout>}
        <button
          type="submit"
          className="btn-ghost px-3 py-1.5 text-xs"
          disabled={ecrire.isPending || !corps.trim()}
        >
          {ecrire.isPending && <Spinner />}
          Envoyer
        </button>
      </form>

      {echanges.data && echanges.data.length > 0 && (
        <div className="mt-4 space-y-2">
          {echanges.data.map((echange) => (
            <article
              key={echange.id}
              className={`rounded-lg px-3 py-2 ${
                echange.auteur === 'CLIENT' ? 'bg-brand-50' : 'bg-ink-50'
              }`}
            >
              <div className="flex flex-wrap items-baseline gap-2 text-xs text-ink-500">
                <span className="font-medium text-ink-800">{echange.auteur_nom}</span>
                <span>{formatDate(echange.envoye_le, 'fr')}</span>
                {echange.type_echange === 'DEMANDE_MODIFICATION' && (
                  <span
                    className={`badge ${
                      echange.traite_le
                        ? 'bg-emerald-100 text-emerald-800'
                        : 'bg-amber-100 text-amber-800'
                    }`}
                  >
                    {echange.traite_le ? 'Traitée' : 'Demande de modification'}
                  </span>
                )}
                {echange.type_echange === 'DEMANDE_MODIFICATION' && !echange.traite_le && (
                  <button
                    type="button"
                    className="ml-auto text-xs text-brand-700 hover:underline"
                    disabled={traiter.isPending}
                    onClick={() => traiter.mutate(echange.id)}
                  >
                    Marquer traitée
                  </button>
                )}
              </div>
              {echange.objet && (
                <p className="mt-1 text-sm font-medium text-ink-900">{echange.objet}</p>
              )}
              <p className="mt-0.5 whitespace-pre-line text-sm text-ink-700">{echange.corps}</p>
            </article>
          ))}
        </div>
      )}
    </section>
  )
}

export default function PanneauEspaceClient({ mandatId }: { mandatId: string }) {
  return (
    <div className="space-y-4">
      <Acces mandatId={mandatId} />
      <Chronogramme mandatId={mandatId} />
      <Echanges mandatId={mandatId} />
    </div>
  )
}
