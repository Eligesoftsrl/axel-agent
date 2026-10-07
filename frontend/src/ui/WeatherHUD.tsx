import { useEffect, useState } from 'react'
import type { WeatherData } from '../lib/api'
import { useStore } from '../store'
import { Icon } from './Icon'

/** Widget meteo olografico in stile HUD: compare quando AXEL consulta il meteo e svanisce da solo. */

const GIORNI = ['dom', 'lun', 'mar', 'mer', 'gio', 'ven', 'sab']
const VISIBLE_MS = 45000

const CLOUD = 'M7 18h10.5a4 4 0 0 0 .4-7.98A6 6 0 0 0 6.3 9.3 4.4 4.4 0 0 0 7 18Z'

export function WeatherIcon({ kind, day = true, size = 64 }: { kind: string; day?: boolean; size?: number }) {
  const sun = (cx: number, cy: number, r: number) => (
    <g className="wx-sun">
      <circle cx={cx} cy={cy} r={r} />
      <g className="wx-rays" style={{ transformOrigin: `${cx}px ${cy}px` }}>
        {Array.from({ length: 8 }, (_, i) => {
          const a = (i / 8) * Math.PI * 2
          return (
            <line key={i} x1={cx + Math.cos(a) * (r + 1.6)} y1={cy + Math.sin(a) * (r + 1.6)} x2={cx + Math.cos(a) * (r + 3.4)} y2={cy + Math.sin(a) * (r + 3.4)} />
          )
        })}
      </g>
    </g>
  )
  const moon = (cx: number, cy: number) => <path className="wx-moon" d={`M${cx + 2} ${cy - 5}a5.5 5.5 0 1 0 4 8.6A4.6 4.6 0 0 1 ${cx + 2} ${cy - 5}Z`} />
  return (
    <svg className={`wx wx-${kind}`} width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      {kind === 'clear' && (day ? sun(12, 12, 4.2) : moon(10, 12))}
      {kind === 'partly' && (
        <>
          {day ? sun(8.5, 8.5, 3) : moon(6, 8)}
          <path className="wx-cloud drift" d={CLOUD} transform="translate(1.5 1.5) scale(0.9)" />
        </>
      )}
      {kind === 'cloudy' && (
        <>
          <path className="wx-cloud faint drift-slow" d={CLOUD} transform="translate(-3 -3) scale(0.8)" />
          <path className="wx-cloud drift" d={CLOUD} transform="translate(1 1) scale(0.92)" />
        </>
      )}
      {(kind === 'rain' || kind === 'storm' || kind === 'snow') && (
        <>
          <path className="wx-cloud" d={CLOUD} transform="translate(0 -3)" />
          {kind === 'rain' &&
            [8, 12, 16].map((x, i) => <line key={x} className="wx-drop" style={{ animationDelay: `${i * 0.25}s` }} x1={x} y1={17} x2={x - 1.2} y2={21} />)}
          {kind === 'snow' &&
            [8, 12, 16].map((x, i) => <circle key={x} className="wx-flake" style={{ animationDelay: `${i * 0.4}s` }} cx={x} cy={18} r={0.8} />)}
          {kind === 'storm' && <path className="wx-bolt" d="M12.5 15.5 10 19.5h2.6L11 23.5l4-5h-2.7l1.4-3Z" />}
        </>
      )}
      {kind === 'fog' && [9, 12.5, 16].map((y, i) => <line key={y} className="wx-fog" style={{ animationDelay: `${i * 0.5}s` }} x1={4} y1={y} x2={20} y2={y} />)}
    </svg>
  )
}

