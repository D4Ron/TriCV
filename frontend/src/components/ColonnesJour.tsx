import { useEffect, useRef, useState } from 'react'

/**
 * Une série par jour, en colonnes.
 *
 * Une seule série par graphique, à dessein : les visites se comptent par
 * dizaines, les candidatures par unités, et les mettre sur un même axe
 * écraserait les secondes contre le zéro. Deux échelles sur un même graphique
 * se lisent mal à coup sûr ; trois petits graphiques alignés sur les mêmes
 * jours se lisent d'un coup d'œil. Le titre nomme la série — pas de légende.
 *
 * Le graphique est un seul arrêt de tabulation : les flèches gauche et droite
 * parcourent les jours, et l'infobulle suit. Trente arrêts par graphique, sur
 * trois graphiques, rendraient la page impraticable au clavier.
 */

// Brand-500 : le bleu du cabinet, un cran plus clair que celui des boutons —
// assez de contraste avec la carte (≥ 3:1), sans l'aplat lourd d'un bleu foncé
// répété trente fois. Vérifié au validateur de palette.
const TEINTE = '#4a55d0'
const TEINTE_SURVOL = '#6b7fe8'
const FILET = '#dcdfec' // ink-200
const ENCRE_DISCRETE = '#6b7080' // ink-500

const HAUTEUR = 96
const MARGE_HAUT = 14
const MARGE_BAS = 18

export interface PointJour {
  jour: string
  valeur: number
}

function nombreRond(max: number): number {
  if (max <= 4) return Math.max(max, 1)
  const pas = 10 ** Math.floor(Math.log10(max))
  return Math.ceil(max / pas) * pas
}

