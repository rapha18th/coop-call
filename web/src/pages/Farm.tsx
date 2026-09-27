import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import type { User } from 'firebase/auth'
import { DEMO_COOP, api, post, signIn, signOutNow, watchUser, type Card, type Me } from '../lib/api'
import { FLOCK_DEFAULTS, FlockFields, flockBody, type FlockForm } from '../components/Flock'
import { ThemeToggle } from '../components/Today'

const WORDS: Record<string, string> = {
  even: 'spread out', huddled: 'huddled', crowded_feeder: 'at the feeder', crowded_drinker: 'at the drinker',
  avoiding_area: 'avoiding a spot', clustered_edges: 'at the edges', empty: 'out of view', unclear: 'unclear',
}

export default function Farm() {
  const [user, setUser] = useState<User | null | undefined>(undefined)
  const [me, setMe] = useState<Me | null>(null)
  const [cards, setCards] = useState<Card[] | null>(null)
  const [error, setError] = useState('')
  const nav = useNavigate()

  useEffect(() => watchUser(setUser), [])
  useEffect(() => {
    if (!user) return
    api<Me>('/api/me').then(setMe).catch((e) => setError(e.message))
    const load = () => api<Card[]>('/api/coops').then(setCards).catch((e) => setError(e.message))
    load()
    const t = setInterval(load, 30000)
    return () => clearInterval(t)
  }, [user])

  if (user === null) {
    return (
      <main className="landing">
        <h1 className="wordmark">Your farm</h1>
        <button className="lamp" onClick={() => signIn().catch((e) => setError(e.message))}>Sign in</button>
        {error && <p className="error">{error}</p>}
      </main>
    )
  }

  return (
    <div className="shell">
      <header className="top">
        <Link to="/" className="mark">Coop Call</Link>
        <span className="name">Your farm</span>
        {me?.admin && <Link to="/admin" className="quiet-link">Admin</Link>}
        <ThemeToggle />
        <button className="quiet-link" onClick={() => signOutNow().then(() => nav('/'))}>Sign out</button>
      </header>

      {error && <p className="error">{error}</p>}
      {!cards && !error && <p className="note">Walking the farm.</p>}

      <div className="cards">
        {cards?.map((c) => (
          <Link key={c.id} to={`/coop/${c.id}`} className={`coopcard ${c.open_alarms ? 'alarm' : ''}`}>
            <div className="thumb">
              {c.latest?.frame_url ? <img src={c.latest.frame_url} alt="" /> : <span className="lampdot" />}
            </div>
            <div className="body">
              <div className="row-between">
                <strong>{c.name}</strong>
                <span className="role">{c.role}</span>
              </div>
              {c.latest ? (
                <p className="note">
                  {c.latest.birds} birds {WORDS[c.latest.spread] ?? c.latest.spread} · drinker {c.latest.drinker.replace('_', ' ')} · {c.latest.ago}
                </p>
              ) : <p className="note">No readings yet. Pair a phone.</p>}
              {!!c.open_alarms && <p className="alarmline">{c.open_alarms} alarm{c.open_alarms > 1 ? 's' : ''} open</p>}
            </div>
          </Link>
        ))}
        <NewCoop onMade={(id) => nav(`/coop/${id}?pair=1`)} />
      </div>

      <p className="note" style={{ marginTop: 32 }}>
        Want to see one first? <Link to={`/coop/${DEMO_COOP}`}>Call the demo coop</Link>.
      </p>
    </div>
  )
}

function NewCoop({ onMade }: { onMade: (id: string) => void }) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [flock, setFlock] = useState<FlockForm>(FLOCK_DEFAULTS)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    try {
      const { coop, node_key } = await post('/api/coops', { name, ...flockBody(flock) })
      sessionStorage.setItem(`node-key:${coop.id}`, node_key)
      onMade(coop.id)
    } catch (err: any) {
      setError(err.message)
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <button className="coopcard add" onClick={() => setOpen(true)}>
        <span className="plus">+</span>
        <span>Add a coop</span>
      </button>
    )
  }
  return (
    <form className="coopcard form" onSubmit={submit}>
      <label className="field">
        <span className="note">Name</span>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="The hen house" required maxLength={40} autoFocus />
      </label>
      <FlockFields v={flock} set={setFlock} />
      <button className="btn primary" style={{ marginTop: 12 }} disabled={busy || !name}>Create and pair a phone</button>
      {error && <p className="error">{error}</p>}
    </form>
  )
}
