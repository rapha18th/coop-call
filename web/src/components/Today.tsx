// Today, front and centre. Everything else one tap away.

import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import { api, del, post, usd, type Action, type ActionButton, type CalDay, type Flock, type Month, type Span, type TodayData } from '../lib/api'
import { currentTheme, setTheme, type Theme } from '../lib/theme'
import { WeekGrid, pct } from './Charts'

// ------------------------------------------------------------------ theme

export function ThemeToggle() {
  const [t, setT] = useState<Theme>(currentTheme())
  const flip = () => {
    const next = t === 'day' ? 'night' : 'day'
    setTheme(next)
    setT(next)
  }
  return (
    <button className="themetoggle" onClick={flip} aria-label={t === 'day' ? 'Switch to night' : 'Switch to day'} title={t === 'day' ? 'Night' : 'Day'}>
      {t === 'day' ? '☾' : '☀'}
    </button>
  )
}

// ------------------------------------------------------------------ status

const TODAY_LABEL = () => new Date().toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' })

export function StatusCard({ today, flock, onOpen, onSheet }: {
  today?: TodayData; flock: Flock | null; onOpen: () => void; onSheet: (sheet: string) => void
}) {
  const level = today?.headline.level ?? 'good'
  return (
    <div className={`status-card ${level}`}>
      <button className="status-main" onClick={onOpen}>
        <span className="eyebrow"><i className="pulse" />{TODAY_LABEL()}</span>
        {flock ? <span className="dayno">Day {flock.age_days}</span> : <span className="dayno">Today</span>}
        <span className="headline">{today?.headline.text ?? 'Reading the coop.'}</span>
        <span className="open">See the whole batch <b>→</b></span>
      </button>
      {flock && <Vitals f={flock} onOpen={onSheet} />}
    </div>
  )
}

// ------------------------------------------------------------------ actions

export function Actions({ coopId, actions, onDo, onChange }: {
  coopId: string; actions: Action[]; onDo: (b: ActionButton) => void; onChange: () => void
}) {
  const [done, setDone] = useState<Record<string, boolean>>({})
  const [form, setForm] = useState<string | null>(null)
  const [err, setErr] = useState('')
  const shown = actions.filter((a) => !done[a.id]).slice(0, 3)
  const more = actions.filter((a) => !done[a.id]).length - shown.length

  async function press(a: Action, b: ActionButton) {
    setErr('')
    try {
      if (b.do === 'log') {
        await post(`/api/coops/${coopId}/ledger`, { kind: b.kind, note: b.note ?? '' })
        setDone((d) => ({ ...d, [a.id]: true }))
        onChange()
      } else if (b.do === 'resolve') {
        await post(`/api/coops/${coopId}/alarms/${b.alarm}/resolve`)
        setDone((d) => ({ ...d, [a.id]: true }))
        onChange()
      } else if (b.do === 'form') {
        setForm(form === a.id ? null : a.id)
      } else {
        onDo(b)
      }
    } catch (e: any) {
      setErr(e.message)
    }
  }

  if (!shown.length) {
    return (
      <div className="actions clear">
        <span className="eyebrow">To do</span>
        <p className="allclear">Nothing needs you right now.</p>
      </div>
    )
  }
  return (
    <div className="actions">
      <span className="eyebrow">To do</span>
      {shown.map((a, i) => (
        <div key={a.id} className={`action ${a.tone}`}>
          <span className="n">{i + 1}</span>
          <div className="body">
            <strong>{a.title}</strong>
            <span>{a.detail}</span>
            {form === a.id && (
              <QuickRecord coopId={coopId} kind={a.buttons.find((b) => b.do === 'form')?.kind ?? 'note'}
                onSaved={() => { setDone((d) => ({ ...d, [a.id]: true })); setForm(null); onChange() }} />
            )}
          </div>
          <div className="btns">
            {a.buttons.map((b) => (
              <button key={b.label} className={`btn ${b.do === 'log' || b.do === 'form' || b.do === 'resolve' ? 'primary' : ''}`} onClick={() => press(a, b)}>
                {b.label}
              </button>
            ))}
          </div>
        </div>
      ))}
      {more > 0 && <p className="note">and {more} more, all in the calendar.</p>}
      {err && <p className="error">{err}</p>}
    </div>
  )
}

