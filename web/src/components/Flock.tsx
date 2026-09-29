// The broiler business at a glance, and one click deeper.

import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { api, del, patch, post, put, usd, type Flock, type LedgerRow, type PlanRow, type Task } from '../lib/api'

// ------------------------------------------------------------------ glance

export function FlockCard({ f }: { f: Flock }) {
  const g = f.growth
  const behind = Math.round((1 - g.estimate_kg / g.target_kg) * 100)
  return (
    <div className="panel flockcard">
      <div className="row-between">
        <span className="label">{f.breed} · batch placed {f.placed}</span>
      </div>
      <div className="dayline">
        <span className="bigday">Day {f.age_days}</span>
        <span className="phase">
          Week {f.week} · {f.phase}
          {f.phase_ends_in != null && f.next_phase && <> · {f.next_phase.toLowerCase()} in {f.phase_ends_in + 1} days</>}
        </span>
      </div>
      <div className="trio">
        <Stat v={String(f.birds.alive)} l={`alive · ${f.birds.mortality_pct}% lost`} warn={f.birds.mortality_pct > 5} />
        <Stat v={`${g.estimate_kg.toFixed(2)} kg`} l={behind > 3 ? `${behind}% under target ${g.target_kg.toFixed(2)}` : `on target ${g.target_kg.toFixed(2)}`} warn={behind > 15} />
        <Stat v={`${Math.round(f.feed.today_kg)} kg`} l={`feed today · ${f.feed.today_bags} bags`} />
      </div>
    </div>
  )
}

function Stat({ v, l, warn }: { v: string; l: string; warn?: boolean }) {
  return (
    <div className={`stat ${warn ? 'warn' : ''}`}>
      <span className="v">{v}</span>
      <span className="l">{l}</span>
    </div>
  )
}

export function MoneyCard({ f }: { f: Flock }) {
  const m = f.money
  const chosen = m.chosen
  const best = m.plan.find((r) => r.day === m.best_day)
  return (
    <div className="panel moneycard">
      <span className="label">The money</span>
      <div className="moneyline">
        <span className={`bigmoney ${chosen && chosen.margin < 0 ? 'neg' : ''}`}>{usd(chosen?.margin)}</span>
        <span className="note">if sold on day {chosen?.day} · {usd(chosen?.margin_per_bird, 2)} a bird</span>
      </div>
      {best && chosen && best.day !== chosen.day && (
        <p className="hint">Day {best.day} looks better: {usd(best.margin)}. Each extra day now adds about {usd(best.extra_day_value * f.birds.alive)} across the flock.</p>
      )}
      <FeedWeeks f={f} />
      <p className="note">
        The last two weeks before selling eat <strong>{f.feed.last_two_weeks_share}%</strong> of the batch's feed.
        {f.feed.last_two_weeks_usd > 0 && <> Have about <strong>{usd(f.feed.last_two_weeks_usd)}</strong> ready for them.</>}
      </p>
      <p className="note">Cost so far about {usd(m.cost_so_far)} · {usd(m.cost_per_bird_so_far, 2)} a bird{m.estimated ? ', estimated from what the birds should have eaten' : ''}</p>
    </div>
  )
}

function FeedWeeks({ f }: { f: Flock }) {
  const weeks = f.feed.weekly.filter((w) => w.week <= Math.ceil(f.feed.sell_day / 7))
  const peak = Math.max(...weeks.map((w) => w.usd), 1)
  const lastTwoFrom = Math.ceil(f.feed.sell_day / 7) - 1
  const [hover, setHover] = useState<number | null>(null)
  return (
    <div className="feedweeks" onMouseLeave={() => setHover(null)}>
      {weeks.map((w) => (
        <div key={w.week} className="fw" onMouseEnter={() => setHover(w.week)}>
          <span className="fwv">{hover === w.week ? `${w.bags} bags` : usd(w.usd)}</span>
          <div className={`fwbar ${w.now ? 'now' : ''} ${w.week >= lastTwoFrom ? 'heavy' : ''}`} style={{ height: `${(w.usd / peak) * 100}%` }} />
          <span className="fwl">W{w.week}</span>
        </div>
      ))}
    </div>
  )
}

