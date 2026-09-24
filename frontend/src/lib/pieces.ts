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
 * Les pièces qu'un poste peut *exiger*.
 *
 * `AUTRE` n'en fait pas partie : c'est le libellé d'un document que le
 * candidat joint de sa propre initiative, et qui s'autorise par le réglage
 * « pièces libres », pas en le cochant dans une liste d'exigences. Le demander
 * reviendrait à exiger « autre chose ».
 */
export const PIECES_EXIGIBLES = PIECES.filter(([code]) => code !== 'AUTRE')

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

/**
 * Les groupes de pièces liées.
 *
 * Deux logiques, et la distinction compte au moment d'éliminer : « la CNI ou
 * le passeport » est satisfait par l'une des deux, « le diplôme et son
 * attestation » exige les deux. Sans les grouper, un candidat qui a joint son
 * passeport était écarté pour CNI manquante.
 */
export const GROUPES_TYPES = [
  {
    libelle: "Pièce d'identité",
    mode: 'AU_MOINS_UNE' as const,
    codes: ['PIECE_IDENTITE', 'PASSEPORT'],
    aide: "La carte nationale d'identité ou le passeport, au choix du candidat.",
  },
  {
    libelle: 'Diplôme et attestation',
    mode: 'TOUTES' as const,
    codes: ['COPIE_DIPLOMES', 'ATTESTATIONS_TRAVAIL'],
    aide: "Les deux sont exigés : l'un sans l'autre ne prouve rien.",
  },
]

/**
 * Découpe une saisie « a, b ; c » en liste propre.
 *
 * Deux versions coexistaient : l'une coupait sur la virgule et le point-virgule,
 * l'autre sur la seule virgule. Dans l'éditeur de fiche, « gestion; finance »
 * devenait donc un domaine unique nommé « gestion; finance » — accepté sans
 * broncher, et comparé à rien. Le retour à la ligne est accepté aussi : c'est
 * ce qu'on obtient en collant une liste depuis un document.
 */
export function enListe(valeur: string): string[] {
  const vus = valeur
    .split(/[,;\n]/)
    .map((x) => x.trim())
    .filter(Boolean)
  return [...new Set(vus)]
}