function QuickRecord({ coopId, kind, onSaved }: { coopId: string; kind: string; onSaved: () => void }) {
  const [a, setA] = useState('')
  const [b, setB] = useState('')
  const [err, setErr] = useState('')
  const feed = kind === 'feed_bought'
  async function save(e: FormEvent) {
    e.preventDefault()
    try {
      await post(`/api/coops/${coopId}/ledger`, feed
        ? { kind, quantity: Number(a) * 50, unit: 'kg', amount_usd: b ? Number(b) : null, note: `${a} bags` }
        : { kind, quantity: Number(a), unit: 'kg', note: 'average of ten birds' })
      onSaved()
    } catch (e: any) { setErr(e.message) }
  }
  return (
    <form className="quick" onSubmit={save}>
      <input autoFocus inputMode="decimal" placeholder={feed ? 'Bags of 50 kg' : 'Average kg a bird'} value={a} onChange={(e) => setA(e.target.value)} required />
      {feed && <input inputMode="decimal" placeholder="Paid $" value={b} onChange={(e) => setB(e.target.value)} />}
      <button className="btn primary">Save</button>
      {err && <span className="error">{err}</span>}
    </form>
  )
}

// ------------------------------------------------------------------ vitals and tabs

export function Vitals({ f, onOpen }: { f: Flock; onOpen: (sheet: string) => void }) {
  const gap = Math.round((1 - f.growth.estimate_kg / f.growth.target_kg) * 100)
  const ch = f.money.chosen
  const best = f.money.plan.find((r) => r.day === f.money.best_day)
  return (
    <div className="vitals">
      <Vital label="Birds" v={String(f.birds.alive)} sub={`${f.birds.mortality_pct}% lost of ${f.birds.placed}`} warn={f.birds.mortality_pct > 5} onClick={() => onOpen('records')} />
      <Vital label="Weight" v={`${f.growth.estimate_kg.toFixed(2)} kg`} sub={gap > 3 ? `${gap}% under target` : 'on target'} warn={gap > 15} onClick={() => onOpen('growth')} />
      <Vital label="Feed" v={f.feed.days_left != null ? `${f.feed.days_left} days` : `${Math.round(f.feed.today_kg)} kg`} sub={f.feed.on_hand_kg != null ? `${f.feed.on_hand_kg} kg on hand` : 'a day, log purchases'} warn={(f.feed.days_left ?? 99) <= 5} onClick={() => onOpen('growth')} />
      <Vital label={`Sell on day ${ch?.day ?? '–'}`} v={usd(ch?.margin)} sub={best && best.day !== ch?.day ? `day ${best.day}: ${usd(best.margin)}` : 'the best day'} warn={(ch?.margin ?? 0) < 0} onClick={() => onOpen('money')} />
    </div>
  )
}

function Vital({ label, v, sub, warn, onClick }: { label: string; v: string; sub: string; warn?: boolean; onClick: () => void }) {
  return (
    <button className={`vital ${warn ? 'warn' : ''}`} onClick={onClick}>
      <span className="eyebrow">{label}</span>
      <span className="v">{v}</span>
      <span className="sub">{sub}</span>
    </button>
  )
}

export const SHEETS: [string, string][] = [
  ['calendar', 'Calendar'], ['growth', 'Growth'], ['money', 'Money'], ['records', 'Records'],
  ['calls', 'Calls'], ['team', 'Team'], ['phone', 'Camera'],
]

export function Tabs({ onOpen, hide, open }: { onOpen: (k: string) => void; hide: string[]; open: string | null }) {
  return (
    <nav className="tabs">
      {SHEETS.filter(([k]) => !hide.includes(k)).map(([k, l]) => (
        <button key={k} className={open === k ? 'on' : ''} onClick={() => onOpen(k)}>{l}</button>
      ))}
    </nav>
  )
}

// ------------------------------------------------------------------ sheet

