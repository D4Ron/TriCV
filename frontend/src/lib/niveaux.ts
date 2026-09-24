/**
 * L'échelle des diplômes, en un seul endroit.
 *
 * Elle était recopiée dans quatre écrans, et les copies avaient divergé — ce
 * qui ne se voyait pas, parce qu'aucune ne s'affiche à côté d'une autre :
 *
 * - `BAC+1` figurait dans la fiche d'un poste et dans le formulaire du
 *   candidat, mais manquait aux trois listes déroulantes qui servent à le
 *   *régler*. Le serveur accepte pourtant 0 à 8. Un poste ouvert à BAC+1
 *   s'affichait donc correctement, se déclarait correctement, et ne pouvait
 *   pas être saisi.
 * - Le même niveau se lisait « BAC+2 », « BAC+2 (DUT, BTS) » ou
 *   « BAC+2 — BTS, DUT, DEUG » selon l'écran.
 *
 * Les valeurs sont celles que le dépouillement emploie, et l'échelle est
 * décrite au modèle dans les mêmes termes (voir `_EXTRACTION_SYSTEME`) : un
 * baccalauréat vaut 0, et zéro est un niveau — pas une absence de niveau.
 */

export interface Niveau {
  valeur: number
  /** Ce qu'on affiche dans une liste de réglage : court, sans exemples. */
  libelle: string
  /** La forme longue, pour un formulaire où la personne hésite. */
  detaille: string
}

export const NIVEAUX: readonly Niveau[] = [
  { valeur: 0, libelle: 'BAC', detaille: 'Baccalauréat' },
  { valeur: 1, libelle: 'BAC+1', detaille: 'BAC+1' },
  { valeur: 2, libelle: 'BAC+2', detaille: 'BAC+2 — BTS, DUT, DEUG' },
  { valeur: 3, libelle: 'BAC+3 (Licence)', detaille: 'BAC+3 — Licence, Bachelor' },
  { valeur: 4, libelle: 'BAC+4 (Master 1)', detaille: 'BAC+4 — Maîtrise, Master 1' },
  {
    valeur: 5,
    libelle: 'BAC+5 (Master, Ingénieur)',
    detaille: 'BAC+5 — Master, Ingénieur, DEA, DESS',
  },
  { valeur: 8, libelle: 'BAC+8 (Doctorat)', detaille: 'Doctorat, PhD' },
]

/**
 * Le libellé d'un niveau, y compris pour une valeur hors échelle.
 *
 * Le serveur accepte tout entier de 0 à 8 ; l'échelle n'en nomme que sept.
 * Un poste réglé à 6 ou 7 — par une importation, ou par une fiche lue — doit
 * s'afficher tel quel plutôt que de disparaître.
 */
export function libelleNiveau(valeur: number | null | undefined): string {
  if (valeur === null || valeur === undefined) return '—'
  return NIVEAUX.find((n) => n.valeur === valeur)?.libelle ?? `BAC+${valeur}`
}
