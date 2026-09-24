import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { avisPublicApi } from '@/lib/api'
import { LogoKapi } from '@/components/Marque'

/**
 * Le pied des pages candidat, et l'adresse à qui écrire.
 *
 * Deux pages le recopiaient, et toutes deux affichaient `info@kapiconsult.tg`
 * en dur — l'adresse générale du cabinet, pas celle du recrutement. Un candidat
 * bloqué par un dépôt écrivait donc à l'accueil, qui ne sait rien de son
 * dossier. L'adresse se règle maintenant dans les paramètres, et ce pied la
 * lit : faute de réglage, il ne promet rien plutôt que de promettre à tort.
 *
 * Le lien vers l'aide compte autant. Le candidat qui bute sur un format de
 * fichier ou sur une pièce manquante abandonne — il n'écrit pas. Une page qui
 * répond aux questions courantes en retient une partie.
 */
export default function PiedPublic({ aide = true }: { aide?: boolean }) {
  const contact = useQuery({
    queryKey: ['aide-publique'],
    queryFn: avisPublicApi.aide,
    // L'adresse ne change pas d'une page à l'autre : une lecture suffit.
    staleTime: 5 * 60 * 1000,
    retry: false,
  })
  const adresse = contact.data?.contact

  return (
    <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-400">
      <LogoKapi taille={18} />
      <span className="font-medium text-ink-500">Kapi Consult</span>
      <span aria-hidden="true">·</span>
      <span>Immeuble D&amp;D, Agoè BKS, Lomé, Togo</span>
      {adresse && (
        <>
          <span aria-hidden="true">·</span>
          <a className="underline hover:text-ink-600" href={`mailto:${adresse}`}>
            {adresse}
          </a>
        </>
      )}
      {aide && (
        <>
          <span aria-hidden="true">·</span>
          <Link className="underline hover:text-ink-600" to="/aide">
            Un problème ?
          </Link>
        </>
      )}
    </p>
  )
}

/**
 * L'encart « Un problème ? », posé au bas d'un formulaire de dépôt.
 *
 * Plus visible que le pied de page, parce que c'est là qu'on se bloque : un
 * fichier trop lourd, une pièce qu'on n'a pas, un champ qui refuse. Sans issue
 * écrite, le candidat referme l'onglet et le cabinet ne sait jamais qu'il a
 * essayé.
 */
export function EncartProbleme({ reference }: { reference?: string | null }) {
  const contact = useQuery({
    queryKey: ['aide-publique'],
    queryFn: avisPublicApi.aide,
    staleTime: 5 * 60 * 1000,
    retry: false,
  })
  const adresse = contact.data?.contact
  const objet = reference ? `?subject=${encodeURIComponent(`[${reference}] Difficulté de dépôt`)}` : ''

  return (
    <div className="mt-8 rounded-lg border border-ink-200 bg-white px-4 py-3">
      <p className="text-sm font-semibold text-ink-900">Un problème ?</p>
      <p className="mt-1 text-xs leading-relaxed text-ink-600">
        Si un document est refusé, si une pièce vous manque ou si le formulaire ne se valide
        pas, ne renoncez pas : <Link className="underline" to="/aide">la page d’aide</Link> répond
        aux difficultés les plus courantes.
        {adresse ? (
          <>
            {' '}
            Sinon, écrivez à{' '}
            <a className="underline" href={`mailto:${adresse}${objet}`}>
              {adresse}
            </a>
            {reference ? ` en rappelant la référence ${reference}.` : '.'}
          </>
        ) : null}
      </p>
    </div>
  )
}