export function Sheet({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', esc)
    document.body.style.overflow = 'hidden'
    return () => { window.removeEventListener('keydown', esc); document.body.style.overflow = '' }
  }, [onClose])
  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`sheet ${wide ? 'wide' : ''}`} role="dialog" aria-label={title}>
        <header>
          <h2>{title}</h2>
          <button className="close" onClick={onClose} aria-label="Close">×</button>
        </header>
        <div className="sheetbody">{children}</div>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ calendar

const WD = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const PLAN_GLYPH: Record<string, string> = { vaccine: 'V', feed: 'F', weigh: 'W', sell: '$' }
const niceDate = (iso: string, opts: Intl.DateTimeFormatOptions = { weekday: 'short', day: 'numeric', month: 'short' }) =>
  new Date(`${iso}T12:00:00`).toLocaleDateString('en-GB', opts)
const addDays = (iso: string, n: number) => {
  const d = new Date(`${iso}T12:00:00`)
  d.setDate(d.getDate() + n)
  return d.toISOString().slice(0, 10)
}

export function CalendarSheet({ coopId, onClose }: { coopId: string; onClose: () => void }) {
  const [month, setMonth] = useState<Month | null>(null)
  const [a, setA] = useState<string | null>(null)
  const [range, setRange] = useState<[string, string] | null>(null)
  const [span, setSpan] = useState<Span | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => { api<Month>(`/api/coops/${coopId}/calendar`).then(setMonth).catch((e) => setErr(e.message)) }, [coopId])
  useEffect(() => {
    if (!range) return
    setSpan(null)
    api<Span>(`/api/coops/${coopId}/span?first=${range[0]}&last=${range[1]}`).then(setSpan).catch((e) => setErr(e.message))
  }, [coopId, range])

  const cells = useMemo(() => {
    if (!month) return []
    const byDate = new Map(month.days.map((d) => [d.date, d]))
    const start = new Date(`${month.first}T12:00:00`)
    const lead = (start.getDay() + 6) % 7
    const out: (CalDay | { date: string; blank: true })[] = []
    let cur = addDays(month.first, -lead)
    const end = month.last
    while (cur <= end || out.length % 7) {
      out.push(byDate.get(cur) ?? { date: cur, blank: true })
      cur = addDays(cur, 1)
    }
    return out
  }, [month])

  function pick(date: string) {
    if (!a) { setA(date); return }
    const [x, y] = a <= date ? [a, date] : [date, a]
    setA(null)
    setRange([x, y])
  }
  const quick = (label: string, r: [string, string]) => (
    <button className="chip" onClick={() => { setA(null); setRange(r) }}>{label}</button>
  )
  const today = month?.today ?? ''

  return (
    <Sheet title={range ? 'The batch, close up' : 'The batch'} onClose={onClose} wide>
      {err && <p className="error">{err}</p>}
      {!month && !err && <p className="note">Opening the calendar.</p>}

      {month && !range && (
        <div className="cal">
          <div className="calhead">
            <p className="note">Tap a day, then another to see the stretch between them. Tap the same day twice for one day.</p>
            <div className="chips">
              {quick('Today', [today, today])}
              {quick('Last 3 days', [addDays(today, -2), today])}
              {quick('Last 7 days', [addDays(today, -6), today])}
              {quick('Whole batch so far', [month.first, today])}
            </div>
          </div>
          <div className="calgrid">
            {WD.map((w) => <span key={w} className="wd">{w}</span>)}
            {cells.map((c) => 'blank' in c ? (
              <span key={c.date} className="calcell blank" />
            ) : (
              <button key={c.date}
                className={`calcell ${c.tone} ${c.today ? 'today' : ''} ${a === c.date ? 'anchor' : ''}`}
                onClick={() => (a === c.date ? (setA(null), setRange([c.date, c.date])) : pick(c.date))}
                title={`${niceDate(c.date)}${c.age != null ? ` · day ${c.age}` : ''}${c.care != null ? ` · care ${c.care}` : ''}`}>
                <span className="dnum">{new Date(`${c.date}T12:00:00`).getDate()}{(new Date(`${c.date}T12:00:00`).getDate() === 1 || c.date === month.first) && <span className="mon">{niceDate(c.date, { month: 'short' })}</span>}</span>
                {c.age != null && <span className="age">d{c.age}</span>}
                <span className="marks">
                  {c.plan.map((p) => <i key={p} className={`pm ${p.split(':')[0]}`} title={p.replace(':', ': ')}>{PLAN_GLYPH[p.split(':')[0]]}</i>)}
                  {c.alarms > 0 && <i className="pm alarm" title={`${c.alarms} alarms`}>!</i>}
                  {c.records.length > 0 && <i className="pm rec" title={c.records.join(', ')}>•</i>}
                </span>
              </button>
            ))}
          </div>
          <div className="legend">
            <span><i className="lg good" />Good day</span><span><i className="lg watch" />Needed a look</span>
            <span><i className="lg act" />Needed action</span><span><i className="lg none" />Not watched</span>
            <span><b className="pm vaccine">V</b>Vaccine</span><span><b className="pm feed">F</b>Feed change</span>
            <span><b className="pm weigh">W</b>Weigh</span><span><b className="pm sell">$</b>Sell day</span>
          </div>
        </div>
      )}

      {month && range && (
        <div className="focus">
          <div className="focusbar">
            <button className="quiet-link" onClick={() => setRange(null)}>← All days</button>
            <div className="ministrip">
              {month.days.map((d) => (
                <button key={d.date} className={`ms ${d.tone} ${d.date >= range[0] && d.date <= range[1] ? 'in' : ''}`}
                  onClick={() => setRange([d.date, d.date])} title={niceDate(d.date)} />
              ))}
            </div>
            <span className="nav">
              <button className="quiet-link" onClick={() => setRange([addDays(range[0], -1), addDays(range[1], -1)])}>‹</button>
              <button className="quiet-link" onClick={() => setRange([addDays(range[0], 1), addDays(range[1], 1)])} disabled={range[1] >= today}>›</button>
            </span>
          </div>
          <SpanView span={span} range={range} />
        </div>
      )}
    </Sheet>
  )
}

