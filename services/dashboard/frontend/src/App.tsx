import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './contexts/AuthContext';
import { useAuth } from './hooks/useAuth';
import Layout from './components/Layout';
import ErrorBoundary from './components/ErrorBoundary';
import LoginPage from './pages/LoginPage';

// Lazy load page components for better initial load performance
const DashboardPage = lazy(() => import('./pages/DashboardPage'));
const ReviewPage = lazy(() => import('./pages/ReviewPage'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));
const ReportsPage = lazy(() => import('./pages/ReportsPage'));
const ApprovePage = lazy(() => import('./pages/ApprovePage'));
const SignInLinkPage = lazy(() => import('./pages/SignInLinkPage'));

// Loading fallback for lazy-loaded components
const PageLoader = () => (
  <div className="flex items-center justify-center h-64">
    <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600"></div>
  </div>
);

// Protected route wrapper
const ProtectedRoute = ({ children }: { children: React.ReactNode }) => {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">Loading...</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
};

// Main app routes with lazy loading
const AppRoutes = () => {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      {/* Opened from the sign-in email: the one-time link is the key */}
      <Route path="/signin/:token" element={<Suspense fallback={<PageLoader />}><SignInLinkPage /></Suspense>} />
      {/* Opened from an alert email: no login, the token in the link is the key */}
      <Route path="/approve/:token" element={<Suspense fallback={<PageLoader />}><ApprovePage /></Suspense>} />

      <Route
        path="/"
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route index element={
          <Suspense fallback={<PageLoader />}>
            <DashboardPage />
          </Suspense>
        } />
        {/* Interviews and the old Events Report now live in Reports; keep old links working */}
        <Route path="interviews" element={<Navigate to="/reports?tab=interviews" replace />} />
        <Route path="interview-events" element={<Navigate to="/reports?tab=interviews" replace />} />
        <Route path="reports" element={
          <Suspense fallback={<PageLoader />}>
            <ReportsPage />
          </Suspense>
        } />
        <Route path="review" element={
          <Suspense fallback={<PageLoader />}>
            <ReviewPage />
          </Suspense>
        } />
        <Route path="settings" element={
          <Suspense fallback={<PageLoader />}>
            <SettingsPage />
          </Suspense>
        } />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
};

function App() {
  return (
    <ErrorBoundary>
      <AuthProvider>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </AuthProvider>
    </ErrorBoundary>
  );
}

export default App;
