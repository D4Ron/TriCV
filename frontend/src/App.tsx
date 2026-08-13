import { Navigate, Route, Routes } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import Layout from '@/components/Layout'
import LoginPage from '@/pages/LoginPage'
import SessionsPage from '@/pages/SessionsPage'
import SessionBuilderPage from '@/pages/SessionBuilderPage'
import SessionDetailPage from '@/pages/SessionDetailPage'
import SettingsPage from '@/pages/SettingsPage'
import ApplyPage from '@/pages/ApplyPage'
import CareersPage from '@/pages/CareersPage'
import { useAuthStore } from '@/store/auth'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((state) => state.accessToken)
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

function NotFound() {
  const { t } = useTranslation()
  return (
    <div className="mx-auto max-w-md py-24 text-center">
      <h1 className="text-lg font-semibold text-ink-900">{t('notFound.title')}</h1>
      <p className="mt-2 text-sm text-ink-500">{t('notFound.body')}</p>
      <Link to="/sessions" className="btn-primary mt-6">
        {t('notFound.back')}
      </Link>
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      {/* Public — no auth, no chrome. Candidates never sign in. */}
      <Route path="/careers" element={<CareersPage />} />
      <Route path="/apply/:publicKey" element={<ApplyPage />} />
      <Route path="/login" element={<LoginPage />} />

      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<Navigate to="/sessions" replace />} />
        <Route path="/sessions" element={<SessionsPage />} />
        <Route path="/sessions/new" element={<SessionBuilderPage />} />
        <Route path="/sessions/:sessionId/edit" element={<SessionBuilderPage />} />
        <Route path="/sessions/:sessionId" element={<SessionDetailPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}
