import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type SpotifyData } from '../lib/api'
import { useStore } from '../store'
import { Icon } from './Icon'

/**
 * Scheda Spotify olografica, nello stile del widget meteo: copertina dentro anelli rotanti,
 * equalizzatore, barra di avanzamento viva e comandi. Compare quando AXEL usa Spotify,
 * si aggiorna da sola mentre è aperta e svanisce dopo un po' (resta se ci passi sopra col mouse).
 */

const VISIBLE_MS = 40000
const POLL_MS = 5000

const fmt = (ms: number) => {
  const s = Math.max(0, Math.floor(ms / 1000))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

function Equalizer({ on }: { on: boolean }) {
  return (
    <div className={`sp-eq ${on ? 'on' : ''}`} aria-hidden>
      {Array.from({ length: 14 }, (_, i) => (
        <span key={i} style={{ animationDelay: `${(i * 137) % 900}ms`, animationDuration: `${700 + ((i * 211) % 600)}ms` }} />
      ))}
    </div>
  )
}

export function SpotifyHUD() {
  const music = useStore((s) => s.music)
  const weatherOpen = useStore((s) => !!s.widget)
  const set = useStore((s) => s.set)
  const [leaving, setLeaving] = useState(false)
  const [now, setNow] = useState(() => Date.now())
  const [busy, setBusy] = useState(false)
  const hover = useRef(false)
  const hideAt = useRef(0)

  const close = useCallback(() => {
    setLeaving(true)
    setTimeout(() => set({ music: null }), 650)
  }, [set])

  const apply = useCallback(
    (data: SpotifyData | null) => {
      if (!data) return
      set({ music: { data, at: Date.now() } })
    },
    [set],
  )

  // comparsa: riparte il conto alla rovescia a ogni nuovo brano/comando
  const key = music ? `${music.data.track}|${music.data.artists}` : ''
  useEffect(() => {
    if (!key) return
    setLeaving(false)
    hideAt.current = Date.now() + VISIBLE_MS
  }, [key])

  // orologio per la barra di avanzamento + auto-chiusura
  useEffect(() => {
    if (!music) return
    const iv = setInterval(() => {
      const t = Date.now()
      setNow(t)
      if (hover.current) hideAt.current = Math.max(hideAt.current, t + 8000)
      else if (t > hideAt.current) {
        clearInterval(iv)
        close()
      }
    }, 500)
    return () => clearInterval(iv)
  }, [music, close])

  // aggiornamento periodico (cambio brano, pausa dal telefono…)
  useEffect(() => {
    if (!music) return
    const iv = setInterval(() => {
      api.spotifyState().then((r) => r.data && apply(r.data)).catch(() => {})
    }, POLL_MS)
    return () => clearInterval(iv)
  }, [!!music, apply]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!music) return null
  const d = music.data
  const progress = Math.min(d.duration_ms, d.progress_ms + (d.is_playing ? now - music.at : 0))
  const pct = d.duration_ms ? (progress / d.duration_ms) * 100 : 0

  const control = async (action: string) => {
    if (busy) return
    setBusy(true)
    hideAt.current = Date.now() + VISIBLE_MS
    if (action === 'play' || action === 'pause') {
      // ottimistico: la UI risponde subito
      set({ music: { data: { ...d, is_playing: action === 'play', progress_ms: progress }, at: Date.now() } })
    }
    try {
      const r = await api.spotifyControl(action)
      if (r.data) apply(r.data)
      else if (r.message && !/ripresa|pausa|successivo|precedente/i.test(r.message)) useStore.getState().set({
        toasts: [...useStore.getState().toasts, { id: Date.now(), text: r.message, kind: 'error' }],
      })
    } catch {
      /* ignore */
    } finally {
      setBusy(false)
    }
  }

  return (
    <aside
      className={`hud-music ${weatherOpen ? 'beside' : ''} ${leaving ? 'leaving' : ''}`}
      key={music.at > 0 ? key : undefined}
      aria-label={`Spotify: ${d.track} di ${d.artists}`}
      onMouseEnter={() => (hover.current = true)}
      onMouseLeave={() => (hover.current = false)}
    >
      <span className="hb tl" />
      <span className="hb tr" />
      <span className="hb bl" />
      <span className="hb br" />
      <div className="hud-scan" />
      <header>
        <span className="mono label">
          <i className={`sp-live ${d.is_playing ? 'on' : ''}`} /> spotify · {d.is_playing ? 'in riproduzione' : 'in pausa'}
        </span>
        <span className="sp-head-btns">
          {d.url && (
            <a className="icon-btn sm" href={d.url} target="_blank" rel="noreferrer" title="Apri in Spotify">
              <Icon name="external" size={13} />
            </a>
          )}
          <button className="icon-btn sm" onClick={close} aria-label="Chiudi">
            <Icon name="close" size={14} />
          </button>
        </span>
      </header>

      <div className="sp-main">
        <div className={`sp-disc ${d.is_playing ? 'spinning' : ''}`}>
          <svg viewBox="0 0 120 120" className="ring-svg" aria-hidden>
            <circle cx="60" cy="60" r="56" className="r1" />
            <circle cx="60" cy="60" r="51" className="r2" />
            <circle cx="60" cy="60" r="46" className="r3" />
            <circle cx="60" cy="60" r="56" className="sp-arc" pathLength={100} style={{ strokeDasharray: `${pct} 100` }} />
          </svg>
          <div className="sp-art">
            {d.art ? <img src={d.art} alt="" /> : <div className="sp-art-empty">♪</div>}
            <span className="sp-hole" />
          </div>
        </div>
        <div className="sp-info">
          <div className="sp-track" title={d.track}>{d.track}</div>
          <div className="sp-artist">{d.artists}</div>
          {d.album && <div className="mono dim sp-album">{d.album}</div>}
          <Equalizer on={d.is_playing} />
        </div>
      </div>

      <div className="sp-progress">
        <span className="mono">{fmt(progress)}</span>
        <div className="sp-bar">
          <div className="sp-fill" style={{ width: `${pct}%` }} />
          <div className="sp-head" style={{ left: `${pct}%` }} />
        </div>
        <span className="mono dim">{fmt(d.duration_ms)}</span>
      </div>

      <div className="sp-controls">
        <button className="icon-btn sm" onClick={() => control('previous')} aria-label="Precedente" disabled={busy}>
          <Icon name="prev" size={14} />
        </button>
        <button className="sp-play" onClick={() => control(d.is_playing ? 'pause' : 'play')} aria-label={d.is_playing ? 'Pausa' : 'Riproduci'} disabled={busy}>
          <Icon name={d.is_playing ? 'pause' : 'play'} size={18} />
        </button>
        <button className="icon-btn sm" onClick={() => control('next')} aria-label="Successivo" disabled={busy}>
          <Icon name="next" size={14} />
        </button>
        <div className="sp-device">
          <span className="mono label">{d.device || 'dispositivo'}</span>
          {d.volume != null && (
            <span className="sp-vol" title={`Volume ${d.volume}%`}>
              {Array.from({ length: 10 }, (_, i) => (
                <i key={i} className={i < Math.round(d.volume! / 10) ? 'on' : ''} />
              ))}
            </span>
          )}
        </div>
      </div>
    </aside>
  )
}
