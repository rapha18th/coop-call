import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import QRCode from 'qrcode'
import type { User } from 'firebase/auth'
import { DEMO_COOP, api, post, signIn, watchUser, type Alarm, type State } from '../lib/api'
import { CoopCall, type CallStatus, type Evidence } from '../lib/call'
import { letCoopCall, pushSupported } from '../lib/push'
import { Calls, Metrics, TeamPanel } from '../components/Panels'

const STATUS_WORDS: Record<CallStatus, string> = {
  idle: '',
  connecting: 'Ringing the coop',
  listening: 'Listening',
  thinking: 'Checking the timeline',
  speaking: 'The coop is speaking',
  ended: 'Call ended',
  error: 'The line dropped',
}

export default function CoopPage() {
  const params = useParams()
  const [search] = useSearchParams()
  const coopId = params.coopId ?? search.get('coop') ?? DEMO_COOP
  const incomingAlarm = search.get('alarm')

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
  const call = useRef<CoopCall | null>(null)
  const live = status === 'connecting' || status === 'listening' || status === 'thinking' || status === 'speaking'

  useEffect(() => watchUser(setUser), [])

  const refresh = useCallback(() => {
    api<State>(`/api/coops/${coopId}/state`).then(setState).catch((e) => setLoadError(e.message))
  }, [coopId])

  useEffect(() => {
    if (user === undefined) return
    refresh()
    const t = setInterval(refresh, 15000)
    return () => clearInterval(t)
  }, [user, refresh])

  function startCall(alarmId?: string) {
    setRinging(false)
    setEvidence(null)
    setYou('')
    setCoopSaid('')
    setDetail('')
    const c = new CoopCall(coopId, {
      status: (s, d) => {
        setStatus(s)
        if (d) setDetail(d)
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

  const frame = evidence?.frame_url ?? state?.now.frame_url
  const frameTime = evidence?.time ?? state?.now.frame_time
  const frameText = evidence?.description ?? state?.now.camera

  return (
    <div className="shell">
      <header className="top">
        <Link to="/" className="mark">Coop Call</Link>
        <span className="name">
          {state?.coop.name ?? ' '}
          {state?.now.note && <span className="badge">{state.now.note}</span>}
        </span>
        {user && <Link to="/farm" className="quiet-link">Your farm</Link>}
        {user === null && <button className="quiet-link" onClick={() => signIn()}>Sign in</button>}
      </header>

      {loadError && !state && <p className="error">{loadError}</p>}

      <div className="grid">
        <section>
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
              {!you && !coopSaid && !live && (
                <span className="note">Try: How did the birds sleep? Is the water okay? Show me the drinker.</span>
              )}
            </div>
          </div>
        </section>

        <aside>
          <div className="panel">
            <div className="label">Now · {state?.now.local_time ?? ''}</div>
            <p className="now-text" style={{ marginTop: 8 }}>{state?.now.camera ?? 'Loading the coop.'}</p>
            {state?.now.sensors && <p className="now-sub">{state.now.sensors}</p>}
          </div>

          {!!state?.alarms.length && (
            <div className="panel">
              <div className="label" style={{ marginBottom: 6 }}>Needs you</div>
              {state.alarms.map((a) => (
                <AlarmRow key={a.id} alarm={a} onAnswer={() => startCall(a.id)} />
              ))}
            </div>
          )}

          {state && ['owner', 'keeper', 'admin'].includes(state.role) && (
            <OwnerTools coopId={coopId} canPair={state.owner} onChange={refresh} />
          )}
        </aside>
      </div>

      <Metrics coopId={coopId} refreshKey={refreshKey} />

      <div className="grid lower">
        <Calls coopId={coopId} refreshKey={refreshKey} />
        {user && state && state.role !== 'public' && <TeamPanel coopId={coopId} />}
      </div>

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

function AlarmRow({ alarm, onAnswer }: { alarm: Alarm; onAnswer: () => void }) {
  return (
    <div className="alarm">
      <span className="dot" />
      <span className="msg">{alarm.message}</span>
      <span className="when">{alarm.time}</span>
      <button className="btn" onClick={onAnswer}>Ask</button>
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

  async function pair() {
    setErr('')
    try {
      const { node_key } = await post(`/api/coops/${coopId}/node-key`)
      await showPair(node_key)
    } catch (e: any) {
      setErr(e.message)
    }
  }

  async function subscribe() {
    setErr('')
    try {
      await letCoopCall(coopId)
      setMsg('This phone will ring when the coop needs you.')
    } catch (e: any) {
      setErr(e.message)
    }
  }

  async function ringNow() {
    setErr('')
    try {
      await post(`/api/coops/${coopId}/alarms/test`, { kind: 'drinker_empty' })
      setMsg('Ringing your phone now.')
      onChange()
    } catch (e: any) {
      setErr(e.message)
    }
  }

  return (
    <div className="panel">
      <div className="label" style={{ marginBottom: 10 }}>Keeping watch</div>
      <div className="row">
        {canPair && <button className="btn" onClick={pair}>Pair a coop phone</button>}
        {pushSupported() && <button className="btn" onClick={subscribe}>Let the coop call me</button>}
        <button className="btn" onClick={ringNow}>Test a call from the coop</button>
      </div>
      {qr && (
        <>
          <p className="note">Open this on the phone that will live in the coop. It becomes the coop's eyes and ears.</p>
          <img className="qr" src={qr} alt="Pairing code" />
          <p className="mono-break">{pairUrl}</p>
        </>
      )}
      {msg && <p className="note">{msg}</p>}
      {err && <p className="error">{err}</p>}
    </div>
  )
}
