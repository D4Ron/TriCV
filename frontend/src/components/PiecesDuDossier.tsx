import { Field } from '@/components/ui'
import { GROUPES_TYPES, PIECES_EXIGIBLES } from '@/lib/pieces'
import type { GroupePieces, Poste } from '@/types'

/**
 * Les pièces exigées d'un candidat, en un seul écran partagé.
 *
 * Ce bloc n'existait qu'à la création du poste. Passé ce moment, la liste
 * devenait intouchable : un client qui ajoutait le certificat de nationalité en
 * cours de route obligeait à refaire le poste — et à perdre ses dossiers. Pire,
 * l'écart ne se voyait pas : la fiche affichait les pièces, le formulaire de
 * modification n'en parlait pas, et rien ne disait qu'elles étaient figées.
 *
 * Trois notions se superposent, et l'ordre des contrôles suit leur portée :
 * le statut de chaque pièce (exigée, facultative, non demandée), le format
 * qu'on lui impose, puis les pièces qui se tiennent entre elles — « la CNI ou
 * le passeport » ne se dit pas pièce par pièce.
 */

export interface ChoixPieces {
  requises: string[]
  facultatives: string[]
  /** Index dans `GROUPES_TYPES` — le référentiel fait foi, pas la copie. */
  groupes: number[]
  /** Les pièces dont on impose le PDF. */
  pdfSeul: string[]
  libresAutorisees: boolean
}

export const CHOIX_PAR_DEFAUT: ChoixPieces = {
  requises: ['LETTRE_MOTIVATION', 'CV'],
  facultatives: [],
  groupes: [],
  pdfSeul: [],
  libresAutorisees: true,
}

const memesCodes = (a: readonly string[], b: readonly string[]) =>
  a.length === b.length && [...a].sort().join('|') === [...b].sort().join('|')

/**
 * Les index de `GROUPES_TYPES` que ces groupes désignent.
 *
 * Le référentiel fait foi : un groupe venu d'ailleurs — d'une fiche lue, d'un
 * poste enregistré avant que la liste existe — n'est retenu que s'il retombe
 * sur l'un des nôtres. Le libellé ne compte pas dans la comparaison ; c'est le
 * jeu de codes et le mode qui font le groupe.
 */
export function groupesDepuis(groupes: GroupePieces[] | null | undefined): number[] {
  return (groupes ?? [])
    .map((g) => GROUPES_TYPES.findIndex((t) => t.mode === g.mode && memesCodes(t.codes, g.codes)))
    .filter((i) => i >= 0)
}

/** Relit un poste enregistré comme un choix affichable. */
export function piecesDepuis(poste: Poste): ChoixPieces {
  const groupes = groupesDepuis(poste.groupes_pieces)
  const formats = poste.formats_pieces ?? {}
  return {
    requises: poste.pieces_requises,
    facultatives: poste.pieces_facultatives,
    groupes,
    pdfSeul: Object.entries(formats)
      .filter(([, f]) => memesCodes(f, ['pdf']))
      .map(([code]) => code),
    libresAutorisees: poste.pieces_libres_autorisees,
  }
}

/**
 * Traduit le choix en ce que l'API attend.
 *
 * `formatsOrigine` n'est pas une précaution de style : l'écran ne sait dire que
 * « PDF ou tout format », alors qu'un poste peut porter une contrainte plus
 * fine posée ailleurs. Repartir de zéro l'effacerait sans que personne l'ait
 * demandé ; on ne touche donc qu'aux entrées que cet écran gouverne vraiment.
 */
