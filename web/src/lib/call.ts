// A browser call to the coop over AssemblyAI's Voice Agent API.
// Audio worklets follow AssemblyAI's voice-agent-starter-js: 24 kHz PCM16 both
// ways, a ring buffer for playback so barge-in can empty it at once.

import { api, post } from './api'

const WIRE_RATE = 24_000

const CAPTURE_WORKLET = `
class CaptureProcessor extends AudioWorkletProcessor {
  constructor() { super(); this._ratio = sampleRate / ${WIRE_RATE}; this._pos = 0; this._prev = 0; this._src = null; this._out = null; }
  _toPcm(s, len) { const p = new Int16Array(len); for (let i = 0; i < len; i++) { const v = Math.max(-1, Math.min(1, s[i])); p[i] = v < 0 ? v * 0x8000 : v * 0x7fff; } return p; }
  process(inputs) {
    const ch = inputs[0]?.[0]; if (!ch) return true;
    let level = 0; for (let i = 0; i < ch.length; i++) level += ch[i] * ch[i];
    if (this._ratio === 1) { const p = this._toPcm(ch, ch.length); this.port.postMessage({ pcm: p.buffer, level: level / ch.length }, [p.buffer]); return true; }
    const n = ch.length;
    if (!this._src || this._src.length < n + 1) { this._src = new Float32Array(n + 1); this._out = new Float32Array(Math.ceil((n + 1) / this._ratio) + 2); }
    const src = this._src, out = this._out; src[0] = this._prev; src.set(ch, 1);
    let len = 0, pos = this._pos;
    while (pos < n) { const i = Math.floor(pos), f = pos - i; out[len++] = src[i] + (src[i + 1] - src[i]) * f; pos += this._ratio; }
    this._pos = pos - n; this._prev = ch[n - 1];
    if (len) { const p = this._toPcm(out, len); this.port.postMessage({ pcm: p.buffer, level: level / n }, [p.buffer]); }
    return true;
  }
}
registerProcessor('capture', CaptureProcessor);`

const PLAYBACK_WORKLET = `
class PlaybackProcessor extends AudioWorkletProcessor {
  constructor() {
    super(); this._ring = new Float32Array(sampleRate * 30); this._w = 0; this._r = 0; this._n = 0;
    this._step = ${WIRE_RATE} / sampleRate; this._rsPos = 0; this._rsPrev = 0; this._drained = false;
    this.port.onmessage = (e) => {
      if (e.data === 'stop') { this._w = this._r = this._n = 0; this._rsPos = this._rsPrev = 0; return; }
      const x = new Int16Array(e.data); if (!x.length) return;
      if (this._drained) { this._rsPrev = 0; this._rsPos = 0; this._drained = false; }
      if (this._step === 1) { for (let i = 0; i < x.length; i++) this._push(x[i] / 32768); return; }
      const n = x.length; let pos = this._rsPos;
      while (pos < n) { const i = Math.floor(pos), f = pos - i; const a = i === 0 ? this._rsPrev : x[i - 1] / 32768; const b = x[i] / 32768; this._push(a + (b - a) * f); pos += this._step; }
      this._rsPos = pos - n; this._rsPrev = x[n - 1] / 32768;
    };
  }
  _push(v) { if (this._n < this._ring.length) { this._ring[this._w] = v; this._w = (this._w + 1) % this._ring.length; this._n++; } }
  process(inputs, outputs) {
    const o = outputs[0], out = o[0]; let level = 0;
    for (let i = 0; i < out.length; i++) {
      if (this._n > 0) { out[i] = this._ring[this._r]; this._r = (this._r + 1) % this._ring.length; this._n--; level += out[i] * out[i]; }
      else { out[i] = 0; this._drained = true; }
    }
    for (let c = 1; c < o.length; c++) o[c].set(out);
    this.port.postMessage(level / out.length);
    return true;
  }
}
registerProcessor('playback', PlaybackProcessor);`

export type CallStatus = 'idle' | 'connecting' | 'listening' | 'thinking' | 'speaking' | 'ended' | 'error'

export type Evidence = { time?: string; frame_url?: string | null; description?: string; tool: string }

export type Line = { who: 'you' | 'coop'; text: string; partial?: boolean }

export type CallEvents = {
  status: (s: CallStatus, detail?: string) => void
  line: (l: Line) => void
  evidence: (e: Evidence) => void
  level: (you: number, coop: number) => void
}

async function worklet(ctx: AudioContext, code: string, name: string) {
  const url = URL.createObjectURL(new Blob([code], { type: 'application/javascript' }))
  try {
    await ctx.audioWorklet.addModule(url)
  } finally {
    URL.revokeObjectURL(url)
  }
  return new AudioWorkletNode(ctx, name)
}

function toBase64(buf: ArrayBuffer) {
  const bytes = new Uint8Array(buf)
  let bin = ''
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000) as any)
  return btoa(bin)
}

export class CoopCall {
  private ws?: WebSocket
  private capCtx?: AudioContext
  private playCtx?: AudioContext
  private playback?: AudioWorkletNode
  private mic?: MediaStream
  private ready = false
  private lastType = ''
  private pending: { call_id: string; result: string }[] = []
  private youLevel = 0
  private coopLevel = 0

