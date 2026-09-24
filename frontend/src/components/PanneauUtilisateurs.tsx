import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { utilisateursApi } from '@/lib/api'
import { useAuthStore } from '@/store/auth'
import { Callout, ErrorState, Field, Modal, PageLoader, Spinner } from '@/components/ui'
import { formatDate } from '@/lib/format'
import type { User } from '@/types'

/**
 * Les comptes du cabinet.
 *
 * L'API de gestion existait ; aucun écran ne l'atteignait. Pour ajouter un
 * collègue, il fallait donc ouvrir « Autoriser la création de compte » — qui
 * ouvre l'inscription à tout internaute tombé sur l'adresse — puis penser à la
 * refermer. Personne ne pense à la refermer.
 *
 * Deux principes tiennent cet écran :
 *
 * Un compte ne se supprime pas. Son nom figure au journal d'audit sur chaque
 * décision qu'il a prise ; l'effacer rendrait ces décisions anonymes. Le
 * désactiver ferme l'accès et garde la trace.
 *
 * Le mot de passe est choisi par l'administrateur et transmis par lui, de vive
 * voix ou par un canal qu'il juge sûr. L'application ne l'envoie pas, ne le
 * réaffiche pas, et ne le journalise pas — seul le fait qu'il a changé, et par
 * qui, est consigné.
 */

const LIBELLE_ROLE: Record<string, string> = {
  ADMIN: 'Administrateur',
  RECRUITER: 'Chargé de recrutement',
}

const AIDE_ROLE: Record<string, string> = {
  ADMIN: 'Accède à tout, gère les comptes et les paramètres du cabinet.',
  RECRUITER: 'Accède aux mandats, aux dossiers et aux notes. Ni comptes ni paramètres.',
}

