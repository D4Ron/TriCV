import type { SectionRapport, TableauRapport } from '@/lib/api'

/**
 * Le rapport tel qu'il sortira, avant qu'il ne sorte.
 *
 * L'écran de rédaction montre des champs : dix zones de texte les unes sous
 * les autres, en police à chasse fixe, sans titre ni mise en page. On y corrige
 * bien une phrase, mais on n'y voit pas le document. Juger de l'ensemble
 * obligeait à exporter en Word, ouvrir le fichier, revenir corriger, exporter
 * de nouveau — et à laisser un fichier de plus dans le dossier des
 * téléchargements à chaque tour.
 *
 * L'aperçu rend le **contenu** : même ordre, mêmes sections, mêmes numéros de
 * titre, mêmes tableaux, et **une section vide n'est pas rendue**, exactement
 * comme dans le DOCX et le PDF.
 *
 * Il ne rend pas la page de garde ni le sommaire, que l'export ajoute. Ce sont
 * deux pages sur lesquelles il n'y a rien à relire : leur contenu vient du
 * mandat et des titres, pas de la rédaction. Les montrer ici n'aurait fait
 * qu'éloigner du bas de l'écran la première phrase qu'on vient d'écrire.
 *
 * Il porte aussi les corrections en cours, non enregistrées : c'est le point de
 * l'affaire — relire avant d'enregistrer, pas après avoir exporté.
 */

/**
 * Un tableau du rapport, dessiné comme il le sera dans le document remis :
 * en-tête, rubriques en gras, sous-critères en retrait, ligne de total.
 *
 * Les rapports produits avant que cette structure n'existe n'ont que leur
 * texte aligné à l'espace ; `TableauTexte` plus bas le rend tel quel, en
 * chasse fixe, qui est la seule police où cet alignement veut dire quelque
 * chose.
 */
const FOND_LIGNE: Record<string, string> = {
  rubrique: 'bg-ink-100 font-semibold',
  total: 'bg-brand-50 font-semibold',
}