function SpanView({ span, range }: { span: Span | null; range: [string, string] }) {
  const one = range[0] === range[1]
  const title = one ? niceDate(range[0], { weekday: 'long', day: 'numeric', month: 'long' }) : `${niceDate(range[0])} to ${niceDate(range[1])}`
  if (!span) return <div className="spanview"><h3 className="spantitle">{title}</h3><p className="note">Gathering those days.</p></div>
  const s = span.summary
  const f = span.flock
  const events = [
    ...(f?.plan ?? []).flatMap((p) => p.what.map((w) => ({ t: niceDate(p.date), k: 'plan', text: planWords(w) }))),
    ...span.records.map((r) => ({ t: r.time, k: 'rec', text: recWords(r) })),
    ...span.alarms.map((a) => ({ t: a.time, k: 'alarm', text: a.message })),
    ...span.calls.map((c) => ({ t: c.time, k: 'call', text: `${c.name} called${c.said ? `: “${c.said}”` : ''}` })),
  ]
  return (
    <div className="spanview">
      <div className="spanhead">
        <h3 className="spantitle">{title}</h3>
        {f && <span className="note">{one ? `day ${f.age_from}` : `days ${f.age_from} to ${f.age_to}`}</span>}
      </div>
      <p className="story">{span.story}</p>
      <div className="spantiles">
        <Tile k="Care" v={s.care != null ? String(s.care) : '–'} hero />
        <Tile k="Water" v={pct(s.water_ok)} sub={s.dry_minutes ? `dry ${s.dry_minutes} min` : 'never dry'} warn={(s.dry_minutes ?? 0) >= 10} />
        <Tile k="Comfort" v={pct(s.comfort)} sub={`cold ${pct(s.cold)} · hot ${pct(s.hot)}`} />
        <Tile k="Calm nights" v={pct(s.calm_nights)} />
        {f && <Tile k="Feed eaten" v={`${f.feed_kg} kg`} sub={`${f.feed_bags} bags · ${usd(f.feed_usd)}`} />}
        {f && <Tile k="Weight" v={one ? `${f.weight_to} kg` : `${f.weight_from} → ${f.weight_to}`} sub="kg a bird, estimated" />}
      </div>
      {span.grid.length > 0 && (
        <div className="spangrid"><span className="eyebrow">Hour by hour</span><WeekGrid grid={span.grid} /></div>
      )}
      <div className="spanlower">
        {span.frames.length > 0 && (
          <div className="moments">
            <span className="eyebrow">Moments</span>
            <div className="frames">
              {span.frames.map((fr, i) => fr.url && (
                <figure key={i}><img src={fr.url} alt="" /><figcaption>{fr.time}{fr.text ? ` · ${fr.text}` : ''}</figcaption></figure>
              ))}
            </div>
          </div>
        )}
        <div className="events">
          <span className="eyebrow">What happened</span>
          {events.length ? events.map((e, i) => (
            <p key={i} className={`ev ${e.k}`}><span className="t">{e.t}</span>{e.text}</p>
          )) : <p className="note">No records, alarms or calls in this stretch.</p>}
        </div>
      </div>
    </div>
  )
}

