import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import type { User } from 'firebase/auth'
import { DEMO_COOP, signIn, watchUser } from '../lib/api'
import { ThemeToggle } from '../components/Today'

export default function Landing() {
  const [user, setUser] = useState<User | null | undefined>(undefined)
  const [error, setError] = useState('')
  const nav = useNavigate()

  useEffect(() => watchUser(setUser), [])

  return (
    <main className="landing">
      <div style={{ position: 'fixed', top: 16, right: 16 }}><ThemeToggle /></div>
      <h1 className="wordmark">Coop Call</h1>
      <p className="tagline">Call your coop. It tells you what happened, what is happening, and what to change.</p>

      <button className="lamp" onClick={() => nav(`/coop/${DEMO_COOP}`)}>
        Call the coop
      </button>

      {user === null && (
        <button className="quiet-link" onClick={() => signIn().then(() => nav('/farm')).catch((e) => setError(e.message))}>
          Sign in to connect your own coop
        </button>
      )}

      {user && (
        <Link to="/farm" className="quiet-link">Your farm</Link>
      )}

      {error && <p className="error">{error}</p>}
      <p className="foot label">Ziso · voice by AssemblyAI · eyes by Gemini</p>
    </main>
  )
}
