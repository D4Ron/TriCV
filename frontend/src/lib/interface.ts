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

/** Libellés lisibles de la provenance d'un dossier. */
export const LIBELLE_SOURCE: Record<string, string> = {
  EMAIL: 'reçu par courriel',
  FORMULAIRE: 'déposé sur le site',
  IMPORT_MANUEL: 'déposé par les RH',
}