function Tile({ k, v, sub, warn, hero }: { k: string; v: string; sub?: string; warn?: boolean; hero?: boolean }) {
  return (
    <div className={`stile ${warn ? 'warn' : ''} ${hero ? 'hero' : ''}`}>
      <span className="eyebrow">{k}</span><span className="v">{v}</span>{sub && <span className="sub">{sub}</span>}
    </div>
  )
}

function planWords(w: string) {
  const [k, v] = w.split(':')
  if (k === 'vaccine') return `Planned: ${v}`
  if (k === 'feed') return `Planned: switch to ${v.toLowerCase()} feed`
  if (k === 'weigh') return 'Planned: weigh ten birds'
  if (k === 'sell') return 'Planned sell day'
  return w
}

function recWords(r: Span['records'][number]) {
  const q = r.quantity != null ? `${r.quantity} ${r.unit}`.trim() : ''
  const m = r.amount_usd != null ? usd(r.amount_usd, 2) : ''
  const word: Record<string, string> = { feed_bought: 'Bought feed', deaths: 'Birds lost', sold: 'Sold', weighed: 'Weighed', expense: 'Spent', vaccinated: 'Vaccinated', note: 'Note' }
  return [word[r.kind] ?? r.kind, q, m, r.note].filter(Boolean).join(' · ')
}

// ------------------------------------------------------------------ camera source

const SOURCE_WORDS: Record<string, string> = {
  phone: 'A coop phone is connected.',
  camera: 'An IP camera is connected through the Ziso bridge.',
  video: 'A video feed is connected. The coop reads it frame by frame, like a camera.',
  pairing: 'Waiting for a phone to scan the code, or a bridge to use the link.',
  none: 'Nothing is connected. The coop cannot see.',
}

const RED_FLAG_WORDS = 'A test tape plays on a loop: a bird down among the flock, then the house clear. The coop calls when it sees the bird, and closes the alarm when the floor is clear again. One call each 40-minute loop.'

export function SourcePanel({ coopId, source, canManage, onChange }: {
  coopId: string; source?: { type: string; label?: string; feed?: string }; canManage: boolean; onChange: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const type = source?.type ?? 'none'
  const feed = type === 'video' ? source?.feed ?? 'demo' : ''
  async function run(fn: () => Promise<unknown>) {
    setBusy(true); setErr('')
    try { await fn(); onChange() } catch (e: any) { setErr(e.message) } finally { setBusy(false) }
  }
  return (
    <div className={`source ${type}`}>
      <span className="eyebrow">Connected</span>
      <strong>{source?.label ?? (type === 'none' ? 'Nothing' : type)}</strong>
      <span className="note">{type === 'video' && feed === 'red_flag' ? RED_FLAG_WORDS : SOURCE_WORDS[type] ?? ''}</span>
      {canManage && (
        <div className="row" style={{ marginTop: 10 }}>
          {type !== 'none' && <button className="btn" disabled={busy} onClick={() => run(() => del(`/api/coops/${coopId}/source`))}>Disconnect</button>}
        </div>
      )}
      {err && <p className="error">{err}</p>}
    </div>
  )
}
