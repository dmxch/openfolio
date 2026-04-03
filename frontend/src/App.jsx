import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate, Link } from 'react-router-dom'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { DataProvider } from './contexts/DataContext'
import Layout from './components/Layout'
import { ToastProvider } from './components/Toast'
import ErrorBoundary from './components/ErrorBoundary'

// Eagerly loaded (always needed)
import Dashboard from './pages/Dashboard'
import Login from './pages/Login'

// Lazy loaded (only when navigated to)
const Portfolio = lazy(() => import('./pages/Portfolio'))
const Analysis = lazy(() => import('./pages/Analysis'))
const Transactions = lazy(() => import('./pages/Transactions'))
const StockDetail = lazy(() => import('./pages/StockDetail'))
const Settings = lazy(() => import('./pages/Settings'))
const Register = lazy(() => import('./pages/Register'))
const ForgotPassword = lazy(() => import('./pages/ForgotPassword'))
const ResetPassword = lazy(() => import('./pages/ResetPassword'))
const ChangePassword = lazy(() => import('./pages/ChangePassword'))
const Admin = lazy(() => import('./pages/Admin'))
const Hilfe = lazy(() => import('./pages/Hilfe'))
const Datenschutz = lazy(() => import('./pages/Datenschutz'))
const Disclaimer = lazy(() => import('./pages/Disclaimer'))
const Terms = lazy(() => import('./pages/Terms'))
const Imprint = lazy(() => import('./pages/Imprint'))
const Legal = lazy(() => import('./pages/Legal'))
const Changelog = lazy(() => import('./pages/Changelog'))
const Glossar = lazy(() => import('./pages/Glossar'))
const Screening = lazy(() => import('./pages/Screening'))

function PageLoader() {
  return (
    <div className="flex items-center justify-center min-h-[40vh]">
      <div className="text-text-muted text-sm">Lade...</div>
    </div>
  )
}

function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] text-center">
      <h1 className="text-6xl font-bold text-text-muted mb-4">404</h1>
      <p className="text-lg text-text-secondary mb-6">Seite nicht gefunden</p>
      <Link to="/" className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90">
        Zur&uuml;ck zum Dashboard
      </Link>
    </div>
  )
}

function ProtectedRoute({ children }) {
  const { isAuthenticated, loading, user } = useAuth()
  if (loading) {
    return (
      <div className="min-h-screen bg-body flex items-center justify-center">
        <div className="text-text-muted text-sm">Lade...</div>
      </div>
    )
  }
  if (!isAuthenticated) return <Navigate to="/login" replace />
  // Force password change redirect
  if (user?.force_password_change && window.location.pathname !== '/change-password') {
    return <Navigate to="/change-password" replace />
  }
  // Force MFA setup redirect
  if (user?.mfa_setup_required && window.location.pathname !== '/settings') {
    return <Navigate to="/settings" replace />
  }
  return children
}

function PublicRoute({ children }) {
  const { isAuthenticated, loading } = useAuth()
  if (loading) return null
  return isAuthenticated ? <Navigate to="/" replace /> : children
}

export default function App() {
  return (
    <ErrorBoundary>
    <BrowserRouter>
      <AuthProvider>
        <ToastProvider>
          <Routes>
            <Route path="/login" element={<PublicRoute><Login /></PublicRoute>} />
            <Route path="/datenschutz" element={<Suspense fallback={<div />}><Datenschutz /></Suspense>} />
            <Route path="/disclaimer" element={<Suspense fallback={<div />}><Disclaimer /></Suspense>} />
            <Route path="/nutzungsbedingungen" element={<Suspense fallback={<div />}><Terms /></Suspense>} />
            <Route path="/impressum" element={<Suspense fallback={<div />}><Imprint /></Suspense>} />
            <Route path="/register" element={<PublicRoute><Suspense fallback={<div />}><Register /></Suspense></PublicRoute>} />
            <Route path="/forgot-password" element={<PublicRoute><Suspense fallback={<div />}><ForgotPassword /></Suspense></PublicRoute>} />
            <Route path="/reset-password" element={<PublicRoute><Suspense fallback={<div />}><ResetPassword /></Suspense></PublicRoute>} />
            <Route path="/change-password" element={
              <ProtectedRoute><Suspense fallback={<div />}><ChangePassword /></Suspense></ProtectedRoute>
            } />
            <Route path="/*" element={
              <ProtectedRoute>
                <DataProvider>
                <Layout>
                  <ErrorBoundary>
                    <Suspense fallback={<PageLoader />}>
                    <Routes>
                      <Route path="/" element={<Dashboard />} />
                      <Route path="/portfolio" element={<Portfolio />} />
                      <Route path="/analysis" element={<Analysis />} />
                      <Route path="/screening" element={<Screening />} />
                      <Route path="/transactions" element={<Transactions />} />
                      <Route path="/stock/:ticker" element={<StockDetail />} />
                      <Route path="/settings" element={<Settings />} />
                      <Route path="/admin" element={<Admin />} />
                      <Route path="/glossar" element={<Glossar />} />
                      <Route path="/hilfe" element={<Hilfe />} />
                      <Route path="/changelog" element={<Changelog />} />
                      <Route path="/rechtliches" element={<Legal />} />
                      <Route path="*" element={<NotFound />} />
                    </Routes>
                    </Suspense>
                  </ErrorBoundary>
                </Layout>
                </DataProvider>
              </ProtectedRoute>
            } />
          </Routes>
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter>
    </ErrorBoundary>
  )
}
