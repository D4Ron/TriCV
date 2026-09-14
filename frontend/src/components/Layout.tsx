import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuthStore } from '@/store/auth'
import { initials } from '@/lib/format'
import { LogoKapi, Marque } from '@/components/Marque'

export { LogoKapi, Marque }

/** Conservé pour les écrans qui l'importaient déjà sous ce nom. */
export function Logo() {
  return <Marque />
}

export default function Layout() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const user = useAuthStore((state) => state.user)
  const logout = useAuthStore((state) => state.logout)

  // L'onglet actif prend le bleu de la marque plutôt qu'un gris : sur une
  // barre blanche, c'est le seul repère de position.
  const navClass = ({ isActive }: { isActive: boolean }) =>
    `rounded-lg px-3 py-1.5 text-sm font-medium transition-colors duration-120 ${
      isActive
        ? 'bg-brand-100 text-brand-800'
        : 'text-ink-600 hover:bg-ink-100 hover:text-ink-900'
    }`

  return (
    <div className="min-h-screen">
      {/* Filet or en tête de page : c'est le seul endroit où la couleur
          secondaire du cabinet apparaît en aplat, et il signe l'écran sans
          rien encombrer. */}
      <div className="h-1 bg-gradient-to-r from-or-500 via-or-400 to-or-500" />

      <header className="sticky top-0 z-30 border-b border-ink-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-[1400px] items-center gap-3 px-4 sm:gap-6 sm:px-6">
          <NavLink to="/mandats" className="shrink-0" aria-label="Kapi Consult — TriCV">
            <Marque />
          </NavLink>

          {/* La barre a gagné une entrée : sur écran étroit, c'est elle qui
              défile, pas la page entière. */}
          <nav className="flex min-w-0 items-center gap-1 overflow-x-auto">
            <NavLink to="/mandats" className={navClass}>
              Mandats
            </NavLink>
            <NavLink to="/vivier" className={navClass}>
              Vivier
            </NavLink>
            <NavLink to="/archives" className={navClass}>
              Archives
            </NavLink>
            {/* L'ancien modèle (session/candidat) n'est plus proposé dans la
                navigation : la chaîne mandat -> poste -> avis le couvre
                entièrement. Ses routes restent joignables le temps que ses
                données soient reprises, puis le module sera retiré. */}
            <NavLink to="/settings" className={navClass}>
              {t('nav.settings')}
            </NavLink>
          </nav>

          <div className="ml-auto flex shrink-0 items-center gap-3">
            {/* Dire que l'outil est interne, à l'endroit où on regarde en
                dernier avant d'agir. Masqué sur écran étroit : la place y va
                d'abord à la navigation. */}
            <span className="hidden text-[11px] font-medium uppercase tracking-wider text-ink-400 lg:block">
              Outil interne
            </span>
            {user && (
              <div className="flex items-center gap-2">
                <span
                  className="grid h-8 w-8 place-items-center rounded-full bg-brand-100 text-xs font-semibold text-brand-800"
                  title={user.email}
                >
                  {initials(user.full_name)}
                </span>
                <button
                  type="button"
                  className="btn-ghost px-2 py-1 text-xs"
                  onClick={() => {
                    logout()
                    navigate('/login')
                  }}
                >
                  {t('nav.logout')}
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1400px] px-4 py-8 sm:px-6">
        <Outlet />
      </main>

      <footer className="mx-auto max-w-[1400px] px-4 pb-10 sm:px-6">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-ink-200 pt-4 text-xs text-ink-400">
          <span className="font-medium text-ink-500">
            Kapi Consult · Bureau d'études et de conseil en management
          </span>
          <span aria-hidden="true">·</span>
          <span>Lomé, Togo</span>
          <span className="ml-auto">{t('app.tagline')}</span>
        </div>
      </footer>
    </div>
  )
}