export default function PanneauUtilisateurs() {
  const queryClient = useQueryClient()
  const moi = useAuthStore((state) => state.user)
  const [creation, setCreation] = useState(false)
  const [motDePasseDe, setMotDePasseDe] = useState<User | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const comptes = useQuery({ queryKey: ['utilisateurs'], queryFn: utilisateursApi.lister })

  const rafraichir = () => {
    void queryClient.invalidateQueries({ queryKey: ['utilisateurs'] })
  }

  const modifier = useMutation({
    mutationFn: ({ id, ...payload }: { id: string; role?: 'ADMIN' | 'RECRUITER'; is_active?: boolean }) =>
      utilisateursApi.modifier(id, payload),
    onSuccess: (u) => {
      setErreur(null)
      setMessage(
        u.is_active
          ? `${u.full_name || u.email} — ${LIBELLE_ROLE[u.role].toLowerCase()}.`
          : `${u.full_name || u.email} n’a plus accès. Ses décisions passées restent au journal.`,
      )
      rafraichir()
    },
    onError: (e) => {
      setMessage(null)
      setErreur(e instanceof Error ? e.message : 'Modification impossible')
    },
  })

  if (comptes.isLoading) return <PageLoader />
  if (comptes.isError)
    return <ErrorState error={comptes.error} onRetry={() => comptes.refetch()} />

  const liste = comptes.data ?? []
  const admins = liste.filter((u) => u.role === 'ADMIN' && u.is_active).length

  return (
    <section className="card p-5">
      <div className="flex flex-wrap items-center gap-2">
        <div>
          <h2 className="text-sm font-semibold text-ink-900">Comptes</h2>
          <p className="mt-1 text-xs text-ink-500">
            Un compte donne accès aux dossiers de tous les candidats. Ajoutez les personnes une
            à une plutôt que d’ouvrir l’inscription libre, qui vaut pour n’importe qui.
          </p>
        </div>
        <button
          type="button"
          className="btn-primary ml-auto px-3 py-1.5 text-xs"
          onClick={() => setCreation(true)}
        >
          Ajouter un compte
        </button>
      </div>

      {erreur && (
        <div className="mt-4">
          <Callout tone="danger">{erreur}</Callout>
        </div>
      )}
      {message && (
        <div className="mt-4">
          <Callout tone="success">{message}</Callout>
        </div>
      )}

      <div className="mt-4 divide-y divide-ink-100">
        {liste.map((u) => {
          const cestMoi = u.id === moi?.id
          // Retirer le dernier administrateur actif fermerait la gestion des
          // comptes à tout le monde : le serveur le refuse, l'écran le grise.
          const dernierAdmin = u.role === 'ADMIN' && u.is_active && admins <= 1
          return (
            <div key={u.id} className="flex flex-wrap items-center gap-3 py-3">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-ink-900">
                  {u.full_name || u.email}
                  {cestMoi && <span className="ml-2 text-xs text-ink-400">(vous)</span>}
                  {!u.is_active && (
                    <span className="badge ml-2 bg-ink-100 text-ink-500">désactivé</span>
                  )}
                </p>
                <p className="truncate text-xs text-ink-500">
                  {u.email} · compte ouvert le {formatDate(u.created_at, 'fr')}
                </p>
              </div>

              <select
                className="input w-auto py-1 text-xs"
                value={u.role}
                aria-label={`Rôle de ${u.full_name || u.email}`}
                disabled={modifier.isPending || cestMoi || dernierAdmin}
                title={
                  cestMoi
                    ? 'Vos propres droits se changent depuis un autre compte administrateur.'
                    : dernierAdmin
                      ? 'Dernier administrateur actif : le retirer fermerait la gestion des comptes.'
                      : AIDE_ROLE[u.role]
                }
                onChange={(e) =>
                  modifier.mutate({ id: u.id, role: e.target.value as 'ADMIN' | 'RECRUITER' })
                }
              >
                {Object.entries(LIBELLE_ROLE).map(([valeur, libelle]) => (
                  <option key={valeur} value={valeur}>
                    {libelle}
                  </option>
                ))}
              </select>

              <button
                type="button"
                className="btn-ghost px-2 py-1 text-xs"
                onClick={() => setMotDePasseDe(u)}
              >
                Mot de passe
              </button>

              <button
                type="button"
                className={`btn-ghost px-2 py-1 text-xs ${u.is_active ? 'text-red-700' : ''}`}
                disabled={modifier.isPending || cestMoi || dernierAdmin}
                title={
                  cestMoi
                    ? 'Vous ne pouvez pas désactiver votre propre compte.'
                    : dernierAdmin
                      ? 'Dernier administrateur actif.'
                      : undefined
                }
                onClick={() => modifier.mutate({ id: u.id, is_active: !u.is_active })}
              >
                {u.is_active ? 'Désactiver' : 'Réactiver'}
              </button>
            </div>
          )
        })}
      </div>

      {creation && (
        <FenetreCreation
          onClose={() => setCreation(false)}
          onCree={(nom) => {
            setErreur(null)
            setMessage(
              `Compte créé pour ${nom}. Communiquez-lui son mot de passe vous-même : ` +
                'l’application ne le lui envoie pas.',
            )
            rafraichir()
          }}
        />
      )}

      {motDePasseDe && (
        <FenetreMotDePasse
          compte={motDePasseDe}
          onClose={() => setMotDePasseDe(null)}
          onChange={() => {
            setErreur(null)
            setMessage(
              `Mot de passe changé pour ${motDePasseDe.full_name || motDePasseDe.email}. ` +
                'Transmettez-le-lui : il n’est ni envoyé ni réaffiché.',
            )
          }}
        />
      )}
    </section>
  )
}

