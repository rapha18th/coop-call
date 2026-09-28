import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import QRCode from 'qrcode'
import type { User } from 'firebase/auth'
import { DEMO_COOP, api, post, signIn, watchUser, type ActionButton, type Alarm, type State } from '../lib/api'
import { CoopCall, type CallStatus, type Evidence } from '../lib/call'
import { letCoopCall, pushSupported } from '../lib/push'
import { Calls, TeamPanel } from '../components/Panels'
import { Growth, MoneyCard, Records, Routine, SellPlan, SetupFlock } from '../components/Flock'
import { DeviceDetail, DevicePill } from '../components/Device'
import { Actions, CalendarSheet, SHEETS, Sheet, SourcePanel, StatusCard, Tabs, ThemeToggle } from '../components/Today'

const STATUS_WORDS: Record<CallStatus, string> = {
  idle: '',
  connecting: 'Ringing the coop',
  listening: 'Listening',
  thinking: 'Checking the records',
  speaking: 'The coop is speaking',
  ended: 'Call ended',
  error: 'The line dropped',
}

export default function CoopPage() {
  const params = useParams()
  const [search] = useSearchParams()
  const coopId = params.coopId ?? search.get('coop') ?? DEMO_COOP
  const [incomingAlarm, setIncomingAlarm] = useState<string | null>(search.get('alarm'))

  const [user, setUser] = useState<User | null | undefined>(undefined)
  const [state, setState] = useState<State | null>(null)
  const [loadError, setLoadError] = useState('')
  const [status, setStatus] = useState<CallStatus>('idle')
  const [detail, setDetail] = useState('')
  const [you, setYou] = useState('')
  const [coopSaid, setCoopSaid] = useState('')
  const [evidence, setEvidence] = useState<Evidence | null>(null)
  const [ringing, setRinging] = useState(Boolean(incomingAlarm))
  const [refreshKey, setRefreshKey] = useState(0)
  const [sheet, setSheet] = useState<string | null>(search.get('pair') ? 'phone' : null)
  const call = useRef<CoopCall | null>(null)
  const live = status === 'connecting' || status === 'listening' || status === 'thinking' || status === 'speaking'
  const liveRef = useRef(false)
  liveRef.current = live

  useEffect(() => watchUser(setUser), [])

  // Alarms already open when the page loads show in the to-do list. A new one rings here too,
  // so an open dashboard behaves like a phone.
  const known = useRef<Set<string> | null>(null)
  const refresh = useCallback(() => {
    api<State>(`/api/coops/${coopId}/state`).then((s) => {
      setState(s)
      setLoadError('')
      const ids = s.alarms.map((a) => a.id)
      if (known.current) {
        const fresh = s.alarms.find((a) => a.status === 'ringing' && !known.current!.has(a.id))
        if (fresh && !liveRef.current) { setIncomingAlarm(fresh.id); setRinging(true) }
      }
      known.current = new Set([...(known.current ?? []), ...ids])
    }).catch((e) => setLoadError(e.message))
  }, [coopId])

  useEffect(() => {
    if (user === undefined) return
    refresh()
    const t = setInterval(refresh, 20000)
    return () => clearInterval(t)
  }, [user, refresh])

  function startCall(alarmId?: string) {
    setRinging(false)
    setSheet(null)
    setEvidence(null)
    setYou('')
    setCoopSaid('')
    setDetail('')
    const c = new CoopCall(coopId, {
      status: (s, d) => {
        setStatus(s)
        if (d) setDetail(d)
        // The agent's words arrive when it finishes speaking; clear the last line as it starts.
        if (s === 'speaking') setCoopSaid('')
        if (s === 'ended' || s === 'error') {
          refresh()
          setTimeout(() => setRefreshKey((k) => k + 1), 1500)
        }
      },
      line: (l) => (l.who === 'you' ? setYou(l.text) : setCoopSaid(l.text)),
      evidence: (e) => setEvidence(e),
      level: () => {},
    })
    call.current = c
    c.start(alarmId)
  }

  useEffect(() => () => call.current?.stop(), [])

  const onAction = (b: ActionButton) => {
    if (b.do === 'call') startCall(b.alarm)
    if (b.do === 'open' && b.sheet) setSheet(b.sheet)
  }

  const f = state?.flock ?? null
  const manage = !!state && ['owner', 'admin'].includes(state.role)
  const canWrite = !!state && ['owner', 'keeper', 'admin', 'public'].includes(state.role)
  const frame = evidence?.frame_url ?? state?.now.frame_url
  const frameTime = evidence?.time ?? state?.now.frame_time
  const frameText = evidence?.description ?? state?.now.camera
  const hideSheets = [
    ...(f ? [] : ['growth', 'money', 'records']),
    ...(user && state && state.role !== 'public' ? [] : ['team']),
  ]
  const title = SHEETS.find(([k]) => k === sheet)?.[1] ?? ''

  return (
    <div className="shell coop">
      <header className="bar">
        <Link to="/" className="mark">Coop Call</Link>
        <span className="coopname">
          {state?.coop.name ?? ''}
          {state?.now.note && <span className="badge">{state.now.note}</span>}
        </span>
        <Tabs onOpen={setSheet} hide={hideSheets} open={sheet} />
        {state?.device && <DevicePill d={state.device} onOpen={() => setSheet('phone')} />}
        <ThemeToggle />
        {user && <Link to="/farm" className="quiet-link">Farm</Link>}
        {user === null && <button className="quiet-link" onClick={() => signIn()}>Sign in</button>}
      </header>

      {loadError && !state && <p className="error">{loadError}</p>}

      <main className="today">
        <section className="todaycol">
          <StatusCard today={state?.today} flock={f} onOpen={() => setSheet('calendar')} onSheet={setSheet} />
          {state && !f && manage && <SetupFlock coopId={coopId} onDone={refresh} />}
          {f?.inferred && <p className="inferred">Flock size and age estimated from the camera. <button className="quiet-link" onClick={() => setSheet('money')}>Correct them</button></p>}
          {state && (
            <Actions coopId={coopId} actions={state.today?.actions ?? []} onDo={onAction} onChange={refresh} />
          )}
        </section>

        <section className="eyecol">
          <div className="stage">
            {frame ? <img src={frame} alt="The coop" /> : <div className="empty">No picture yet. Pair a phone to give the coop its eyes.</div>}
            {evidence && <span className="evidence-tag">Evidence</span>}
            {frameText && (
              <div className="caption">
                {frameTime && <span className="when">{frameTime}</span>}
                {frameText}
              </div>
            )}
          </div>
          <div className="callbox">
            <button
              className={`lamp ${live ? 'live' : ''} ${state?.alarms.length && !live ? 'ember' : ''}`}
              onClick={() => (live ? call.current?.stop() : startCall())}
              disabled={status === 'connecting'}
            >
              {live ? 'End call' : 'Call the coop'}
            </button>
            <div className="status-line">{detail && status === 'error' ? detail : STATUS_WORDS[status]}</div>
            <div className="said">
              {you && <span className="you">You: {you}</span>}
              {coopSaid && <span className="coop">{coopSaid}</span>}
            </div>
          </div>
        </section>
      </main>


      {sheet === 'calendar' && <CalendarSheet coopId={coopId} onClose={() => setSheet(null)} />}
      {sheet && sheet !== 'calendar' && (
        <Sheet title={title} onClose={() => setSheet(null)} wide={sheet === 'growth' || sheet === 'money' || sheet === 'records'}>
          {sheet === 'growth' && f && <><Growth f={f} /><div className="sheetgap" /><Routine f={f} /></>}
          {sheet === 'money' && f && <><MoneyCard f={f} /><div className="sheetgap" /><SellPlan coopId={coopId} f={f} canEdit={manage} onSaved={refresh} /></>}
          {sheet === 'records' && f && <Records coopId={coopId} canWrite={canWrite} onChange={refresh} />}
          {sheet === 'calls' && <Calls coopId={coopId} refreshKey={refreshKey} />}
          {sheet === 'team' && <TeamPanel coopId={coopId} />}
          {sheet === 'phone' && state && (
            <>
              <SourcePanel coopId={coopId} source={state.source} canManage={manage} onChange={refresh} />
              <DeviceDetail d={state.device} />
              {state.now.sensors && <p className="note">{state.now.sensors}</p>}
              {['owner', 'keeper', 'admin'].includes(state.role) && (
                <OwnerTools coopId={coopId} canPair={state.owner} onChange={refresh} />
              )}
            </>
          )}
        </Sheet>
      )}

      {ringing && incomingAlarm && (
        <Incoming
          coopName={state?.coop.name ?? 'Your coop'}
          alarm={state?.alarms.find((a) => a.id === incomingAlarm)}
          onAnswer={() => startCall(incomingAlarm)}
          onDecline={() => setRinging(false)}
        />
      )}
    </div>
  )
}