export function NeedsYou({ tasks, alarms }: { tasks: Task[]; alarms: { message: string; time: string }[] }) {
  const urgent = tasks.filter((t) => t.when !== 'daily')
  if (!urgent.length && !alarms.length) {
    return <div className="panel needs calm"><span className="label">Needs you</span><p className="note">Nothing today. The routine is under More.</p></div>
  }
  return (
    <div className="panel needs">
      <span className="label">Needs you</span>
      {alarms.map((a, i) => (
        <p key={`a${i}`} className="need alarm"><span className="when">{a.time}</span>{a.message}</p>
      ))}
      {urgent.map((t, i) => (
        <p key={i} className={`need ${t.when.includes('overdue') || t.when === 'now' ? 'late' : ''}`}>
          <span className="when">{t.when}</span>{t.text}
        </p>
      ))}
    </div>
  )
}

// ------------------------------------------------------------------ deeper

export function Section({ id, title, summary, open, onToggle, children }: {
  id: string; title: string; summary?: ReactNode; open: boolean; onToggle: () => void; children: ReactNode
}) {
  return (
    <section id={id} className={`more ${open ? 'open' : ''}`}>
      <button className="morehead" onClick={onToggle} aria-expanded={open}>
        <span className="t">{title}</span>
        <span className="s">{summary}</span>
        <span className="chev">{open ? '−' : '+'}</span>
      </button>
      {open && <div className="morebody">{children}</div>}
    </section>
  )
}

