import { createBrowserRouter } from 'react-router-dom';
import AdminLayout from './layout/AdminLayout';
import DashboardPage from './pages/DashboardPage';
import ProvidersPage from './pages/ProvidersPage';
import CredentialsPage from './pages/CredentialsPage';
import SchwabAuthPage from './pages/SchwabAuthPage';
import AlertsPage from './pages/AlertsPage';
import AuthCallbackPage from './pages/AuthCallbackPage';
import { SettingsPage } from './pages/SettingsPage';
import AuthGuard from './components/AuthGuard';

export const router = createBrowserRouter([
  {
    path: '/admin',
    element: (
      <AuthGuard>
        <AdminLayout />
      </AuthGuard>
    ),
    children: [
      {
        index: true,
        element: <DashboardPage />,
      },
      {
        path: 'providers',
        element: <ProvidersPage />,
      },
      {
        path: 'credentials',
        element: <CredentialsPage />,
      },
      {
        path: 'schwab-auth',
        element: <SchwabAuthPage />,
      },
      {
        path: 'alerts',
        element: <AlertsPage />,
      },
      {
        path: 'settings',
        element: <SettingsPage />,
      },
    ],
  },
  {
    path: '/admin/callback',
    element: <AuthCallbackPage />,
  },
]);
