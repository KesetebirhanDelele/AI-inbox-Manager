import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { apiClient } from '../api/client';
import { useAuth } from '../hooks/useAuth';

/**
 * Opened from the sign-in email. Opening the page changes nothing; the person taps Continue.
 * (An email scanner that fetches the link therefore cannot use it up.)
 */
const SignInLinkPage = () => {
  const { token = '' } = useParams();
  const navigate = useNavigate();
  const { checkAuth } = useAuth();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const proceed = async () => {
    setBusy(true);
    setError('');
    try {
      await apiClient.redeemSignInLink(token);
      await checkAuth();
      navigate('/', { replace: true });
    } catch (e) {
      setError((e as { response?: { data?: { detail?: string } } }).response?.data?.detail || 'Could not sign you in. Ask for a new link.');
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
      <div className="max-w-md w-full bg-white shadow rounded-lg p-8 space-y-5 text-center">
        <h1 className="text-xl font-semibold text-gray-900">Sign in to InboxGenius</h1>
        {error ? (
          <>
            <div className="rounded-md bg-red-50 p-4 text-sm text-red-800">{error}</div>
            <button onClick={() => navigate('/login', { replace: true })} className="text-sm font-medium text-primary-600 hover:text-primary-700">
              Back to sign in
            </button>
          </>
        ) : (
          <>
            <p className="text-sm text-gray-600">Tap Continue to finish signing in. This link works once.</p>
            <button
              onClick={proceed}
              disabled={busy}
              className="w-full py-2 px-4 text-sm font-medium rounded-md text-white bg-primary-600 hover:bg-primary-700 disabled:opacity-50"
            >
              {busy ? 'Signing in...' : 'Continue'}
            </button>
          </>
        )}
      </div>
    </div>
  );
};

export default SignInLinkPage;
