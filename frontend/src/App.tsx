import './App.css'
import { useAuth } from './contexts/AuthContext'
import { LoginPage } from './components/LoginPage'
import { Dashboard } from './components/Dashboard'

function App() {
  const { user, loading } = useAuth()

  if (loading) {
    return <div className="loading">Loading...</div>
  }

  return user ? <Dashboard /> : <LoginPage />
}

export default App