function Spark({ hours }: { hours: WeatherData['hourly'] }) {
  const pts = hours.slice(0, 13)
  if (pts.length < 2) return null
  const W = 280
  const H = 54
  const min = Math.min(...pts.map((p) => p.temp))
  const max = Math.max(...pts.map((p) => p.temp))
  const x = (i: number) => 8 + (i / (pts.length - 1)) * (W - 16)
  const y = (t: number) => 18 + (1 - (t - min) / Math.max(1, max - min)) * (H - 32)
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(p.temp).toFixed(1)}`).join(' ')
  return (
    <svg className="wx-spark" viewBox={`0 0 ${W} ${H + 14}`} width="100%" aria-hidden>
      {pts.map((p, i) => (
        <rect key={`r${i}`} x={x(i) - 3} y={H - (p.rain / 100) * 18} width={6} height={(p.rain / 100) * 18} className="wx-rainbar" />
      ))}
      <path d={`${line} L${x(pts.length - 1)} ${H} L${x(0)} ${H} Z`} className="wx-area" />
      <path d={line} className="wx-line" />
      {pts.map((p, i) =>
        i % 3 === 0 ? (
          <g key={i}>
            <circle cx={x(i)} cy={y(p.temp)} r={2.2} className="wx-dot" />
            <text x={x(i)} y={y(p.temp) - 6} textAnchor="middle" className="wx-t">{p.temp}°</text>
            <text x={x(i)} y={H + 12} textAnchor="middle" className="wx-h">{p.time}</text>
          </g>
        ) : null,
      )}
    </svg>
  )
}

export function WeatherHUD() {
  const widget = useStore((s) => s.widget)
  const set = useStore((s) => s.set)
  const [leaving, setLeaving] = useState(false)

  useEffect(() => {
    if (!widget) return
    setLeaving(false)
    const t1 = setTimeout(() => setLeaving(true), VISIBLE_MS)
    const t2 = setTimeout(() => set({ widget: null }), VISIBLE_MS + 900)
    return () => {
      clearTimeout(t1)
      clearTimeout(t2)
    }
  }, [widget, set])

  if (!widget || widget.kind !== 'weather') return null
  const w = widget.data
  const c = w.current
  const close = () => {
    setLeaving(true)
    setTimeout(() => set({ widget: null }), 600)
  }

  return (
    <aside className={`hud-weather ${leaving ? 'leaving' : ''}`} key={widget.at} aria-label={`Meteo ${w.city}`}>
      <span className="hb tl" />
      <span className="hb tr" />
      <span className="hb bl" />
      <span className="hb br" />
      <div className="hud-scan" />
      <header>
        <span className="mono label">meteo · {w.city}{w.region ? `, ${w.region}` : ''}</span>
        <button className="icon-btn sm" onClick={close} aria-label="Chiudi">
          <Icon name="close" size={14} />
        </button>
      </header>

      <div className="wx-main">
        <div className="wx-ring">
          <svg viewBox="0 0 120 120" className="ring-svg" aria-hidden>
            <circle cx="60" cy="60" r="54" className="r1" />
            <circle cx="60" cy="60" r="47" className="r2" />
            <circle cx="60" cy="60" r="40" className="r3" />
          </svg>
          <div className="wx-temp">
            {c.temp}
            <sup>°</sup>
          </div>
        </div>
        <div className="wx-side">
          <WeatherIcon kind={c.kind} day={c.is_day} size={74} />
          <div className="wx-desc">{c.desc}</div>
          <div className="mono dim">percepiti {c.feels}°</div>
        </div>
      </div>

      <div className="wx-stats">
        <div><span className="mono label">umidità</span>{c.humidity}%</div>
        <div><span className="mono label">vento</span>{c.wind} km/h</div>
        <div><span className="mono label">alba</span>{w.today.sunrise}</div>
        <div><span className="mono label">tramonto</span>{w.today.sunset}</div>
      </div>

      <div className="wx-section mono label">prossime ore</div>
      <Spark hours={w.hourly} />

      <div className="wx-days">
        {w.daily.slice(0, 4).map((d, i) => (
          <div key={d.date} className="wx-day">
            <span className="mono dim">{i === 0 ? 'oggi' : GIORNI[new Date(d.date).getDay()]}</span>
            <WeatherIcon kind={d.kind} size={30} />
            <span className="wx-mm">
              <b>{d.tmax}°</b> <em>{d.tmin}°</em>
            </span>
            <span className="mono dim rain">{d.rain}%</span>
          </div>
        ))}
      </div>
    </aside>
  )
}