export function piecesVers(
  choix: ChoixPieces,
  formatsOrigine: Record<string, string[]> = {},
): Record<string, unknown> {
  const formats: Record<string, string[]> = { ...formatsOrigine }
  for (const [code] of PIECES_EXIGIBLES) {
    if (choix.pdfSeul.includes(code)) formats[code] = ['pdf']
    else if (memesCodes(formats[code] ?? [], ['pdf'])) delete formats[code]
  }
  return {
    pieces_requises: choix.requises,
    pieces_facultatives: choix.facultatives,
    groupes_pieces: choix.groupes.map((i) => ({
      codes: GROUPES_TYPES[i].codes,
      mode: GROUPES_TYPES[i].mode,
      libelle: GROUPES_TYPES[i].libelle,
    })),
    formats_pieces: formats,
    pieces_libres_autorisees: choix.libresAutorisees,
  }
}

export default function PiecesDuDossier({
  valeur,
  onChange,
}: {
  valeur: ChoixPieces
  onChange: (v: ChoixPieces) => void
}) {
  const modifier = (part: Partial<ChoixPieces>) => onChange({ ...valeur, ...part })
  const bascule = (liste: string[], code: string, present: boolean) =>
    present ? [...liste.filter((c) => c !== code), code] : liste.filter((c) => c !== code)

  return (
    <>
      <Field
        label="Pièces du dossier"
        hint="Exigée : son absence élimine le dossier. Facultative : acceptée, jamais éliminatoire. Cochez « PDF » pour imposer ce format."
      >
        <div className="space-y-1.5">
          {PIECES_EXIGIBLES.map(([code, libelle]) => {
            const etat = valeur.requises.includes(code)
              ? 'exigee'
              : valeur.facultatives.includes(code)
                ? 'facultative'
                : 'aucune'
            return (
              <div key={code} className="flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate text-sm text-ink-700">{libelle}</span>
                <label className="flex items-center gap-1 text-xs text-ink-500">
                  <input
                    type="checkbox"
                    checked={valeur.pdfSeul.includes(code)}
                    aria-label={`PDF exigé — ${libelle}`}
                    onChange={(e) =>
                      modifier({ pdfSeul: bascule(valeur.pdfSeul, code, e.target.checked) })
                    }
                  />
                  PDF
                </label>
                <select
                  className="input w-auto py-1 text-xs"
                  value={etat}
                  aria-label={libelle}
                  onChange={(e) => {
                    const v = e.target.value
                    modifier({
                      requises: bascule(valeur.requises, code, v === 'exigee'),
                      facultatives: bascule(valeur.facultatives, code, v === 'facultative'),
                    })
                  }}
                >
                  <option value="aucune">Non demandée</option>
                  <option value="exigee">Exigée</option>
                  <option value="facultative">Facultative</option>
                </select>
              </div>
            )
          })}
        </div>
      </Field>

      <Field
        label="Pièces liées"
        hint="Ce que « exigée / facultative » ne sait pas dire : un choix entre deux documents, ou deux documents indissociables."
      >
        <div className="space-y-1.5">
          {GROUPES_TYPES.map((groupe, index) => (
            <label key={groupe.libelle} className="flex items-start gap-2 text-sm text-ink-700">
              <input
                type="checkbox"
                className="mt-0.5"
                checked={valeur.groupes.includes(index)}
                onChange={(e) =>
                  modifier({
                    groupes: e.target.checked
                      ? [...valeur.groupes, index]
                      : valeur.groupes.filter((i) => i !== index),
                  })
                }
              />
              <span>
                {groupe.libelle}
                <span className="block text-xs text-ink-500">{groupe.aide}</span>
              </span>
            </label>
          ))}
        </div>
      </Field>

      <label className="flex items-start gap-2 text-sm text-ink-700">
        <input
          type="checkbox"
          className="mt-0.5"
          checked={valeur.libresAutorisees}
          onChange={(e) => modifier({ libresAutorisees: e.target.checked })}
        />
        <span>
          Autoriser les documents libres
          <span className="block text-xs text-ink-500">
            Le candidat peut joindre ce qu&apos;il juge utile — lettre de recommandation,
            attestation — en le nommant lui-même.
          </span>
        </span>
      </label>
    </>
  )
}
