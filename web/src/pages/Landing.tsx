import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import type { User } from 'firebase/auth'
import { DEMO_COOP, api, post, signIn, signOutNow, watchUser, type Coop } from '../lib/api'

export default function Landing() {
  const [user, setUser] = useState<User | null | undefined>(undefined)
  const [coops, setCoops] = useState<Coop[]>([])
  const [error, setError] = useState('')
  const nav = useNavigate()

  useEffect(() => watchUser(setUser), [])
  useEffect(() => {
    if (user) api<Coop[]>('/api/coops').then(setCoops).catch((e) => setError(e.message))
  }, [user])

  return (
    <main className="landing">
      <h1 className="wordmark">Coop Call</h1>
      <p className="tagline">Call your coop. It tells you what happened, what is happening, and what to change.</p>

      <button className="lamp" onClick={() => nav(`/coop/${DEMO_COOP}`)}>
        Call the coop
      </button>

      {user === null && (
        <button className="quiet-link" onClick={() => signIn().catch((e) => setError(e.message))}>
          Sign in to connect your own coop
        </button>
      )}

      {user && (
        <section style={{ width: '100%', maxWidth: 420, textAlign: 'left' }}>
          <div className="label" style={{ marginBottom: 10 }}>Your coops</div>
          {coops.map((c) => (
            <Link key={c.id} to={`/coop/${c.id}`} className="panel" style={{ display: 'block', textDecoration: 'none', marginBottom: 8 }}>
              {c.name} <span className="note">· {c.birds_expected ?? '?'} birds</span>
            </Link>
          ))}
          <NewCoop onMade={(id) => nav(`/coop/${id}?pair=1`)} />
          <button className="quiet-link" style={{ marginTop: 16 }} onClick={() => signOutNow()}>
            Sign out {user.displayName ?? ''}
          </button>
        </section>
      )}

      {error && <p className="error">{error}</p>}
      <p className="foot label">Ziso · voice by AssemblyAI · eyes by Gemini</p>
    </main>
  )
}

function NewCoop({ onMade }: { onMade: (id: string) => void }) {
  const [name, setName] = useState('')
  const [birds, setBirds] = useState('50')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    try {
      const { coop, node_key } = await post('/api/coops', { name, birds: Number(birds), age_days: 0 })
      sessionStorage.setItem(`node-key:${coop.id}`, node_key)
      onMade(coop.id)
    } catch (err: any) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <form className="panel" onSubmit={submit}>
      <div className="label" style={{ marginBottom: 12 }}>A new coop</div>
      <label className="field">
        <span className="note">What should it be called?</span>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="The hen house" required maxLength={40} />
      </label>
      <label className="field">
        <span className="note">How many birds?</span>
        <input value={birds} onChange={(e) => setBirds(e.target.value)} inputMode="numeric" required />
      </label>
      <button className="btn primary" disabled={busy || !name}>Create</button>
      {error && <p className="error">{error}</p>}
    </form>
  )
}
