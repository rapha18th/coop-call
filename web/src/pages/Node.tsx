// The coop phone. It watches, listens, and decides on the device what is worth
// sending: a frame when the scene changes or a minute passes, a heartbeat always.

import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { API } from '../lib/api'

const SAMPLE_MS = 5000
const BEAT_MS = 30000
const FRAME_EVERY_MS = 60000
const MOTION_TRIGGER = 7

type Seen = { summary?: string; birds?: number; drinker?: string; feeder?: string }

export default function NodePage() {
  const { coopId = '' } = useParams()
  const [key] = useState(() => {
    const fromHash = location.hash.slice(1)
    if (fromHash) {
      localStorage.setItem(`node:${coopId}`, fromHash)
      history.replaceState(null, '', location.pathname)
      return fromHash
    }
    return localStorage.getItem(`node:${coopId}`) ?? ''
  })
  const [running, setRunning] = useState(false)
  const [seen, setSeen] = useState<Seen | null>(null)
  const [stats, setStats] = useState({ frames: 0, beats: 0, motion: 0, sound: 0, light: 0 })
  const [error, setError] = useState('')
  const [gone, setGone] = useState(false)
  const video = useRef<HTMLVideoElement>(null)
  const stopRef = useRef(false)

  async function disconnect() {
    if (!confirm('Disconnect this phone from the coop? You will need a new code to connect again.')) return
    stopRef.current = true
    try {
      await fetch(`${API}/api/node/${coopId}/disconnect`, { method: 'POST', headers: { 'X-Node-Key': key } })
    } catch {}
    try { localStorage.removeItem(`node:${coopId}`) } catch {}
    const s = video.current?.srcObject as MediaStream | null
    s?.getTracks().forEach((t) => t.stop())
    setRunning(false)
    setGone(true)
  }

  async function start(file?: File) {
    setError('')
    try {
      const v = video.current!
      let audio: MediaStream | null = null
      if (file) {
        v.srcObject = null
        v.src = URL.createObjectURL(file)
        v.loop = true
        v.muted = true
      } else {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: 'environment', width: { ideal: 1280 } },
          audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
        })
        v.srcObject = stream
        audio = stream
      }
      await v.play()
      try {
        await (navigator as any).wakeLock?.request('screen')
      } catch {}
      setRunning(true)
      loop(v, audio)
    } catch (e: any) {
      setError(e.message || 'Could not open the camera.')
    }
  }

  function loop(v: HTMLVideoElement, stream: MediaStream | null) {
    const small = document.createElement('canvas')
    small.width = 64
    small.height = 48
    const sctx = small.getContext('2d', { willReadFrequently: true })!
    const big = document.createElement('canvas')
    let prev: Uint8ClampedArray | null = null
    let motionSince = 0
    let lastFrame = 0
    let lastBeat = 0
    let analyser: AnalyserNode | null = null
    if (stream) {
      const ctx = new AudioContext()
      analyser = ctx.createAnalyser()
      analyser.fftSize = 2048
      ctx.createMediaStreamSource(stream).connect(analyser)
    }
    const buf = new Float32Array(2048)

    const tick = async () => {
      if (stopRef.current) return
      sctx.drawImage(v, 0, 0, 64, 48)
      const px = sctx.getImageData(0, 0, 64, 48).data
      let light = 0
      let diff = 0
      for (let i = 0; i < px.length; i += 4) {
        const g = (px[i] + px[i + 1] + px[i + 2]) / 3
        light += g
        if (prev) diff += Math.abs(g - (prev[i] + prev[i + 1] + prev[i + 2]) / 3)
      }
      const n = px.length / 4
      // Sharpness: mean difference between horizontal neighbours. A blocked or smeared lens reads low.
      let edge = 0
      for (let y = 0; y < 48; y++) {
        for (let x = 1; x < 64; x++) {
          const i = (y * 64 + x) * 4
          edge += Math.abs((px[i] + px[i + 1] + px[i + 2]) - (px[i - 4] + px[i - 3] + px[i - 2])) / 3
        }
      }
      const sharpness = edge / (48 * 63)
      prev = new Uint8ClampedArray(px)
      const brightness = light / n
      const motion = diff / n
      motionSince = Math.max(motionSince, motion)

      // A relative loudness from 0 to 100, from the mic's RMS.
      let sound: number | null = null
      if (analyser) {
        analyser.getFloatTimeDomainData(buf)
        let s = 0
        for (const x of buf) s += x * x
        sound = Math.max(0, Math.min(100, 20 * Math.log10(Math.sqrt(s / buf.length) + 1e-9) + 100))
      }
      const battery = await (navigator as any).getBattery?.().catch(() => null)
      const sensors = {
        brightness,
        motion,
        sharpness,
        sound_db: sound,
        battery: battery?.level ?? null,
        charging: battery?.charging ?? null,
        network: (navigator as any).connection?.effectiveType ?? null,
        width: v.videoWidth || null,
        height: v.videoHeight || null,
        camera: stream ? 'on' : 'file',
        version: '0.3',
      }
      setStats((s) => ({ ...s, motion: Math.round(motion * 10) / 10, sound: Math.round(sound ?? 0), light: Math.round(brightness) }))

      const now = Date.now()
      const wantFrame = now - lastFrame > FRAME_EVERY_MS || (motionSince > MOTION_TRIGGER && now - lastFrame > 15000)
      try {
        if (wantFrame) {
          big.width = 800
          big.height = Math.round((800 * v.videoHeight) / Math.max(1, v.videoWidth))
          big.getContext('2d')!.drawImage(v, 0, 0, big.width, big.height)
          const blob: Blob = await new Promise((r) => big.toBlob((b) => r(b!), 'image/jpeg', 0.72))
          const form = new FormData()
          form.append('image', blob, 'frame.jpg')
          form.append('sensors', JSON.stringify({ ...sensors, motion: motionSince }))
          const res = await fetch(`${API}/api/node/${coopId}/frame`, { method: 'POST', body: form, headers: { 'X-Node-Key': key } })
          if (res.status === 403) throw new Error('This phone is not paired. Scan the code on the dashboard again.')
          const out = await res.json()
          if (out.analysed) setSeen(out.seen)
          lastFrame = now
          lastBeat = now
          motionSince = 0
          setStats((s) => ({ ...s, frames: s.frames + 1 }))
        } else if (now - lastBeat > BEAT_MS) {
          const res = await fetch(`${API}/api/node/${coopId}/beat`, {
            method: 'POST', body: JSON.stringify(sensors),
            headers: { 'X-Node-Key': key, 'Content-Type': 'application/json' },
          })
          if (res.status === 403) throw new Error('This phone is not paired. Scan the code on the dashboard again.')
          lastBeat = now
          setStats((s) => ({ ...s, beats: s.beats + 1 }))
        }
        setError('')
      } catch (e: any) {
        setError(e.message || 'No connection. Still watching.')
      }
      setTimeout(tick, SAMPLE_MS)
    }
    tick()
  }

  useEffect(() => {
    if (!key) setError('This phone has no pairing key. Scan the code on the coop dashboard.')
  }, [key])

  return (
    <div className="node">
      <video ref={video} playsInline muted />
      <div className="hud">
        <div className="eye">
          <span className={`pulse ${running ? '' : 'off'}`} />
          <span className="label">Ziso · coop phone {running ? 'watching' : 'idle'}</span>
        </div>
        <div>
          <p className="seen">{seen?.summary ?? 'The first reading appears here within a minute.'}</p>
          <p className="stats">
            {stats.frames} frames · {stats.beats} heartbeats · light {stats.light} · sound {stats.sound} · motion {stats.motion}
          </p>
          {error && <p className="error">{error}</p>}
          {running && <button className="quiet-link" style={{ marginTop: 10 }} onClick={disconnect}>Disconnect this phone</button>}
        </div>
      </div>
      {gone && (
        <div className="start">
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16, padding: 16, textAlign: 'center' }}>
            <p className="tagline">Disconnected. To connect again, scan a new pairing code from the coop's Camera sheet.</p>
          </div>
        </div>
      )}
      {!running && (
        <div className="start">
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 24, padding: 16, textAlign: 'center' }}>
            <p className="tagline">Point this phone at the birds, the feeder and the drinker. Keep it on a charger.</p>
            <button className="lamp" onClick={() => start()} disabled={!key}>Start watching</button>
            <label className="quiet-link" style={{ cursor: 'pointer' }}>
              Use a video of a coop instead
              <input type="file" accept="video/*" hidden onChange={(e) => e.target.files?.[0] && start(e.target.files[0])} />
            </label>
            {error && <p className="error">{error}</p>}
          </div>
        </div>
      )}
    </div>
  )
}
