import { useQuery } from '@tanstack/react-query'
import { settingsApi } from '@/lib/api'

/** Le compte rendu de « Relire les noms », en une phrase. */
export function resumeRelectureNoms(r: {
  examines: number
  corriges: Array<{ avant: string; apres: string }>
  a_verifier: Array<{ nom: string; motif: string }>
}): string {
  const parts: string[] = []
  if (r.corriges.length) {
    const exemples = r.corriges.slice(0, 3).map((c) => `${c.avant || '—'} → ${c.apres}`)
    parts.push(
      `${r.corriges.length} nom(s) corrigé(s) d'après le CV (${exemples.join(' ; ')}${r.corriges.length > 3 ? '…' : ''})`,
    )
  } else {
    parts.push(`Aucun nom à corriger sur ${r.examines} dossier(s) non confirmé(s)`)
  }
  if (r.a_verifier.length)
    parts.push(
      `${r.a_verifier.length} à vérifier, le CV porte un autre nom : ${r.a_verifier
        .slice(0, 3)
        .map((v) => v.nom)
        .join(', ')}`,
    )
  return parts.join('. ') + '.'
}

/** Le compte rendu de « Fusionner les doublons ». */
export function resumeFusion(r: { fusionnes: string[]; a_trancher: string[] }): string {
  const parts = [
    r.fusionnes.length
      ? `${r.fusionnes.length} doublon(s) versé(s) dans le dossier qu'ils doublaient`
      : 'Aucun doublon à fusionner',
  ]
  if (r.a_trancher.length)
    parts.push(
      `${r.a_trancher.length} à trancher — les deux dossiers ont été travaillés : ${r.a_trancher.join(', ')}`,
    )
  return parts.join('. ') + '.'
}

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
