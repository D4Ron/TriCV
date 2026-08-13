import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuthStore } from '@/store/auth'
import { initials } from '@/lib/format'

function LanguageToggle() {
  const { i18n, t } = useTranslation()
  const current = i18n.resolvedLanguage ?? 'fr'
  return (
    <div
      className="flex items-center rounded-lg border border-ink-200 bg-white p-0.5"
      role="group"
      aria-label={t('nav.language')}
    >
      {(['fr', 'en'] as const).map((lang) => (
        <button
          key={lang}
          type="button"
          onClick={() => void i18n.changeLanguage(lang)}
          aria-pressed={current === lang}
          className={`rounded-md px-2 py-1 text-xs font-semibold uppercase transition-colors ${
            current === lang ? 'bg-ink-900 text-white' : 'text-ink-500 hover:text-ink-800'
          }`}
        >
          {lang}
        </button>
      ))}
    </div>
  )
}

export function Logo() {
  return (
    <span className="flex items-center gap-2">
      <span className="grid h-7 w-7 place-items-center rounded-md bg-ink-900 text-[11px] font-bold text-white">
        Tri
      </span>
      <span className="text-[15px] font-semibold tracking-tight text-ink-900">CV</span>
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
        <div className="mx-auto flex h-14 max-w-[1400px] items-center gap-6 px-4 sm:px-6">
          <NavLink to="/sessions" className="shrink-0">
            <Logo />
          </NavLink>

          <nav className="flex items-center gap-1">
            <NavLink to="/sessions" className={navClass}>
              {t('nav.sessions')}
            </NavLink>
            <NavLink to="/settings" className={navClass}>
              {t('nav.settings')}
            </NavLink>
          </nav>

          <div className="ml-auto flex items-center gap-3">
            <LanguageToggle />
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
