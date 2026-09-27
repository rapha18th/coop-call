// Charts for the coop. States are validated for the dark surface: comfortable,
// cold and hot each carry a label in the legend and in every tooltip, and water
// or feed trouble is a marker inside the cell, so no reading depends on colour alone.

import { useState, type ReactNode } from 'react'
import { dayLabel, type Cell, type Day } from '../lib/api'

export const STATE = {
  fine: { color: 'var(--c-fine)', label: 'Comfortable' },
  cold: { color: 'var(--c-cold)', label: 'Huddled (cold)' },
  hot: { color: 'var(--c-hot)', label: 'Panting (hot)' },
  none: { color: 'transparent', label: 'No reading' },
} as const

type Tip = { x: number; y: number; body: ReactNode } | null

function Tooltip({ tip }: { tip: Tip }) {
  if (!tip) return null
  return (
    <div className="tip" style={{ left: tip.x, top: tip.y }}>
      {tip.body}
    </div>
  )
}

export function WeekGrid({ grid }: { grid: { day: string; hours: Cell[] }[] }) {
  const [tip, setTip] = useState<Tip>(null)
  return (
    <div className="weekgrid" onMouseLeave={() => setTip(null)}>
      <div className="wg-rows">
        {grid.map((row) => (
          <div className="wg-row" key={row.day}>
            <span className="wg-day">{dayLabel(row.day)}</span>
            <div className="wg-cells">
              {row.hours.map((c, h) => (
                <div
                  key={h}
                  className={`wg-cell ${c.state}`}
                  style={{ background: STATE[c.state].color }}
                  onMouseEnter={(e) => {
                    const r = (e.currentTarget.closest('.weekgrid') as HTMLElement).getBoundingClientRect()
                    const b = e.currentTarget.getBoundingClientRect()
                    setTip({
                      x: b.left - r.left + b.width / 2,
                      y: b.top - r.top,
                      body: (
                        <>
                          <strong>{dayLabel(row.day)} {String(h).padStart(2, '0')}:00</strong>
                          <span>{STATE[c.state].label}{c.birds != null ? ` · ${c.birds} birds` : ''}</span>
                          {c.water && <span>Drinker low</span>}
                          {c.feed && <span>Feeder low</span>}
                          {c.note && <span>Something unusual noted</span>}
                        </>
                      ),
                    })
                  }}
                >
                  {(c.water || c.feed) && <i className={c.water ? 'mk water' : 'mk feed'} />}
                </div>
              ))}
            </div>
          </div>
        ))}
        <div className="wg-row axis">
          <span className="wg-day" />
          <div className="wg-cells">
            {Array.from({ length: 24 }, (_, h) => (
              <span key={h} className="wg-hour">{h % 6 === 0 ? String(h).padStart(2, '0') : ''}</span>
            ))}
          </div>
        </div>
      </div>
      <div className="legend">
        {(['fine', 'cold', 'hot'] as const).map((k) => (
          <span key={k}><i style={{ background: STATE[k].color }} />{STATE[k].label}</span>
        ))}
        <span><i className="mk water inline" />Drinker low</span>
        <span><i className="mk feed inline" />Feeder low</span>
      </div>
      <Tooltip tip={tip} />
    </div>
  )
}

export function CareBars({ days }: { days: Day[] }) {
  const [tip, setTip] = useState<Tip>(null)
  const W = 320
  const H = 120
  const pad = 18
  const bw = (W - 8) / days.length
  return (
    <div className="carebars" onMouseLeave={() => setTip(null)}>
      <svg viewBox={`0 0 ${W} ${H + pad}`} role="img" aria-label="Care score by day">
        {[50, 100].map((g) => (
          <line key={g} x1={0} x2={W} y1={H - (H * g) / 100} y2={H - (H * g) / 100} className="grid" />
        ))}
        {days.map((d, i) => {
          const v = d.care ?? 0
          const h = Math.max(d.care != null ? 3 : 0, (H * v) / 100)
          const x = 4 + i * bw + bw * 0.22
          const w = bw * 0.56
          return (
            <g key={d.day}>
              <rect
                x={x - bw * 0.22} y={0} width={bw} height={H + pad} fill="transparent"
                onMouseEnter={(e) => {
                  const r = (e.currentTarget.ownerSVGElement!.parentElement as HTMLElement).getBoundingClientRect()
                  const b = e.currentTarget.getBoundingClientRect()
                  setTip({
                    x: b.left - r.left + b.width / 2, y: b.top - r.top + H - h,
                    body: d.care != null ? (
                      <>
                        <strong>{dayLabel(d.day)} · care {d.care}</strong>
                        <span>Water {pct(d.water_ok)} · feed {pct(d.feed_ok)}</span>
                        <span>Comfortable {pct(d.comfort)} · calm nights {pct(d.calm_nights)}</span>
                      </>
                    ) : <strong>{dayLabel(d.day)} · no readings</strong>,
                  })
                }}
              />
              {d.care != null && <path d={roundedTop(x, H - h, w, h, 4)} className="bar" />}
              <text x={x + w / 2} y={H + 13} className="axis-text" textAnchor="middle">{dayLabel(d.day)}</text>
            </g>
          )
        })}
      </svg>
      <Tooltip tip={tip} />
    </div>
  )
}

function roundedTop(x: number, y: number, w: number, h: number, r: number) {
  const rr = Math.min(r, w / 2, h)
  return `M${x},${y + h} V${y + rr} Q${x},${y} ${x + rr},${y} H${x + w - rr} Q${x + w},${y} ${x + w},${y + rr} V${y + h} Z`
}

export const pct = (v?: number) => (v == null ? '–' : `${Math.round(v * 100)}%`)