  constructor(private coopId: string, private on: CallEvents) {}

  async start(alarmId?: string) {
    this.on.status('connecting')
    try {
      const { token, session } = await post<{ token: string; session: any }>(
        `/api/coops/${this.coopId}/call`, { alarm_id: alarmId ?? null })

      this.capCtx = new AudioContext({ sampleRate: WIRE_RATE })
      this.playCtx = new AudioContext({ sampleRate: WIRE_RATE })
      await Promise.all([this.capCtx.resume(), this.playCtx.resume()])
      this.playback = await worklet(this.playCtx, PLAYBACK_WORKLET, 'playback')
      this.playback.connect(this.playCtx.destination)
      this.playback.port.onmessage = ({ data }) => {
        this.coopLevel = data
        this.on.level(this.youLevel, this.coopLevel)
      }
      this.mic = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: false, autoGainControl: false },
      })
      const capture = await worklet(this.capCtx, CAPTURE_WORKLET, 'capture')
      this.capCtx.createMediaStreamSource(this.mic).connect(capture)

      const url = new URL('wss://agents.assemblyai.com/v1/ws')
      url.searchParams.set('token', token)
      const ws = (this.ws = new WebSocket(url))

      capture.port.onmessage = ({ data }) => {
        this.youLevel = data.level
        this.on.level(this.youLevel, this.coopLevel)
        if (!this.ready || ws.readyState !== 1) return
        ws.send(JSON.stringify({ type: 'input.audio', audio: toBase64(data.pcm) }))
      }
      ws.onopen = () => ws.send(JSON.stringify({ type: 'session.update', session }))
      ws.onmessage = ({ data }) => this.handle(JSON.parse(data))
      ws.onclose = () => this.cleanup('ended')
      ws.onerror = () => this.cleanup('error', 'The line dropped.')
    } catch (err: any) {
      this.cleanup('error', err?.message || 'Could not start the call.')
    }
  }

  private handle(msg: any) {
    this.lastType = msg.type
    switch (msg.type) {
      case 'session.ready':
        this.ready = true
        this.on.status('listening')
        break
      case 'input.speech.started':
        this.playback?.port.postMessage('stop')
        this.on.status('listening')
        break
      case 'reply.started':
        this.on.status('speaking')
        break
      case 'reply.audio': {
        const raw = atob(msg.data)
        const bytes = new Uint8Array(raw.length)
        for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i)
        this.playback?.port.postMessage(bytes.buffer, [bytes.buffer])
        break
      }
      case 'reply.done':
        if (msg.status === 'interrupted') this.playback?.port.postMessage('stop')
        this.on.status('listening')
        this.flush()
        break
      case 'transcript.user.delta':
        this.on.line({ who: 'you', text: msg.text, partial: true })
        break
      case 'transcript.user':
        this.on.line({ who: 'you', text: msg.text })
        break
      case 'transcript.agent':
        this.on.line({ who: 'coop', text: msg.text })
        break
      case 'tool.call':
        this.on.status('thinking')
        this.runTool(msg.call_id, msg.name, msg.arguments ?? {})
        break
      case 'session.error':
        this.on.status('error', msg.message)
        break
      case 'session.ended':
        this.ws?.close()
        break
    }
  }

  private async runTool(callId: string, name: string, args: any) {
    let result: any
    try {
      result = await api(`/api/coops/${this.coopId}/tools/${name}`, { method: 'POST', body: JSON.stringify(args) })
      if (result?.frame_url) {
        this.on.evidence({ tool: name, frame_url: result.frame_url, time: result.time || result.frame_time,
          description: result.description || result.camera })
      }
      if (name === 'show_picture' && result?.found) result = { ...result, shown_on_screen: true }
      if (result && typeof result === 'object') delete result.frame_url
    } catch (err: any) {
      result = { error: err?.message || 'lookup failed' }
    }
    this.pending.push({ call_id: callId, result: JSON.stringify(result) })
    // Results go back only while reply.done is the latest event.
    if (this.lastType === 'reply.done') this.flush()
  }

  private flush() {
    if (!this.ws || this.ws.readyState !== 1) return
    while (this.pending.length) {
      const r = this.pending.shift()!
      this.ws.send(JSON.stringify({ type: 'tool.result', ...r }))
    }
  }

  stop() {
    if (this.ws?.readyState === 1) {
      this.ws.send(JSON.stringify({ type: 'session.end' }))
      const ws = this.ws
      setTimeout(() => ws.readyState === 1 && ws.close(), 2500)
    }
    this.cleanup('ended')
  }

  private cleanup(status: CallStatus, detail?: string) {
    this.playback?.port.postMessage('stop')
    this.mic?.getTracks().forEach((t) => t.stop())
    this.capCtx?.close().catch(() => {})
    this.playCtx?.close().catch(() => {})
    this.capCtx = this.playCtx = this.playback = this.mic = undefined
    this.ready = false
    this.on.status(status, detail)
    this.on.level(0, 0)
  }
}