function Tableau({ tableau }: { tableau: TableauRapport }) {
  const legende = (tableau.titre || '').split('\n').filter(Boolean)

  return (
    <div className="mt-3">
      {legende.map((ligne, index) => (
        <p key={index} className="mb-1 text-[12px] font-semibold text-ink-800">
          {ligne}
        </p>
      ))}
      {tableau.colonnes.length > 0 && tableau.lignes.length > 0 && (
        // Un tableau large — les huit colonnes des préqualifiés — défile dans
        // son propre cadre plutôt que d'élargir la page.
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-[12px]">
            <thead>
              <tr>
                {tableau.colonnes.map((colonne, index) => (
                  <th
                    key={index}
                    scope="col"
                    className={`border border-ink-200 bg-ink-50 px-2 py-1.5 font-semibold text-[#1E2299] ${
                      colonne.numerique ? 'text-right' : 'text-left'
                    }`}
                  >
                    {colonne.libelle}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tableau.lignes.map((ligne, rang) => (
                <tr key={rang} className={FOND_LIGNE[ligne.genre] ?? ''}>
                  {tableau.colonnes.map((colonne, index) => (
                    <td
                      key={index}
                      className={`border border-ink-200 px-2 py-1 align-top text-ink-800 ${
                        colonne.numerique ? 'text-right tabular-nums' : 'text-left'
                      } ${ligne.genre === 'detail' && index === 0 ? 'pl-6' : ''}`}
                    >
                      {ligne.cellules[index] ?? ''}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/** Le repli : un rapport d'avant la structure, dont le texte est aligné. */
function TableauTexte({ contenu }: { contenu: string }) {
  return (
    <pre className="mt-2 overflow-x-auto whitespace-pre rounded-md bg-ink-50 p-3 font-mono text-[11px] leading-relaxed text-ink-800">
      {contenu}
    </pre>
  )
}

/**
 * La numérotation des titres, telle que les exports la calculent.
 *
 * Le document remis numérote ses sections en chiffres romains et ses
 * sous-sections sous leur section — « III. Méthodologie », puis « 3.1.
 * Présélection ». L'introduction fait exception.
 *
 * Elle se calcule sur les sections **rendues** : une section laissée vide ne
 * paraît pas dans le document, elle ne doit donc pas consommer un numéro et
 * laisser un trou à la place du II. C'est la règle de `frontispice.numeroter`
 * côté serveur ; la répéter ici est ce qui permet à l'aperçu de montrer les
 * mêmes numéros que le fichier, corrections en cours comprises — et l'aperçu
 * ne peut pas les demander au serveur pour du texte qui n'y est pas encore.
 */
const SANS_NUMERO = new Set(['INTRODUCTION'])

const ROMAINS = ['', 'I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X', 'XI', 'XII']

function romain(n: number): string {
  return ROMAINS[n] ?? String(n)
}

function numeroter(sections: SectionRapport[]): string[] {
  let section = 0
  let sousSection = 0
  return sections.map((s) => {
    if (s.niveau === 2) {
      sousSection += 1
      return section ? `${section}.${sousSection}.` : `${sousSection}.`
    }
    if (SANS_NUMERO.has((s.code || '').toUpperCase())) {
      sousSection = 0
      return ''
    }
    section += 1
    sousSection = 0
    return `${romain(section)}.`
  })
}

/**
 * Le rendu de la prose suit celui des exports : une ligne, un paragraphe.
 * Reproduire ici un découpage différent donnerait un aperçu qui ment.
 */
const PUCES = ['- ', '– ', '— ', '• ', '* ']

function Prose({ contenu }: { contenu: string }) {
  // Les mêmes marques que `paragraphes_de` côté serveur : un élément
  // d'énumération devient une puce avec retrait, dans l'aperçu comme dans le
  // fichier. Le rendre tel quel donnait ici une ligne commençant par un signe
  // moins, là une vraie liste — un aperçu qui ne montre pas le document.
  const lignes = contenu
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => {
      const puce = PUCES.find((p) => l.startsWith(p))
      return { texte: puce ? l.slice(puce.length).trim() : l, puce: Boolean(puce) }
    })

  return (
    <div className="mt-2 space-y-2">
      {lignes.map((ligne, index) =>
        ligne.puce ? (
          <p
            key={index}
            className="flex gap-2 pl-3 text-[13px] leading-relaxed text-ink-800"
          >
            <span aria-hidden="true" className="text-ink-400">
              •
            </span>
            <span>{ligne.texte}</span>
          </p>
        ) : (
          <p key={index} className="text-[13px] leading-relaxed text-ink-800">
            {ligne.texte}
          </p>
        ),
      )}
    </div>
  )
}

export default function ApercuRapport({
  titre,
  sousTitre,
  etabliLe,
  sections,
}: {
  titre: string
  sousTitre?: string
  etabliLe?: string | null
  sections: SectionRapport[]
}) {
  // La même règle que `rendre_docx` : un titre suivi de blanc se lit comme un
  // oubli, donc une section sans contenu ne paraît pas — sauf un titre
  // porteur, dont les sous-sections dépendent.
  const rendues = sections.filter(
    (s) => s.contenu.trim() || s.contenu_apres?.trim() || s.tableaux?.length || s.porteur,
  )
  const vides = sections.length - rendues.length
  const numeros = numeroter(rendues)
  const date = etabliLe ? new Date(etabliLe) : new Date()

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 text-xs text-ink-500">
        <span>
          Le contenu tel qu&apos;il sera exporté, corrections en cours comprises. Le fichier
          y ajoute la page de garde du cabinet et le sommaire.
        </span>
        {vides > 0 && (
          <span className="badge bg-amber-100 text-amber-800">
            {vides} section(s) vide(s) — non rendue(s)
          </span>
        )}
      </div>

      {/* La feuille. Fond blanc et large marge : on juge d'une mise en page sur
          une page, pas sur un panneau d'application. */}
      <div className="mt-3 rounded-lg border border-ink-200 bg-white p-6 shadow-sm sm:p-10">
        <p className="text-[11px] font-bold tracking-wide text-[#B8892A]">KAPI CONSULT</p>

        <h1 className="mt-4 text-xl font-bold leading-tight text-[#1E2299]">{titre}</h1>
        {sousTitre && <p className="mt-1 text-sm text-ink-500">{sousTitre}</p>}
        <p className="mt-1 text-[11px] text-ink-500">
          Établi le{' '}
          {date.toLocaleDateString('fr-FR', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
          })}
        </p>

        {rendues.length === 0 ? (
          <p className="mt-8 text-sm italic text-ink-500">
            Aucune section n&apos;a encore de contenu. Le document serait vide.
          </p>
        ) : (
          <div className="mt-8 space-y-6">
            {rendues.map((section, rang) => (
              <section key={section.code} className={section.niveau === 2 ? 'pl-4' : ''}>
                {section.niveau === 2 ? (
                  <h3 className="text-[13px] font-bold text-[#1E2299]">
                    {[numeros[rang], section.titre].filter(Boolean).join(' ')}
                  </h3>
                ) : (
                  <h2 className="text-[15px] font-bold text-[#1E2299]">
                    {[numeros[rang], section.titre].filter(Boolean).join(' ')}
                  </h2>
                )}
                {/* La prose d'abord, les tableaux ensuite : c'est la phrase
                    qui annonce le tableau, comme dans le document remis. */}
                {section.contenu.trim() &&
                  (section.tableaux?.length || section.origine !== 'CALCULEE' ? (
                    <Prose contenu={section.contenu} />
                  ) : (
                    <TableauTexte contenu={section.contenu} />
                  ))}
                {section.tableaux?.map((tableau, index) => (
                  <Tableau key={index} tableau={tableau} />
                ))}
                {/* Le commentaire des chiffres, après les chiffres. */}
                {section.contenu_apres?.trim() && <Prose contenu={section.contenu_apres} />}
              </section>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
