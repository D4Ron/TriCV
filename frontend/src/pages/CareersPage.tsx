import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { avisPublicApi } from '@/lib/api'
import CandidatureSpontanee from '@/components/CandidatureSpontanee'
import { Marque } from '@/components/Marque'
import PiedPublic from '@/components/PiedPublic'
import { EmptyState, ErrorState, PageLoader } from '@/components/ui'
import { formatDate } from '@/lib/format'

const LIBELLE_TYPE: Record<string, string> = {
  NATIONAL: 'Avis national',
  INTERNATIONAL: 'Avis international',
  GRE_A_GRE: 'Gré à gré',
}

/**
 * L'index public des postes ouverts.
 *
 * Comme le reste de la surface candidat, elle ne montre ni note, ni classement,
 * ni le nombre de personnes ayant déjà postulé.
 */
export default function CareersPage() {
  const avis = useQuery({ queryKey: ['avis-ouverts'], queryFn: avisPublicApi.ouverts })

  return (
    <div className="min-h-screen bg-ink-50">
      <div className="h-1 bg-gradient-to-r from-or-500 via-or-400 to-or-500" />
      <header className="border-b border-ink-200 bg-white">
        <div className="mx-auto flex h-16 max-w-3xl items-center px-4">
          <Marque sousTitre="Recrutement" />
        </div>
      </header>

      {/* Bandeau de marque : cette page est publique, c'est elle que voient les
          candidats. Elle doit dire pour qui ils postulent avant de dire quoi. */}
      <div className="border-b border-ink-200 bg-brand-900">
        <div className="mx-auto max-w-3xl px-4 py-10">
          <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-or-300">
            Cabinet d'études et de conseil en management · Lomé, Togo
          </p>
          <h1 className="mt-2 font-titre text-3xl font-bold text-white">
            Rejoignez nos recrutements
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-brand-200">
            Kapi Consult conduit les recrutements de ses clients en Afrique de l'Ouest.
            Consultez les avis en cours et déposez votre dossier en quelques minutes.
          </p>
        </div>
      </div>

      <main className="mx-auto max-w-3xl px-4 py-10">
        <div className="mb-6">
          <h2 className="text-lg font-semibold tracking-tight text-ink-900">Postes ouverts</h2>
        </div>

        {avis.isLoading && <PageLoader />}
        {avis.isError && <ErrorState error={avis.error} onRetry={() => avis.refetch()} />}

        {avis.data?.length === 0 && (
          <EmptyState
            title="Aucun poste ouvert actuellement"
            hint="Revenez consulter cette page ultérieurement."
          />
        )}

        <div className="grid gap-3">
          {avis.data?.map((item, index) => (
            <Link
              key={item.cle_publique}
              to={`/apply/${item.cle_publique}`}
              className="card-interactive stagger animate-rise p-5"
              style={{ ['--delai' as string]: `${index * 30}ms` }}
            >
              <div className="flex flex-wrap items-baseline gap-2">
                <h2 className="text-base font-semibold text-ink-900">{item.intitule}</h2>
                <span className="badge bg-brand-100 text-brand-800">
                  {LIBELLE_TYPE[item.type_avis] ?? item.type_avis}
                </span>
                <span className="ml-auto text-sm font-medium text-brand-700">Postuler →</span>
              </div>
              {/* Le lieu avant les dates : c'est la première question que pose
                  un candidat devant une liste de postes, et l'absence de
                  réponse en écarte plus d'un. */}
              <p className="mt-1 text-xs text-ink-500">
                {item.localisation ? `${item.localisation} · ` : ''}
                {item.departement ? `${item.departement} · ` : ''}
                {item.publie_le ? `publié le ${formatDate(item.publie_le, 'fr')}` : ''}
                {item.date_cloture
                  ? ` · clôture le ${formatDate(item.date_cloture, 'fr')}`
                  : ''}
              </p>
            </Link>
          ))}
        </div>

        <CandidatureSpontanee />

        <div className="mt-10 border-t border-ink-200 pt-6 text-xs text-ink-500">
          <p>
            Aucun compte n'est nécessaire pour postuler. Les informations que vous fournissez
            servent uniquement à l'examen de votre candidature.
          </p>
          <div className="mt-3">
            <PiedPublic />
          </div>
        </div>
      </main>
    </div>
  )
}
