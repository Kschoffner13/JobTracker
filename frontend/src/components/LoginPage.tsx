import { useState } from 'react'
import { useGoogleLogin } from '@react-oauth/google'
import { useAuth } from '../contexts/AuthContext'
import { exchangeCode } from '../api/auth'

export function LoginPage() {
  const { login } = useAuth()
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const handleLogin = useGoogleLogin({
    flow: 'auth-code',
    scope: 'openid email profile https://www.googleapis.com/auth/gmail.readonly',
    onSuccess: async ({ code }) => {
      setLoading(true)
      setError(null)
      try {
        const { token, user } = await exchangeCode(code)
        login(token, user)
      } catch {
        setError('Sign in failed. Please try again.')
        setLoading(false)
      }
    },
    onError: () => {
      setError('Google sign in was cancelled or failed.')
      setLoading(false)
    },
  })

  return (
    <div className="login-page">
      <div className="login-card">
        <h1>JobTracker</h1>
        <p>Connect your Gmail to automatically track your job applications.</p>
        <button
          className="google-btn"
          onClick={() => handleLogin()}
          disabled={loading}
        >
          {loading ? <span className="spinner" /> : <GoogleIcon />}
          {loading ? 'Signing in...' : 'Sign in with Google'}
        </button>
        {loading && (
          <p className="loading-note">
            This may take a minute while the server warms up. Please don't close this page.
          </p>
        )}
        {error && <p className="error">{error}</p>}
        <p className="disclaimer">
          We only read emails to detect job applications. We never send emails on your behalf.
        </p>
      </div>
    </div>
  )
}

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 2.078-1.796 2.717v2.258h2.908c1.702-1.567 2.684-3.875 2.684-6.615z"
      />
      <path
        fill="#34A853"
        d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18z"
      />
      <path
        fill="#FBBC05"
        d="M3.964 10.71A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.042l3.007-2.332z"
      />
      <path
        fill="#EA4335"
        d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.958L3.964 6.29C4.672 4.163 6.656 3.58 9 3.58z"
      />
    </svg>
  )
}
