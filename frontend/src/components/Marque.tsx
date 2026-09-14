/**
 * La marque de Kapi Consult, telle qu'elle figure sur kapiconsult.tg.
 *
 * Le logo du cabinet n'est pas une image mais une composition : une grille de
 * neuf carrés en dégradé bleu, cerclée d'un filet or. La redessiner en CSS
 * plutôt que d'embarquer un fichier a trois avantages — elle reste nette à
 * toute taille, elle suit la couleur du thème, et l'application n'a pas de
 * dépendance à un fichier binaire que personne ne saurait régénérer.
 *
 * Les proportions viennent du site : cadre de 40 px, filet de 2 px, rayon de
 * 4 px, gouttière de 2 px entre les carrés.
 */

export function LogoKapi({ taille = 32 }: { taille?: number }) {
  return (
    <span
      aria-hidden="true"
      className="grid shrink-0 grid-cols-3 rounded border-2 border-or-500"
      style={{
        width: taille,
        height: taille,
        gap: Math.max(1, Math.round(taille / 20)),
        padding: Math.max(2, Math.round(taille / 13)),
      }}
    >
      {Array.from({ length: 9 }, (_, i) => (
        <span
          key={i}
          className="rounded-[1px] bg-gradient-to-br from-brand-400 to-brand-700"
        />
      ))}
    </span>
  )
}

/**
 * Le bloc d'identité complet.
 *
 * L'ordre dit à qui appartient l'outil : « Kapi Consult » d'abord, en Playfair
 * comme sur le site, puis le nom de l'outil en dessous. Quelqu'un qui ouvre
 * l'application doit voir le cabinet avant de voir le logiciel.
 */
export function Marque({
  taille = 34,
  sousTitre = 'TriCV · recrutement',
}: {
  taille?: number
  sousTitre?: string | null
}) {
  return (
    <span className="flex items-center gap-2.5">
      <LogoKapi taille={taille} />
      <span className="flex min-w-0 flex-col leading-none">
        <span className="font-titre text-[17px] font-bold text-ink-900">Kapi Consult</span>
        {sousTitre && (
          <span className="mt-1 truncate text-[11px] font-medium uppercase tracking-wider text-brand-700">
            {sousTitre}
          </span>
        )}
      </span>
    </span>
  )
}