function FenetreCreation({
  onClose,
  onCree,
}: {
  onClose: () => void
  onCree: (nom: string) => void
}) {
  const [nom, setNom] = useState('')
  const [email, setEmail] = useState('')
  const [motDePasse, setMotDePasse] = useState('')
  const [role, setRole] = useState<'ADMIN' | 'RECRUITER'>('RECRUITER')
  const [erreur, setErreur] = useState<string | null>(null)

  const creer = useMutation({
    mutationFn: () =>
      utilisateursApi.creer({
        email: email.trim().toLowerCase(),
        password: motDePasse,
        full_name: nom.trim(),
        role,
      }),
    onSuccess: () => {
      onCree(nom.trim() || email.trim())
      onClose()
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Création impossible'),
  })

  const complet = nom.trim() && email.trim() && motDePasse.length >= 8

  return (
    <Modal open title="Nouveau compte" onClose={onClose}>
      <div className="space-y-4">
        {erreur && <Callout tone="danger">{erreur}</Callout>}

        <Field label="Nom et prénom" htmlFor="compte-nom">
          <input
            id="compte-nom"
            className="input"
            value={nom}
            autoFocus
            onChange={(e) => setNom(e.target.value)}
          />
        </Field>

        <Field
          label="Adresse email"
          htmlFor="compte-email"
          hint="Elle sert d’identifiant. Elle ne peut plus être changée ensuite."
        >
          <input
            id="compte-email"
            type="email"
            className="input"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </Field>

        <Field
          label="Mot de passe initial"
          htmlFor="compte-mdp"
          hint="Huit caractères au moins. Choisissez-le et transmettez-le vous-même : l’application ne l’envoie pas et ne le réaffichera jamais."
        >
          <input
            id="compte-mdp"
            type="password"
            className="input"
            value={motDePasse}
            autoComplete="new-password"
            onChange={(e) => setMotDePasse(e.target.value)}
          />
        </Field>

        <Field label="Rôle" htmlFor="compte-role" hint={AIDE_ROLE[role]}>
          <select
            id="compte-role"
            className="input"
            value={role}
            onChange={(e) => setRole(e.target.value as 'ADMIN' | 'RECRUITER')}
          >
            {Object.entries(LIBELLE_ROLE).map(([valeur, libelle]) => (
              <option key={valeur} value={valeur}>
                {libelle}
              </option>
            ))}
          </select>
        </Field>

        <div className="flex gap-2">
          <button
            type="button"
            className="btn-primary"
            disabled={!complet || creer.isPending}
            onClick={() => creer.mutate()}
          >
            {creer.isPending && <Spinner />}
            Créer le compte
          </button>
          <button type="button" className="btn-ghost" onClick={onClose}>
            Annuler
          </button>
        </div>
      </div>
    </Modal>
  )
}

function FenetreMotDePasse({
  compte,
  onClose,
  onChange,
}: {
  compte: User
  onClose: () => void
  onChange: () => void
}) {
  const [motDePasse, setMotDePasse] = useState('')
  const [erreur, setErreur] = useState<string | null>(null)

  const changer = useMutation({
    mutationFn: () => utilisateursApi.motDePasse(compte.id, motDePasse),
    onSuccess: () => {
      onChange()
      onClose()
    },
    onError: (e) => setErreur(e instanceof Error ? e.message : 'Changement impossible'),
  })

  return (
    <Modal open title={`Mot de passe — ${compte.full_name || compte.email}`} onClose={onClose}>
      <div className="space-y-4">
        {erreur && <Callout tone="danger">{erreur}</Callout>}

        <Callout tone="info">
          Le nouveau mot de passe remplace immédiatement l’ancien. Il n’est envoyé à personne :
          c’est à vous de le transmettre, et à l’intéressé de le changer ensuite.
        </Callout>

        <Field label="Nouveau mot de passe" htmlFor="compte-nouveau-mdp" hint="Huit caractères au moins.">
          <input
            id="compte-nouveau-mdp"
            type="password"
            className="input"
            value={motDePasse}
            autoComplete="new-password"
            autoFocus
            onChange={(e) => setMotDePasse(e.target.value)}
          />
        </Field>

        <div className="flex gap-2">
          <button
            type="button"
            className="btn-primary"
            disabled={motDePasse.length < 8 || changer.isPending}
            onClick={() => changer.mutate()}
          >
            {changer.isPending && <Spinner />}
            Changer le mot de passe
          </button>
          <button type="button" className="btn-ghost" onClick={onClose}>
            Annuler
          </button>
        </div>
      </div>
    </Modal>
  )
}