function dateCourte(iso: string): string {
  return new Intl.DateTimeFormat('fr', { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(
    new Date(`${iso}T00:00:00Z`),
  )
}

function dateLongue(iso: string): string {
  return new Intl.DateTimeFormat('fr', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    timeZone: 'UTC',
  }).format(new Date(`${iso}T00:00:00Z`))
}

export default function ColonnesJour({
  titre,
  unite,
  points,
}: {
  titre: string
  /** Au pluriel, pour l'infobulle : « visites », « candidatures ». */
  unite: string
  points: PointJour[]
}) {
  const conteneur = useRef<HTMLDivElement>(null)
  const [largeur, setLargeur] = useState(0)
  const [actif, setActif] = useState<number | null>(null)

  useEffect(() => {
    const el = conteneur.current
    if (!el) return undefined
    const obs = new ResizeObserver(([e]) => setLargeur(Math.floor(e.contentRect.width)))
    obs.observe(el)
    return () => obs.disconnect()
  }, [])

  const total = points.reduce((s, p) => s + p.valeur, 0)
  const max = nombreRond(Math.max(0, ...points.map((p) => p.valeur)))
  const zone = HAUTEUR - MARGE_HAUT - MARGE_BAS
  const pas = points.length ? largeur / points.length : 0
  const epaisseur = Math.max(2, Math.min(24, pas - 2))
  const y = (v: number) => MARGE_HAUT + zone - (v / max) * zone

  function colonne(i: number, v: number) {
    const x = i * pas + (pas - epaisseur) / 2
    const haut = y(v)
    const h = MARGE_HAUT + zone - haut
    if (h <= 0) return null
    // Arrondi de 4 px au sommet, angle droit à la ligne de base.
    const r = Math.min(4, epaisseur / 2, h)
    return (
      `M${x},${MARGE_HAUT + zone}` +
      `V${haut + r}Q${x},${haut} ${x + r},${haut}` +
      `H${x + epaisseur - r}Q${x + epaisseur},${haut} ${x + epaisseur},${haut + r}` +
      `V${MARGE_HAUT + zone}Z`
    )
  }

  function clavier(e: React.KeyboardEvent) {
    if (!points.length) return
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault()
      const depart = actif ?? (e.key === 'ArrowRight' ? -1 : points.length)
      const suivant = e.key === 'ArrowRight' ? depart + 1 : depart - 1
      setActif(Math.max(0, Math.min(points.length - 1, suivant)))
    } else if (e.key === 'Home') {
      e.preventDefault()
      setActif(0)
    } else if (e.key === 'End') {
      e.preventDefault()
      setActif(points.length - 1)
    } else if (e.key === 'Escape') {
      setActif(null)
    }
  }

  const point = actif !== null ? points[actif] : null
  const xInfobulle = actif !== null ? actif * pas + pas / 2 : 0

  return (
    <figure className="min-w-0">
      {/* Titre et total sur deux lignes fixes : côte à côte, ils passaient à la
          ligne dans une colonne étroite et non dans l'autre, et les trois
          graphiques ne partaient plus de la même hauteur. */}
      <figcaption className="mb-1">
        <span className="block truncate text-xs font-medium text-ink-700">{titre}</span>
        <span className="block text-xs text-ink-500">{total.toLocaleString('fr')} sur 30 jours</span>
      </figcaption>

      <div
        ref={conteneur}
        className="relative rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
        tabIndex={points.length ? 0 : -1}
        role="img"
        aria-label={`${titre} : ${total} sur 30 jours. Flèches gauche et droite pour parcourir les jours.`}
        onKeyDown={clavier}
        onBlur={() => setActif(null)}
        onPointerLeave={() => setActif(null)}
      >
        {largeur > 0 && (
          <svg width={largeur} height={HAUTEUR} className="block" aria-hidden="true">
            {/* Repère du haut : une valeur ronde, en filet discret. */}
            <line x1={0} x2={largeur} y1={MARGE_HAUT} y2={MARGE_HAUT} stroke={FILET} strokeWidth={1} />
            <text x={0} y={MARGE_HAUT - 4} fontSize={10} fill={ENCRE_DISCRETE}>
              {max.toLocaleString('fr')}
            </text>
            {/* Ligne de base. */}
            <line
              x1={0}
              x2={largeur}
              y1={MARGE_HAUT + zone + 0.5}
              y2={MARGE_HAUT + zone + 0.5}
              stroke={FILET}
              strokeWidth={1}
            />
            {points.map((p, i) => {
              const d = colonne(i, p.valeur)
              return d ? (
                <path key={p.jour} d={d} fill={i === actif ? TEINTE_SURVOL : TEINTE} />
              ) : null
            })}
            {/* Zones de survol : toute la hauteur de la colonne, plus large que la marque. */}
            {points.map((p, i) => (
              <rect
                key={`zone-${p.jour}`}
                x={i * pas}
                y={0}
                width={pas}
                height={MARGE_HAUT + zone}
                fill="transparent"
                onPointerEnter={() => setActif(i)}
              />
            ))}
            {points.length > 0 && (
              <>
                <text x={0} y={HAUTEUR - 4} fontSize={10} fill={ENCRE_DISCRETE}>
                  {dateCourte(points[0].jour)}
                </text>
                <text x={largeur} y={HAUTEUR - 4} fontSize={10} fill={ENCRE_DISCRETE} textAnchor="end">
                  {dateCourte(points[points.length - 1].jour)}
                </text>
              </>
            )}
          </svg>
        )}

        {total === 0 && largeur > 0 && (
          <p className="pointer-events-none absolute inset-x-0 top-7 text-center text-xs text-ink-400">
            Rien sur la période
          </p>
        )}

        {point && (
          <div
            className="pointer-events-none absolute -top-2 z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-md border border-ink-200 bg-white px-2.5 py-1.5 shadow-card"
            style={{ left: Math.max(48, Math.min(largeur - 48, xInfobulle)) }}
            role="status"
          >
            <span className="block text-sm font-semibold text-ink-900">
              {point.valeur.toLocaleString('fr')} {unite}
            </span>
            <span className="block text-xs text-ink-500">{dateLongue(point.jour)}</span>
          </div>
        )}
      </div>
    </figure>
  )
}
