import { Outlet, NavLink, useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../api/client';
import { useAuth } from '../hooks/useAuth';
import CountdownTimer from './CountdownTimer';

const Layout = () => {
  const { user, logout } = useAuth();
  const location = useLocation();
  // Same data the Review screen uses: tells every page when the student-notification flow is only logging.
  const { data: queue } = useQuery({
    queryKey: ['reviewQueue', false],
    queryFn: () => apiClient.getReviewQueue(false),
    refetchInterval: 5 * 60 * 1000,
  });
  const showShadowBanner = !!queue?.escalation_enabled && !queue?.delivery_live && location.pathname !== '/review';

  const navigation = [
    { name: 'Dashboard', path: '/' },
    { name: 'Reports', path: '/reports' },
    { name: 'Review', path: '/review' },
    { name: 'Settings', path: '/settings' },
  ];

  return (
    <div className="min-h-screen bg-gray-300">
      {/* Navigation */}
      <nav className="bg-white shadow-sm">
        <div className="mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-16">
            <div className="flex items-center">
              {/* Colaberry logo — far left */}
              <div className="flex-shrink-0 flex items-center mr-4">
                <img
                  src="/colaberry-logo.png"
                  alt="Colaberry"
                  className="h-8 w-auto"
                />
              </div>
              {/* App name with email icon */}
              <div className="flex-shrink-0 flex items-center">
                {/* Email icon */}
                <svg className="h-6 w-6 text-primary-600 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                </svg>
                <h1 className="text-xl font-bold text-primary-600">
                  AI-Inbox-Manager
                </h1>
                <CountdownTimer variant="nav" />
              </div>
              <div className="hidden sm:ml-6 sm:flex sm:space-x-8">
                {navigation.map((item) => (
                  <NavLink
                    key={item.name}
                    to={item.path}
                    end={item.path === '/'}
                    className={({ isActive }) =>
                      `inline-flex items-center px-1 pt-1 border-b-2 text-sm font-medium ${
                        isActive
                          ? 'border-primary-500 text-gray-900'
                          : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
                      }`
                    }
                  >
                    {item.name}
                  </NavLink>
                ))}
              </div>
            </div>
            <div className="flex items-center">
              <span className="text-sm text-gray-700 mr-2">
                {user?.username}
              </span>
              <span className={`text-xs font-semibold px-2 py-0.5 rounded-full mr-4 ${user?.role === 'admin' ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-600'}`}>
                {user?.role === 'admin' ? 'Admin' : 'Stakeholder'}
              </span>
              <button
                onClick={logout}
                className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-primary-600 hover:bg-primary-700"
              >
                Logout
              </button>
            </div>
          </div>
        </div>

        {/* Mobile menu */}
        <div className="sm:hidden">
          <div className="pt-2 pb-3 space-y-1">
            {navigation.map((item) => (
              <NavLink
                key={item.name}
                to={item.path}
                end={item.path === '/'}
                className={({ isActive }) =>
                  `block pl-3 pr-4 py-2 border-l-4 text-base font-medium ${
                    isActive
                      ? 'bg-primary-50 border-primary-500 text-primary-700'
                      : 'border-transparent text-gray-500 hover:bg-gray-50 hover:border-gray-300 hover:text-gray-700'
                  }`
                }
              >
                {item.name}
              </NavLink>
            ))}
          </div>
        </div>
      </nav>

      {/* Main content */}
      {showShadowBanner && (
        <div className="bg-red-50 border-b border-red-300 text-red-800 text-sm px-4 py-2 text-center">
          <strong>Shadow mode:</strong> nothing is delivered to students yet. "Notified" and "Sent" numbers on these pages mean the plan was logged, not that a student was reached.
        </div>
      )}
      <main className="mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Outlet />
      </main>
    </div>
  );
};

export default Layout;
