import { ADMIN_PATH, estPosteCabinet } from '@/lib/config'
import { Navigate, Route, Routes } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import Layout from '@/components/Layout'
import LoginPage from '@/pages/LoginPage'
import SignupPage from '@/pages/SignupPage'
import MandatsPage from '@/pages/MandatsPage'
import MandatDetailPage from '@/pages/MandatDetailPage'
import PosteDetailPage from '@/pages/PosteDetailPage'
import ArchivesPage from '@/pages/ArchivesPage'
import VivierPage from '@/pages/VivierPage'
import SessionsPage from '@/pages/SessionsPage'
import SessionBuilderPage from '@/pages/SessionBuilderPage'
import SessionDetailPage from '@/pages/SessionDetailPage'
import SettingsPage from '@/pages/SettingsPage'
import ApplyPage from '@/pages/ApplyPage'
import CareersPage from '@/pages/CareersPage'
import AidePage from '@/pages/AidePage'
import EspaceClientPage, { ActivationEspaceClient } from '@/pages/EspaceClientPage'
import { useAuthStore } from '@/store/auth'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((state) => state.accessToken)
  // Un inconnu qui tape une adresse interne ne découvre pas l'entrée du
  // cabinet : il arrive sur les postes ouverts. Un poste déjà utilisé pour se
  // connecter, lui, retrouve l'écran de connexion à l'expiration de la session.
  if (!token) return <Navigate to={estPosteCabinet() ? ADMIN_PATH : '/'} replace />
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
      {/* L'adresse nue est celle que voient les candidats : les postes ouverts.
          Le cabinet entre par /admin (ou « Se connecter » sur cette page). */}
      <Route path="/" element={<CareersPage />} />
      <Route path="/careers" element={<CareersPage />} />
      <Route path="/apply/:publicKey" element={<ApplyPage />} />
      {/* Le lien court des avis : huit caractères au lieu d'une clé de trente-deux. */}
      <Route path="/p/:publicKey" element={<ApplyPage />} />
      {/* Hors authentification, comme /careers et /apply : elle existe pour
          quelqu'un qui n'a pas de compte et n'en aura pas. */}
      <Route path="/aide" element={<AidePage />} />
      {/* L'espace du promoteur. Porte séparée de celle du cabinet, jusque dans
          le type de jeton : un accès client n'ouvre aucune route interne. */}
      <Route path="/espace-client" element={<EspaceClientPage />} />
      <Route path="/espace-client/activation/:jeton" element={<ActivationEspaceClient />} />
      {/* L'entrée du cabinet, à une adresse qui ne se devine pas. /login et
          /admin, les premières qu'on essaie, mènent aux postes ouverts. */}
      <Route path={ADMIN_PATH} element={<LoginPage />} />
      <Route path="/login" element={<Navigate to="/" replace />} />
      <Route path="/admin" element={<Navigate to="/" replace />} />
      {/* HR self-registration. The page itself reports when it is disabled. */}
      <Route path="/signup" element={<SignupPage />} />

      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        {/* Chaîne de recrutement : mandat -> poste -> grille. */}
        <Route path="/mandats" element={<MandatsPage />} />
        <Route path="/mandats/:mandatId" element={<MandatDetailPage />} />
        <Route path="/postes/:posteId" element={<PosteDetailPage />} />
        <Route path="/vivier" element={<VivierPage />} />
        <Route path="/archives" element={<ArchivesPage />} />
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
