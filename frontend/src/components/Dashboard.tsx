import { useAuth } from '../contexts/AuthContext'
import { signOut } from '../api/auth'

export function Dashboard() {
  const { user, token, logout } = useAuth()

  const handleLogout = async () => {
    if (token) await signOut(token).catch(() => {})
    logout()
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
          <button onClick={handleLogout} className="logout-btn">
            Sign out
          </button>
        </div>
      </header>
      <main className="dashboard-main">
        <p>
          Connected as <strong>{user?.email}</strong>
        </p>
        <p>Job application tracking coming soon.</p>
      </main>
    </div>
  )
}
