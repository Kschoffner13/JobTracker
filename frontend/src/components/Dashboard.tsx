import { useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { signOut } from '../api/auth'
import { scanEmails, type Email } from '../api/emails'

export function Dashboard() {
  const { user, token, logout } = useAuth()
  const [emails, setEmails] = useState<Email[]>([])
  const [scanning, setScanning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [scanned, setScanned] = useState(false)

  const handleLogout = async () => {
    if (token) await signOut(token).catch(() => {})
    logout()
  }

  const handleScan = async () => {
    if (!token) return
    setScanning(true)
    setError(null)
    try {
      const result = await scanEmails(token)
      setEmails(result.emails)
      setScanned(true)
    } catch {
      setError('Scan failed. Please try again.')
    } finally {
      setScanning(false)
    }
  }

  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <h1>JobTracker</h1>
        <div className="user-info">
          {user?.picture && (
            <img src={user.picture} alt={user.name} className="avatar" referrerPolicy="no-referrer" />
          )}
          <span>{user?.name}</span>
          <button onClick={handleLogout} className="logout-btn">Sign out</button>
        </div>
      </header>

      <main className="dashboard-main">
        <div className="scan-section">
          <button onClick={handleScan} disabled={scanning} className="scan-btn">
            {scanning ? 'Scanning...' : 'Scan Emails'}
          </button>
          {error && <p className="error">{error}</p>}
          {scanned && !scanning && (
            <p className="scan-summary">
              Found <strong>{emails.length}</strong> job-related email{emails.length !== 1 ? 's' : ''}
            </p>
          )}
        </div>

        {emails.length > 0 && (
          <div className="email-list">
            {emails.map((email) => (
              <div key={email.id} className="email-card">
                <div className="email-meta">
                  <span className="email-from">{email.from}</span>
                  <span className="email-date">{email.date}</span>
                </div>
                <p className="email-subject">{email.subject}</p>
                <p className="email-snippet">{email.snippet}</p>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
