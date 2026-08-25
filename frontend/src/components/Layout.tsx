import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuthStore } from '@/store/auth'
import { initials } from '@/lib/format'

export function Logo() {
  return (
    <span className="flex items-center gap-2">
      <span className="grid h-7 w-7 place-items-center rounded-md bg-ink-900 text-[13px] font-bold text-white">
        T
      </span>
      <span className="text-[15px] font-semibold tracking-tight text-ink-900">TriCV</span>
    </span>
  )
}

export default function Layout() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const user = useAuthStore((state) => state.user)
  const logout = useAuthStore((state) => state.logout)

  const navClass = ({ isActive }: { isActive: boolean }) =>
    `rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
      isActive ? 'bg-ink-100 text-ink-900' : 'text-ink-600 hover:bg-ink-100 hover:text-ink-900'
    }`

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-ink-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[1400px] items-center gap-3 px-4 sm:gap-6 sm:px-6">
          <NavLink to="/mandats" className="shrink-0">
            <Logo />
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
            {user && (
              <div className="flex items-center gap-2">
                <span
                  className="grid h-8 w-8 place-items-center rounded-full bg-ink-100 text-xs font-semibold text-ink-700"
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
        <p className="border-t border-ink-200 pt-4 text-xs text-ink-400">{t('app.tagline')}</p>
      </footer>
    </div>
  )
}
