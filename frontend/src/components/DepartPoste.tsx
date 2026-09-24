import { useRef, useState } from 'react'
import { fichesApi } from '@/lib/api'
import { Callout, Field, Spinner } from '@/components/ui'
import type { PropositionFiche } from '@/types'

/**
 * Par où commence un poste.
 *
 * Le formulaire complet s'ouvrait directement, et il demande une douzaine de
 * réglages. Or le cabinet a presque toujours une fiche de poste sous la main —
 * c'est le document que le client transmet — et elle porte déjà l'essentiel.
 * La saisie manuelle n'est plus la seule porte : c'est la dernière.
 *
 * Quatre départs, dans l'ordre où ils se présentent en pratique :
 *
 *   le document      la fiche du client, en PDF ou en Word ;
 *   le texte collé   la même chose venue d'un courriel ou d'un intranet ;
 *   la saisie        quand il n'y a pas de fiche ;
 *   plus tard        l'intitulé seul, pour ouvrir le poste et y revenir.
 *
 * Rien n'est enregistré ici. La lecture rend une **proposition** que le
 * formulaire reprend, champ par champ, avec l'origine de chacun — un champ lu
 * dans le document et un champ deviné par l'assistance ne se relisent pas de
 * la même façon.
 */

export type Depart =
  | { mode: 'formulaire'; proposition: PropositionFiche | null; source: SourceFiche | null }
  | { mode: 'plus-tard'; intitule: string }

/** Ce qui a servi à lire la fiche, pour pouvoir la joindre au poste ensuite. */
export interface SourceFiche {
  fichier?: File
  texte?: string
}

const FORMATS = '.pdf,.docx'

export default function DepartPoste({ onChoix }: { onChoix: (depart: Depart) => void }) {
  const [texte, setTexte] = useState('')
  const [collage, setCollage] = useState(false)
  const [intitule, setIntitule] = useState('')
  const [plusTard, setPlusTard] = useState(false)
  const [lecture, setLecture] = useState(false)
  const [erreur, setErreur] = useState<string | null>(null)
  const fichierRef = useRef<HTMLInputElement>(null)

  async function lire(source: SourceFiche) {
    setErreur(null)
    setLecture(true)
    try {
      const proposition = await fichesApi.lire(source)
      onChoix({ mode: 'formulaire', proposition, source })
    } catch (e) {
      setErreur(e instanceof Error ? e.message : 'La fiche n’a pas pu être lue.')
    } finally {
      setLecture(false)
    }
  }

  if (lecture) {
    return (
      <div className="flex items-center gap-3 py-8 text-sm text-ink-600">
        <Spinner />
        Lecture de la fiche — les champs reconnus seront proposés à la relecture.
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {erreur && <Callout tone="danger">{erreur}</Callout>}

      {!collage && !plusTard && (
        <div className="space-y-2">
          <Choix
            titre="Importer la fiche de poste"
            detail="PDF ou Word. Les champs reconnus remplissent le formulaire ; le document reste attaché au poste."
            onClick={() => fichierRef.current?.click()}
          />
          <Choix
            titre="Coller le texte de la fiche"
            detail="Quand la fiche arrive dans un courriel ou n’existe qu’à l’écran."
            onClick={() => setCollage(true)}
          />
          <Choix
            titre="Saisir moi-même"
            detail="Le formulaire complet, vierge."
            onClick={() => onChoix({ mode: 'formulaire', proposition: null, source: null })}
          />
          <Choix
            titre="Créer avec l’intitulé seulement"
            detail="Le poste existe tout de suite et se complète plus tard. Il ne pourra pas porter d’avis tant qu’il est incomplet."
            onClick={() => setPlusTard(true)}
          />
          <input
            ref={fichierRef}
            type="file"
            accept={FORMATS}
            className="hidden"
            onChange={(e) => {
              const fichier = e.target.files?.[0]
              if (fichier) void lire({ fichier })
              e.target.value = ''
            }}
          />
        </div>
      )}

      {collage && (
        <div className="space-y-3">
          <Field label="Texte de la fiche de poste" htmlFor="fiche-texte">
            <textarea
              id="fiche-texte"
              className="input font-mono text-xs"
              rows={12}
              value={texte}
              onChange={(e) => setTexte(e.target.value)}
              placeholder={
                'Intitulé du poste : Directeur Supply Chain\n' +
                'Direction : Supply Chain, Logistique & Trading\n' +
                'Localisation : Lomé, Togo\n\n' +
                'Profil requis\n' +
                'Diplôme de niveau BAC+5…'
              }
            />
          </Field>
          <div className="flex gap-2">
            <button
              type="button"
              className="btn-primary"
              disabled={texte.trim().length < 40}
              onClick={() => void lire({ texte: texte.trim() })}
            >
              Lire ce texte
            </button>
            <button type="button" className="btn-ghost" onClick={() => setCollage(false)}>
              Retour
            </button>
          </div>
        </div>
      )}

      {plusTard && (
        <div className="space-y-3">
          <Field label="Intitulé du poste" htmlFor="poste-intitule-rapide">
            <input
              id="poste-intitule-rapide"
              className="input"
              value={intitule}
              onChange={(e) => setIntitule(e.target.value)}
              placeholder="Directeur Administratif et Financier"
              autoFocus
            />
          </Field>
          <Callout tone="warning">
            Le poste sera marqué <b>à compléter</b>. Les exigences prennent les valeurs par
            défaut, et l’avis ne pourra pas être publié tant que la fiche n’est pas remplie —
            on ne note pas des candidats sur des exigences que personne n’a posées.
          </Callout>
          <div className="flex gap-2">
            <button
              type="button"
              className="btn-primary"
              disabled={!intitule.trim()}
              onClick={() => onChoix({ mode: 'plus-tard', intitule: intitule.trim() })}
            >
              Créer le poste
            </button>
            <button type="button" className="btn-ghost" onClick={() => setPlusTard(false)}>
              Retour
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function Choix({
  titre,
  detail,
  onClick,
}: {
  titre: string
  detail: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full rounded-lg border border-ink-200 bg-white px-4 py-3 text-left transition hover:border-brand-400 hover:bg-brand-50"
    >
      <span className="block text-sm font-semibold text-ink-900">{titre}</span>
      <span className="mt-0.5 block text-xs leading-relaxed text-ink-500">{detail}</span>
    </button>
  )
}
