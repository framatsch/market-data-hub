import { createBrowserRouter, Navigate } from 'react-router-dom';
import AdminLayout from './layout/AdminLayout';
import DashboardPage from './pages/DashboardPage';
import AuthCallbackPage from './pages/AuthCallbackPage';
import SettingsPage from './pages/SettingsPage';
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
      { index: true, element: <DashboardPage /> },
      // legacy routes → dashboard
      { path: 'providers',    element: <Navigate to="/admin" replace /> },
      { path: 'credentials',  element: <Navigate to="/admin" replace /> },
      { path: 'schwab-auth',  element: <Navigate to="/admin" replace /> },
      { path: 'alerts',       element: <Navigate to="/admin" replace /> },
      { path: 'settings',     element: <SettingsPage /> },
    ],
  },
  {
    path: '/admin/callback',
    element: <AuthCallbackPage />,
  },
]);
