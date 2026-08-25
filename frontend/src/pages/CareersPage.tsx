import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { avisPublicApi } from '@/lib/api'
import { Logo } from '@/components/Layout'
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
      <header className="border-b border-ink-200 bg-white">
        <div className="mx-auto flex h-14 max-w-3xl items-center px-4">
          <Logo />
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-10">
        <div className="mb-8">
          <h1 className="text-2xl font-semibold tracking-tight text-ink-900">Postes ouverts</h1>
          <p className="mt-1 text-sm text-ink-500">
            Consultez les avis de recrutement en cours et déposez votre dossier en quelques
            minutes.
          </p>
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
          {avis.data?.map((item) => (
            <Link
              key={item.cle_publique}
              to={`/apply/${item.cle_publique}`}
              className="card p-5 transition-colors hover:border-ink-300"
            >
              <div className="flex flex-wrap items-baseline gap-2">
                <h2 className="text-base font-semibold text-ink-900">{item.intitule}</h2>
                <span className="badge bg-ink-100 text-ink-700">
                  {LIBELLE_TYPE[item.type_avis] ?? item.type_avis}
                </span>
                <span className="ml-auto text-sm font-medium text-ink-600">Postuler →</span>
              </div>
              <p className="mt-1 text-xs text-ink-500">
                {item.departement ? `${item.departement} · ` : ''}
                {item.publie_le ? `publié le ${formatDate(item.publie_le, 'fr')}` : ''}
                {item.date_cloture
                  ? ` · clôture le ${formatDate(item.date_cloture, 'fr')}`
                  : ''}
              </p>
            </Link>
          ))}
        </div>

        <p className="mt-10 border-t border-ink-200 pt-6 text-xs text-ink-500">
          Aucun compte n'est nécessaire pour postuler. Les informations que vous fournissez
          servent uniquement à l'examen de votre candidature.
        </p>
      </main>
    </div>
  )
}