export function Growth({ f }: { f: Flock }) {
  return (
    <div className="split">
      <div>
        <WeightChart f={f} />
        <p className="note">Your line is the breed target scaled by {f.growth.factor_source}. Weigh ten birds each week to keep it honest.</p>
      </div>
      <div className="facts">
        <Fact k="Feed today" v={`${f.feed.today_kg} kg · ${f.feed.per_bird_g} g a bird`} />
        <Fact k="Water today" v={`about ${f.water_l_today} litres`} />
        <Fact k="Feed bought" v={`${f.feed.bought_kg} kg`} />
        <Fact k="Eaten so far" v={`about ${f.feed.eaten_kg} kg`} />
        <Fact k="On hand" v={f.feed.on_hand_kg != null ? `about ${f.feed.on_hand_kg} kg · ${f.feed.days_left} days` : 'log feed purchases to see'} warn={(f.feed.days_left ?? 99) <= 5} />
        <table className="table compact">
          <thead><tr><th>Week</th><th>Per bird</th><th>Bags</th><th>Cost</th></tr></thead>
          <tbody>
            {f.feed.weekly.map((w) => (
              <tr key={w.week} className={w.now ? 'nowrow' : ''}><td>{w.week}</td><td>{w.kg_per_bird} kg</td><td>{w.bags}</td><td>{usd(w.usd)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Fact({ k, v, warn }: { k: string; v: string; warn?: boolean }) {
  return <div className={`fact ${warn ? 'warn' : ''}`}><span className="k">{k}</span><span className="v">{v}</span></div>
}

function WeightChart({ f }: { f: Flock }) {
  const [hover, setHover] = useState<number | null>(null)
  const W = 420, H = 190, L = 34, B = 22
  const days = f.growth.curve
  const maxDay = days[days.length - 1].day
  const maxKg = Math.max(...days.map((d) => d.target_kg), ...f.growth.weighs.map((w) => w.kg)) * 1.05
  const x = (d: number) => L + ((W - L - 8) * d) / maxDay
  const y = (kg: number) => H - B - ((H - B - 8) * kg) / maxKg
  const line = (pick: (d: { day: number; target_kg: number }) => number) =>
    days.map((d, i) => `${i ? 'L' : 'M'}${x(d.day).toFixed(1)},${y(pick(d)).toFixed(1)}`).join(' ')
  const hd = hover != null ? days.find((d) => d.day === hover) : null
  return (
    <div className="weightchart">
      <svg viewBox={`0 0 ${W} ${H}`} onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const r = e.currentTarget.getBoundingClientRect()
          const d = Math.round((((e.clientX - r.left) / r.width) * W - L) / ((W - L - 8) / maxDay))
          setHover(Math.max(0, Math.min(maxDay, d)))
        }}>
        {[1, 2, 3].filter((k) => k < maxKg).map((k) => (
          <g key={k}><line x1={L} x2={W} y1={y(k)} y2={y(k)} className="grid" /><text x={L - 6} y={y(k) + 3} className="axis-text" textAnchor="end">{k} kg</text></g>
        ))}
        {[0, 7, 14, 21, 28, 35, 42, 49].filter((d) => d <= maxDay).map((d) => (
          <text key={d} x={x(d)} y={H - 6} className="axis-text" textAnchor="middle">{d}</text>
        ))}
        <line x1={x(f.age_days)} x2={x(f.age_days)} y1={8} y2={H - B} className="today" />
        <path d={line((d) => d.target_kg)} className="target" />
        <path d={line((d) => d.target_kg * f.growth.factor)} className="yours" />
        {f.growth.weighs.map((w, i) => <circle key={i} cx={x(w.day)} cy={y(w.kg)} r={5} className="weigh" />)}
        {hd && <line x1={x(hd.day)} x2={x(hd.day)} y1={8} y2={H - B} className="cross" />}
      </svg>
      {hd && (
        <div className="tip static">
          <strong>Day {hd.day}</strong>
          <span>Breed target {hd.target_kg.toFixed(2)} kg</span>
          <span>Your flock about {(hd.target_kg * f.growth.factor).toFixed(2)} kg</span>
        </div>
      )}
      <div className="legend">
        <span><i className="swatch target" />Breed target</span>
        <span><i className="swatch yours" />Your flock</span>
        <span><i className="swatch dot" />Weigh-ins</span>
      </div>
    </div>
  )
}

export function SellPlan({ coopId, f, canEdit, onSaved }: { coopId: string; f: Flock; canEdit: boolean; onSaved: () => void }) {
  const best = f.money.best_day
  const rows = f.money.plan.filter((r) => r.day % 2 === 1 || r.day === best || r.day === f.feed.sell_day)
  return (
    <div>
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>Sell on day</th><th>Weight</th><th>Revenue</th><th>Feed still to buy</th><th>Margin</th><th>A bird</th><th>One more day</th></tr></thead>
          <tbody>
            {rows.map((r: PlanRow) => (
              <tr key={r.day} className={`${r.day === best ? 'best' : ''} ${r.day === f.feed.sell_day ? 'chosen' : ''}`}>
                <td>{r.day}{r.day === best && <span className="badge">best</span>}{r.day === f.feed.sell_day && <span className="badge">plan</span>}</td>
                <td>{r.weight_kg} kg</td><td>{usd(r.revenue)}</td><td>{usd(r.feed_to_buy)}</td>
                <td className={r.margin < 0 ? 'hot' : ''}>{usd(r.margin)}</td><td>{usd(r.margin_per_bird, 2)}</td>
                <td className={r.extra_day_value < 0 ? 'hot' : ''}>{usd(r.extra_day_value * f.birds.alive)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="note">One more day is the weight a bird gains that day, at your sell price, minus the feed it eats. When it turns negative, waiting costs money.</p>
      {canEdit && <Prices coopId={coopId} f={f} onSaved={onSaved} />}
    </div>
  )
}

function Prices({ coopId, f, onSaved }: { coopId: string; f: Flock; onSaved: () => void }) {
  const p = f.money.prices
  const [v, setV] = useState({ chick: p.chick, feed_bag: +(p.feed_per_kg * 50).toFixed(2), sell_per_kg: p.sell_per_kg, other_per_bird: p.other_per_bird, sell_day: f.feed.sell_day })
  const [msg, setMsg] = useState('')
  async function save(e: FormEvent) {
    e.preventDefault()
    await patch(`/api/coops/${coopId}/flock`, {
      prices: { chick: v.chick, feed_per_kg: v.feed_bag / 50, sell_per_kg: v.sell_per_kg, other_per_bird: v.other_per_bird },
      sell_day: v.sell_day,
    })
    setMsg('Saved.')
    onSaved()
  }
  const field = (k: keyof typeof v, label: string, step = '0.01') => (
    <label className="field"><span className="note">{label}</span>
      <input type="number" step={step} value={v[k]} onChange={(e) => setV({ ...v, [k]: Number(e.target.value) })} /></label>
  )
  return (
    <form className="prices" onSubmit={save}>
      {field('chick', 'Chick $')}{field('feed_bag', 'Feed $ per 50 kg bag')}{field('sell_per_kg', 'Sell $ per kg live')}
      {field('other_per_bird', 'Other $ per bird')}{field('sell_day', 'Plan to sell on day', '1')}
      <button className="btn">Save prices</button>{msg && <span className="note">{msg}</span>}
    </form>
  )
}

const KIND_WORDS: Record<string, string> = {
  feed_bought: 'Feed bought', deaths: 'Deaths', sold: 'Sold', weighed: 'Weighed', expense: 'Expense', vaccinated: 'Vaccinated', note: 'Note',
}

export function Records({ coopId, canWrite, onChange }: { coopId: string; canWrite: boolean; onChange: () => void }) {
  const [rows, setRows] = useState<LedgerRow[]>([])
  const [kind, setKind] = useState('feed_bought')
  const [qty, setQty] = useState('')
  const [amount, setAmount] = useState('')
  const [note, setNote] = useState('')
  const [err, setErr] = useState('')
  const load = () => api<LedgerRow[]>(`/api/coops/${coopId}/ledger`).then(setRows).catch((e) => setErr(e.message))
  useEffect(() => { load() }, [coopId])

  const units: Record<string, string> = { feed_bought: 'kg', deaths: 'birds', sold: 'birds', weighed: 'kg a bird' }
  async function add(e: FormEvent) {
    e.preventDefault()
    setErr('')
    try {
      await post(`/api/coops/${coopId}/ledger`, {
        kind, quantity: qty ? Number(qty) : null,
        amount_usd: amount ? Number(amount) : null, note, unit: units[kind] ?? '',
      })
      setQty(''); setAmount(''); setNote('')
      load(); onChange()
    } catch (e: any) { setErr(e.message) }
  }
  return (
    <div>
      <p className="note" style={{ marginTop: 0 }}>Optional. The coop estimates everything from what it sees; records only sharpen it.</p>
      {canWrite && (
        <form className="recordform" onSubmit={add}>
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            {Object.entries(KIND_WORDS).map(([k, w]) => <option key={k} value={k}>{w}</option>)}
          </select>
          <input placeholder={units[kind] ? `How many ${units[kind]}` : 'Quantity'} value={qty} onChange={(e) => setQty(e.target.value)} inputMode="decimal" />
          <input placeholder="$ amount" value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" />
          <input placeholder="Note" value={note} onChange={(e) => setNote(e.target.value)} />
          <button className="btn">Add</button>
        </form>
      )}
      <div className="table-wrap" style={{ marginTop: 12 }}>
        <table className="table">
          <thead><tr><th>When</th><th>What</th><th>Quantity</th><th>Amount</th><th>Note</th><th /></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{r.ts}</td><td>{KIND_WORDS[r.kind] ?? r.kind}</td>
                <td>{r.quantity != null ? `${r.quantity} ${r.unit}` : ''}</td><td>{r.amount_usd != null ? usd(r.amount_usd, 2) : ''}</td>
                <td>{r.note}</td>
                <td>{canWrite && <button className="quiet-link" onClick={() => del(`/api/coops/${coopId}/ledger/${r.id}`).then(() => { load(); onChange() })}>Remove</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {err && <p className="error">{err}</p>}
    </div>
  )
}

export function Routine({ f }: { f: Flock }) {
  return (
    <div className="routine">
      {f.tasks.map((t, i) => <p key={i} className="need"><span className="when">{t.when}</span>{t.text}</p>)}
      <p className="note">
        Growth and feed targets: Cobb500 Broiler Performance and Nutrition Supplement, 2022. Vaccine days are a common
        schedule; your chick supplier's programme comes first. Prices are Zimbabwe figures from September 2026, edit them to yours.
      </p>
    </div>
  )
}

// ------------------------------------------------------------------ setup

export const AGES = [
  ['0', 'Day-old, arriving today'], ['7', '1 week old'], ['14', '2 weeks old'], ['21', '3 weeks old'],
  ['28', '4 weeks old'], ['35', '5 weeks old'], ['42', '6 weeks old'],
]

export function FlockFields({ v, set }: { v: FlockForm; set: (v: FlockForm) => void }) {
  const [prices, setPrices] = useState(false)
  const num = (k: keyof FlockForm, label: string, step = '1') => (
    <label className="field"><span className="note">{label}</span>
      <input type="number" step={step} value={v[k] as number} onChange={(e) => set({ ...v, [k]: Number(e.target.value) })} /></label>
  )
  return (
    <>
      <div className="row">
        <label className="field" style={{ flex: 1 }}><span className="note">Birds</span>
          <input type="number" value={v.birds || ''} placeholder="e.g. 300" onChange={(e) => set({ ...v, birds: Number(e.target.value) })} required min={1} /></label>
        <label className="field" style={{ flex: 2 }}><span className="note">How old are they?</span>
          <select value={v.age} onChange={(e) => set({ ...v, age: e.target.value })} style={{ height: 40 }}>
            {AGES.map(([d, l]) => <option key={d} value={d}>{l}</option>)}
            <option value="custom">Exact age in days</option>
          </select></label>
      </div>
      {v.age === 'custom' && num('ageDays', 'Age in days')}
      <label className="field"><span className="note">Breed</span>
        <select value={v.breed} onChange={(e) => set({ ...v, breed: e.target.value })} style={{ height: 40 }}>
          <option>Cobb 500</option><option>Ross 308</option><option>Other broiler</option>
        </select></label>
      <button type="button" className="quiet-link" onClick={() => setPrices(!prices)}>
        {prices ? 'Hide prices' : 'Prices: Zimbabwe typical, tap to use yours'}
      </button>
      {prices && (
        <div className="row">
          {num('chick', 'Chick $', '0.01')}{num('feedBag', 'Feed $ per 50 kg', '0.5')}{num('sellKg', 'Sell $ per kg', '0.05')}{num('sellDay', 'Sell on day')}
        </div>
      )}
    </>
  )
}

export type FlockForm = { birds: number; age: string; ageDays: number; breed: string; chick: number; feedBag: number; sellKg: number; sellDay: number }
export const FLOCK_DEFAULTS: FlockForm = { birds: 0, age: '0', ageDays: 0, breed: 'Cobb 500', chick: 0.9, feedBag: 31, sellKg: 2.1, sellDay: 35 }
export const flockBody = (v: FlockForm) => ({
  birds: v.birds, age_days: v.age === 'custom' ? v.ageDays : Number(v.age), breed: v.breed, sell_day: v.sellDay,
  prices: { chick: v.chick, feed_per_kg: v.feedBag / 50, sell_per_kg: v.sellKg },
})

export function SetupFlock({ coopId, onDone }: { coopId: string; onDone: () => void }) {
  const [v, setV] = useState<FlockForm>(FLOCK_DEFAULTS)
  const [err, setErr] = useState('')
  async function save(e: FormEvent) {
    e.preventDefault()
    try {
      await put(`/api/coops/${coopId}/flock`, flockBody(v))
      onDone()
    } catch (e: any) { setErr(e.message) }
  }
  return (
    <form className="panel setup" onSubmit={save}>
      <span className="label">Set up this flock</span>
      <p className="note">Optional. Leave it and the coop estimates the flock from the camera after a few pictures.</p>
      <FlockFields v={v} set={setV} />
      <button className="btn primary" style={{ marginTop: 12 }}>Start tracking</button>
      {err && <p className="error">{err}</p>}
    </form>
  )
}
