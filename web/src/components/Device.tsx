import type { Device } from '../lib/api'

const WORD = { ok: 'Watching', warn: 'Check the phone', down: 'Phone offline' }

export function DevicePill({ d, onOpen }: { d: Device; onOpen: () => void }) {
  const bits = [
    d.battery != null ? `${d.battery}%${d.charging ? ' ⚡' : ''}` : null,
    d.network,
  ].filter(Boolean)
  return (
    <button className={`devpill ${d.level}`} onClick={onOpen} title={d.summary}>
      <span className="dot" />
      <span>{d.level === 'ok' ? WORD.ok : d.summary || WORD[d.level]}</span>
      {d.level === 'ok' && bits.length > 0 && <span className="bits">{bits.join(' · ')}</span>}
    </button>
  )
}

export function DeviceDetail({ d }: { d: Device }) {
  const icon = { ok: '●', warn: '▲', down: '■' }
  return (
    <div className="devdetail">
      {d.checks.map((c) => (
        <div key={c.name} className={`devcheck ${c.level}`}>
          <span className="ic" aria-label={c.level}>{icon[c.level]}</span>
          <span className="k">{c.name}</span>
          <span className="v">{c.text}</span>
        </div>
      ))}
      <p className="note">
        {d.frames} pictures read{d.resolution ? ` · camera ${d.resolution}` : ''}{d.version ? ` · app ${d.version}` : ''}.
        Keep the phone on a charger, out of direct sun, with the lens wiped.
      </p>
    </div>
  )
}