function Incoming({ coopName, alarm, onAnswer, onDecline }: {
  coopName: string; alarm?: Alarm; onAnswer: () => void; onDecline: () => void
}) {
  return (
    <div className="incoming">
      <div className="label">Incoming call</div>
      <h1>{coopName}</h1>
      <p className="why">{alarm?.message ?? 'Your coop needs you.'}</p>
      <div className="choices">
        <button className="lamp small" onClick={onDecline} style={{ filter: 'grayscale(1) brightness(0.5)' }}>Later</button>
        <button className="lamp ringing" onClick={onAnswer}>Answer</button>
      </div>
    </div>
  )
}

function OwnerTools({ coopId, canPair, onChange }: { coopId: string; canPair: boolean; onChange: () => void }) {
  const [search] = useSearchParams()
  const [pairUrl, setPairUrl] = useState('')
  const [qr, setQr] = useState('')
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')

  const showPair = useCallback(async (key: string) => {
    const url = `${location.origin}/node/${coopId}#${key}`
    setPairUrl(url)
    setQr(await QRCode.toDataURL(url, { margin: 1, width: 220 }))
  }, [coopId])

  useEffect(() => {
    const key = sessionStorage.getItem(`node-key:${coopId}`)
    if (key && search.get('pair')) showPair(key)
  }, [coopId, search, showPair])

  async function run(fn: () => Promise<unknown>, ok: string) {
    setErr('')
    try {
      await fn()
      setMsg(ok)
    } catch (e: any) {
      setErr(e.message)
    }
  }

  return (
    <div className="ownertools">
      <div className="row">
        {canPair && <button className="btn" onClick={() => run(async () => showPair((await post(`/api/coops/${coopId}/node-key`)).node_key), '')}>Pair a phone or camera</button>}
        {pushSupported() && <button className="btn" onClick={() => run(() => letCoopCall(coopId), 'This phone will ring when the coop needs you.')}>Let the coop call me</button>}
        <button className="btn" onClick={() => run(async () => { await post(`/api/coops/${coopId}/alarms/test`, { kind: 'drinker_empty' }); onChange() }, 'Ringing your phone now.')}>Test a call from the coop</button>
      </div>
      {qr && (
        <>
          <p className="note">Scan this with the phone that will live in the coop. For an IP camera, give this link to the Ziso bridge.</p>
          <img className="qr" src={qr} alt="Pairing code" />
          <p className="mono-break">{pairUrl}</p>
        </>
      )}
      {msg && <p className="note">{msg}</p>}
      {err && <p className="error">{err}</p>}
    </div>
  )
}
