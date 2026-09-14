/**
 * Le référentiel des pièces d'un dossier, en un seul endroit.
 *
 * Il en existait trois copies — la fiche de poste, le dossier d'un candidat, le
 * dépôt en lot — et elles ont dérivé : le passeport, ajouté au serveur, ne
 * portait de libellé dans aucune, si bien que l'écran affichait « PASSEPORT »
 * au milieu de « Copie des diplômes ». Une liste dupliquée finit toujours par
 * diverger ; celle-ci fait foi.
 *
 * L'ordre est celui dans lequel les pièces se demandent, pas l'alphabétique :
 * c'est celui d'un dossier qu'on feuillette.
 */
export const PIECES: ReadonlyArray<readonly [string, string]> = [
  ['LETTRE_MOTIVATION', 'Lettre de motivation'],
  ['CV', 'CV détaillé'],
  ['COPIE_DIPLOMES', 'Copie des diplômes'],
  ['ATTESTATIONS_TRAVAIL', 'Attestations de travail'],
  ['PIECE_IDENTITE', "Carte nationale d'identité"],
  ['PASSEPORT', 'Passeport'],
  ['CERTIFICAT_NATIONALITE', 'Certificat de nationalité'],
  ['LETTRE_RECOMMANDATION', 'Lettre de recommandation'],
  ['AUTRE', 'Autre document'],
]

export const LIBELLE_PIECE: Record<string, string> = Object.fromEntries(PIECES)

/**
 * Le libellé d'une pièce.
 *
 * `intitule_libre` l'emporte quand il existe : une pièce hors nomenclature est
 * nommée par le candidat, et « Lettre de recommandation — BOAD » en dit plus
 * que « Autre document ». À défaut de tout, le code brut, qui reste lisible et
 * signale qu'une entrée manque ici.
 */
export function libellePiece(code: string, intituleLibre?: string | null): string {
  return intituleLibre?.trim() || LIBELLE_PIECE[code] || code
}
