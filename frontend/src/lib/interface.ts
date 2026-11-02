import { useQuery } from '@tanstack/react-query'
import { settingsApi } from '@/lib/api'

/**
 * L'interface d'avant la refonte de la revue et de la boîte est-elle demandée ?
 *
 * Réglée dans Paramètres › Général. Tant que les réglages se chargent, la
 * nouvelle interface s'affiche : c'est la valeur par défaut.
 */
export function useInterfaceClassique(): boolean {
  const reglages = useQuery({ queryKey: ['settings'], queryFn: settingsApi.get, staleTime: 60_000 })
  return Boolean(reglages.data?.interface_classique)
}

/**
 * Les messageries publiques : la plupart des candidats y ont leur adresse.
 * Leur domaine entier ne s'ignore ni ne se sélectionne d'un coup — seulement
 * une adresse précise. Même liste que le serveur, qui refuse de toute façon.
 */
const DOMAINES_PUBLICS = new Set([
  '@gmail.com', '@googlemail.com', '@yahoo.com', '@yahoo.fr', '@ymail.com',
  '@outlook.com', '@outlook.fr', '@hotmail.com', '@hotmail.fr', '@live.com',
  '@live.fr', '@msn.com', '@icloud.com', '@me.com', '@aol.com', '@gmx.com',
  '@gmx.fr', '@proton.me', '@protonmail.com', '@orange.fr', '@free.fr',
  '@laposte.net', '@yandex.com', '@mail.com', '@zoho.com',
])

export function estDomainePublic(domaine: string | null | undefined): boolean {
  return DOMAINES_PUBLICS.has((domaine ?? '').trim().toLowerCase())
}

/** Libellés lisibles de la provenance d'un dossier. */
export const LIBELLE_SOURCE: Record<string, string> = {
  EMAIL: 'reçu par courriel',
  FORMULAIRE: 'déposé sur le site',
  IMPORT_MANUEL: 'déposé par les RH',
}
