import { useEffect, useState, type FormEvent } from 'react'
import { api, del, patch, post, type CallRecord, type Team, type Week } from '../lib/api'
import { CareBars, WeekGrid, pct } from './Charts'

// ------------------------------------------------------------------ metrics

export function Metrics({ coopId, refreshKey }: { coopId: string; refreshKey: number }) {
  const [week, setWeek] = useState<Week | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    api<Week>(`/api/coops/${coopId}/metrics?days=7`).then(setWeek).catch((e) => setError(e.message))
  }, [coopId, refreshKey])

  if (error) return <p className="error">{error}</p>
  if (!week) return <p className="note">Reading the week.</p>
  const t = week.today

  return (
    <section className="metrics">
      {t.simulated && <p className="note" style={{ marginTop: 0 }}>Readings in this section are demo data.</p>}

      <div className="tiles">
        <div className="tile hero" title={`Care score: water ${week.care_weights.water * 100}%, comfort ${week.care_weights.comfort * 100}%, feed ${week.care_weights.feed * 100}%, calm nights ${week.care_weights.calm_nights * 100}%`}>
          <span className="label">Care score</span>
          <span className="big">{t.care ?? '–'}</span>
          <span className="note">water, comfort, feed, calm nights</span>
        </div>
        <Tile label="Water" value={pct(t.water_ok)} sub={t.dry_minutes ? `dry about ${t.dry_minutes} min` : 'never dry'} warn={(t.dry_minutes ?? 0) >= 10} />
        <Tile label="Feed" value={pct(t.feed_ok)} sub={t.empty_feeder_minutes ? `empty about ${t.empty_feeder_minutes} min` : 'of checks not low'} warn={(t.feed_ok ?? 1) < 0.8} />
        <Tile label="Comfort" value={pct(t.comfort)} sub={`cold ${pct(t.cold)} · hot ${pct(t.hot)}`} warn={(t.comfort ?? 1) < 0.7} />
        <Tile label="Calm nights" value={pct(t.calm_nights)} sub="not agitated after dark" warn={(t.calm_nights ?? 1) < 0.8} />
        <Tile label="Birds in view" value={t.birds_max != null ? String(t.birds_max) : '–'} sub="most at once today" />
        <Tile label="Camera" value={`${t.coverage_h}h`} sub="of today watched" warn={t.coverage_h < 12} />
        <Tile label="Alarms" value={String(week.alarms.count)} sub={week.alarms.median_answer_min != null ? `answered in ${week.alarms.median_answer_min} min` : 'this week'} />
      </div>

      <div className="advice">
        {week.insights.map((i, n) => (
          <p key={n} className={`insight ${i.level}`}>
            <span className="tag">{i.level === 'act' ? 'Act' : i.level === 'watch' ? 'Watch' : 'Good'}</span>
            {i.text}
          </p>
        ))}
      </div>

      <div className="charts">
        <div className="panel">
          <div className="label">The week, hour by hour</div>
          <WeekGrid grid={week.grid} />
        </div>
        <div className="panel">
          <div className="label">Care score by day</div>
          <CareBars days={week.days} />
          <p className="note">Weighted: water 35, comfort 30, feed 20, calm nights 15.</p>
        </div>
      </div>
    </section>
  )
}

function Tile({ label, value, sub, warn }: { label: string; value: string; sub: string; warn?: boolean }) {
  return (
    <div className={`tile ${warn ? 'warn' : ''}`}>
      <span className="label">{label}</span>
      <span className="val">{value}{warn && <span className="flag" aria-label="needs attention">!</span>}</span>
      <span className="note">{sub}</span>
    </div>
  )
}

// ------------------------------------------------------------------ calls

