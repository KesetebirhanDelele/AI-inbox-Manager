import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { apiClient } from '../api/client';

const inputClass =
  'appearance-none relative block w-full px-3 py-2 border border-gray-300 placeholder-gray-500 text-gray-900 rounded-md focus:outline-none focus:ring-primary-500 focus:border-primary-500 sm:text-sm';
const buttonClass =
  'w-full flex justify-center py-2 px-4 border border-transparent text-sm font-medium rounded-md text-white bg-primary-600 hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500 disabled:opacity-50 disabled:cursor-not-allowed';

const LoginPage = () => {
  const [email, setEmail] = useState('');
  const [linkMessage, setLinkMessage] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const { login, isAuthenticated } = useAuth();
  const navigate = useNavigate();

  // Redirect if already authenticated
  if (isAuthenticated) {
    navigate('/');
    return null;
  }

  const handleLink = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLinkMessage('');
    setIsLoading(true);
    try {
      const res = await apiClient.requestSignInLink(email);
      setLinkMessage(res.message);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Could not send a link. Try again in a moment.');
    } finally {
      setIsLoading(false);
    }
  };

  const handlePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);
    try {
      await login(username, password);
      navigate('/');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Login failed. Please check your credentials.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-md w-full space-y-8">
        <div>
          <h2 className="mt-6 text-center text-3xl font-extrabold text-gray-900">Email Management Dashboard</h2>
          <p className="mt-2 text-center text-sm text-gray-600">Enter your email and we will send you a sign-in link</p>
        </div>

        {error && (
          <div className="rounded-md bg-red-50 p-4">
            <div className="text-sm text-red-800">{error}</div>
          </div>
        )}

        <form className="space-y-4" onSubmit={handleLink}>
          <label htmlFor="email" className="sr-only">Email</label>
          <input
            id="email"
            name="email"
            type="email"
            required
            autoComplete="email"
            className={inputClass}
            placeholder="you@company.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={isLoading}
          />
          <button type="submit" disabled={isLoading} className={buttonClass}>
            {isLoading && !showPassword ? 'Sending...' : 'Email me a sign-in link'}
          </button>
          {linkMessage && <div className="rounded-md bg-green-50 p-4 text-sm text-green-800">{linkMessage}</div>}
        </form>

        <div className="text-center">
          <button type="button" className="text-xs text-gray-500 hover:text-gray-700 underline" onClick={() => setShowPassword(!showPassword)}>
            {showPassword ? 'Hide password sign-in' : 'Staff: sign in with a password'}
          </button>
        </div>

        {showPassword && (
          <form className="space-y-3" onSubmit={handlePassword}>
            <input
              id="username"
              name="username"
              type="text"
              required
              className={inputClass}
              placeholder="Username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={isLoading}
            />
            <input
              id="password"
              name="password"
              type="password"
              required
              className={inputClass}
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={isLoading}
            />
            <button type="submit" disabled={isLoading} className={buttonClass}>
              {isLoading ? 'Signing in...' : 'Sign in'}
            </button>
          </form>
        )}
      </div>
    </div>
  );
};

export default LoginPage;
