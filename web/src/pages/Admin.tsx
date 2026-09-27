import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import type { User } from 'firebase/auth'
import { api, post, signIn, watchUser, type AdminOverview } from '../lib/api'

export default function Admin() {
  const [user, setUser] = useState<User | null | undefined>(undefined)
  const [data, setData] = useState<AdminOverview | null>(null)
  const [error, setError] = useState('')
  const [q, setQ] = useState('')

  useEffect(() => watchUser(setUser), [])
  const load = () => api<AdminOverview>('/api/admin/overview').then(setData).catch((e) => setError(e.message))
  useEffect(() => { if (user) load() }, [user])

  async function toggle(uid: string, blocked: boolean) {
    try {
      await post(`/api/admin/users/${uid}/block`, { blocked })
      load()
    } catch (e: any) { setError(e.message) }
  }

  if (user === null) {
    return <main className="landing"><button className="lamp" onClick={() => signIn()}>Sign in</button></main>
  }

  const totals = data?.usage.reduce(
    (a, d) => ({ frames: a.frames + d.frames, calls: a.calls + d.calls, minutes: a.minutes + d.call_minutes, cost: a.cost + d.cost_usd }),
    { frames: 0, calls: 0, minutes: 0, cost: 0 })
  const peak = Math.max(0.01, ...(data?.usage.map((d) => d.cost_usd) ?? [0]))
  const needle = q.toLowerCase()

  return (
    <div className="shell">
      <header className="top">
        <Link to="/" className="mark">Coop Call</Link>
        <span className="name">Admin</span>
        <Link to="/farm" className="quiet-link">Farm</Link>
      </header>
      {error && <p className="error">{error}</p>}
      {!data && !error && <p className="note">Loading.</p>}

      {data && totals && (
        <>
          <div className="tiles">
            <div className="tile"><span className="label">People</span><span className="val">{data.users.length}</span><span className="note">{data.users.filter((u) => u.blocked).length} paused</span></div>
            <div className="tile"><span className="label">Coops</span><span className="val">{data.coops.length}</span><span className="note">{data.coops.reduce((a, c) => a + c.open_alarms, 0)} alarms open</span></div>
            <div className="tile"><span className="label">Frames read</span><span className="val">{totals.frames}</span><span className="note">last 14 days</span></div>
            <div className="tile"><span className="label">Calls</span><span className="val">{totals.calls}</span><span className="note">{totals.minutes.toFixed(1)} minutes</span></div>
            <div className="tile hero"><span className="label">Estimated spend</span><span className="big">${totals.cost.toFixed(2)}</span><span className="note">14 days, list prices</span></div>
          </div>

          <div className="panel" style={{ marginTop: 16 }}>
            <div className="label">Spend by day</div>
            <div className="spend">
              {data.usage.map((d) => (
                <div key={d.day} className="spendcol" title={`${d.day}: $${d.cost_usd} · ${d.frames} frames · ${d.call_minutes} call minutes`}>
                  <div className="spendbar" style={{ height: `${Math.max(2, (d.cost_usd / peak) * 100)}%` }} />
                  <span>{d.day.slice(6)}</span>
                </div>
              ))}
              {!data.usage.length && <p className="note">No usage recorded yet.</p>}
            </div>
          </div>

          <div className="section-head"><h2>Coops</h2></div>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Coop</th><th>Owner</th><th>Team</th><th>Birds</th><th>Last seen</th><th>Alarms</th><th>Calls 7d</th></tr></thead>
              <tbody>
                {data.coops.map((c) => (
                  <tr key={c.id}>
                    <td><Link to={`/coop/${c.id}`}>{c.name}</Link></td>
                    <td>{c.owner}</td>
                    <td>{c.members}{c.invites ? ` + ${c.invites} invited` : ''}</td>
                    <td>{c.birds ?? '–'}</td>
                    <td>{c.last_seen}</td>
                    <td className={c.open_alarms ? 'hot' : ''}>{c.open_alarms}</td>
                    <td>{c.calls_7d}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="section-head">
            <h2>People</h2>
            <input className="search" placeholder="Search email or name" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Name</th><th>Email</th><th>Coops</th><th>Joined</th><th>Last seen</th><th /></tr></thead>
              <tbody>
                {data.users.filter((u) => !needle || `${u.email} ${u.name}`.toLowerCase().includes(needle)).map((u) => (
                  <tr key={u.uid} className={u.blocked ? 'muted' : ''}>
                    <td>{u.name || '–'}{u.admin && <span className="badge">admin</span>}</td>
                    <td>{u.email}</td>
                    <td>{u.coops}</td>
                    <td>{u.first_seen}</td>
                    <td>{u.last_seen}</td>
                    <td>
                      {!u.admin && (
                        <button className="btn" onClick={() => toggle(u.uid, !u.blocked)}>{u.blocked ? 'Restore' : 'Pause'}</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