export function Calls({ coopId, refreshKey }: { coopId: string; refreshKey: number }) {
  const [calls, setCalls] = useState<CallRecord[]>([])
  const [open, setOpen] = useState<string | null>(null)
  useEffect(() => {
    api<CallRecord[]>(`/api/coops/${coopId}/calls?limit=20`).then(setCalls).catch(() => {})
  }, [coopId, refreshKey])

  return (
    <section className="panel">
      <div className="label" style={{ marginBottom: 8 }}>Calls</div>
      {!calls.length && <p className="note">No calls yet.</p>}
      {calls.map((c) => (
        <div key={c.id} className="callrow">
          <button className="callhead" onClick={() => setOpen(open === c.id ? null : c.id)}>
            <span className="when">{c.when}</span>
            <span className="who">{c.name || 'Caller'}{c.alarm_id && <span className="badge ember">alarm</span>}</span>
            <span className="dur">{c.duration_s != null ? fmtDur(c.duration_s) : c.status}</span>
          </button>
          {open === c.id && (
            <div className="callbody">
              {c.transcript.map((l, i) => (
                <p key={i} className={l.who === 'coop' ? 'coop' : 'you'}>
                  <span>{l.who === 'coop' ? 'Coop' : 'You'}</span>{l.text}
                </p>
              ))}
              {!!c.tools.length && <p className="note">Looked up: {[...new Set(c.tools)].join(', ')} · {c.evidence} pictures shown</p>}
            </div>
          )}
        </div>
      ))}
    </section>
  )
}

const fmtDur = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`

// ------------------------------------------------------------------ team

export function TeamPanel({ coopId }: { coopId: string }) {
  const [team, setTeam] = useState<Team | null>(null)
  const [email, setEmail] = useState('')
  const [role, setRole] = useState('keeper')
  const [err, setErr] = useState('')
  const load = () => api<Team>(`/api/coops/${coopId}/team`).then(setTeam).catch((e) => setErr(e.message))
  useEffect(() => { load() }, [coopId])

  async function add(e: FormEvent) {
    e.preventDefault()
    setErr('')
    try {
      await post(`/api/coops/${coopId}/team`, { email, role })
      setEmail('')
      load()
    } catch (e: any) { setErr(e.message) }
  }
  const act = (p: Promise<unknown>) => p.then(load).catch((e) => setErr(e.message))

  if (!team) return null
  return (
    <section className="panel">
      <div className="label" style={{ marginBottom: 8 }}>Team</div>
      <p className="note" style={{ marginTop: 0 }}>The owner is rung first. From the third ring, everyone on the team is rung.</p>
      {team.members.map((m) => (
        <div key={m.uid} className="member">
          <span className="who">{m.name || m.email || 'Member'}<span className="note"> {m.email}</span></span>
          {team.can_manage && m.role !== 'owner' ? (
            <>
              <select value={m.role} onChange={(e) => act(patch(`/api/coops/${coopId}/team/${m.uid}`, { role: e.target.value }))}>
                <option value="keeper">Keeper</option>
                <option value="viewer">Viewer</option>
              </select>
              <button className="quiet-link" onClick={() => act(del(`/api/coops/${coopId}/team/${m.uid}`))}>Remove</button>
            </>
          ) : <span className="role">{m.role}</span>}
        </div>
      ))}
      {team.invites.map((i) => (
        <div key={i.email} className="member pending">
          <span className="who">{i.email}<span className="note"> invited</span></span>
          <span className="role">{i.role}</span>
          <button className="quiet-link" onClick={() => act(del(`/api/coops/${coopId}/invites/${encodeURIComponent(i.email)}`))}>Cancel</button>
        </div>
      ))}
      {team.can_manage && (
        <form className="invite" onSubmit={add}>
          <input type="email" placeholder="their Google email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="keeper">Keeper</option>
            <option value="viewer">Viewer</option>
          </select>
          <button className="btn">Invite</button>
        </form>
      )}
      <p className="note">Keepers can answer and clear alarms. Viewers can watch and call.</p>
      {err && <p className="error">{err}</p>}
    </section>
  )
}
