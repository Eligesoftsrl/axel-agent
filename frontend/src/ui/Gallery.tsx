import { useCallback, useEffect, useRef, useState } from 'react'
import { useStore } from '../store'
import { Icon } from './Icon'

/**
 * Galleria olografica stile Cover Flow: la foto al centro di fronte, le altre inclinate ai lati con riflesso,
 * scorrimento orizzontale (frecce, rotella, trascinamento, voce: "avanti", "indietro", "chiudi").
 * Mentre è aperta AXEL si dissolve in particelle e ricompare alla chiusura.
 */

export interface GalleryData {
  id: string
  title: string
  path: string
  items: { i: number; name: string; folder: string; date: string }[]
}

const VISIBLE = 6 // carte per lato
const src = (g: GalleryData, i: number, big: boolean) => `/api/photos/${g.id}/${i}?size=${big ? 1600 : 480}`

/** comandi dalla voce o dal controller */
export const galleryNav = {
  go: (_d: number) => {},
  close: () => {},
  play: () => {},
}

export function Gallery() {
  const gallery = useStore((s) => s.gallery)
  const set = useStore((s) => s.set)
  const [index, setIndex] = useState(0)
  const [leaving, setLeaving] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [zoom, setZoom] = useState(false)
  const drag = useRef<{ x: number; start: number; moved: boolean } | null>(null)
  const wheelAt = useRef(0)
  const n = gallery?.data.items.length ?? 0

  useEffect(() => {
    setIndex(0)
    setLeaving(false)
    setPlaying(false)
    setZoom(false)
  }, [gallery?.at])

  const go = useCallback((d: number) => setIndex((i) => Math.max(0, Math.min(n - 1, i + d))), [n])
  const close = useCallback(() => {
    setLeaving(true)
    setPlaying(false)
    setTimeout(() => set({ gallery: null }), 650)
  }, [set])

  useEffect(() => {
    galleryNav.go = go
    galleryNav.close = close
    galleryNav.play = () => setPlaying(true)
  }, [go, close])

  // tastiera
  useEffect(() => {
    if (!gallery) return
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === 'INPUT' || (e.target as HTMLElement)?.tagName === 'TEXTAREA') return
      if (e.key === 'ArrowRight') go(1)
      else if (e.key === 'ArrowLeft') go(-1)
      else if (e.key === 'Escape') (zoom ? setZoom(false) : close())
      else if (e.key === ' ') {
        e.preventDefault()
        setPlaying((p) => !p)
      } else if (e.key === 'Enter') setZoom((z) => !z)
      else return
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [gallery, go, close, zoom])

  // presentazione automatica
  useEffect(() => {
    if (!playing || !n) return
    const iv = setInterval(() => setIndex((i) => (i + 1 >= n ? 0 : i + 1)), 4200)
    return () => clearInterval(iv)
  }, [playing, n])

  // precarica le versioni grandi vicine
  useEffect(() => {
    if (!gallery) return
    for (const d of [0, 1, -1, 2]) {
      const i = index + d
      if (i >= 0 && i < n) new Image().src = src(gallery.data, i, true)
    }
  }, [gallery, index, n])

  if (!gallery) return null
  const g = gallery.data
  const cur = g.items[index]

  const onWheel = (e: React.WheelEvent) => {
    const now = performance.now()
    if (now - wheelAt.current < 180) return
    const d = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY
    if (Math.abs(d) < 8) return
    wheelAt.current = now
    go(d > 0 ? 1 : -1)
  }
  const onDown = (e: React.PointerEvent) => {
    drag.current = { x: e.clientX, start: index, moved: false }
  }
  const onMove = (e: React.PointerEvent) => {
    if (!drag.current) return
    const steps = Math.round((drag.current.x - e.clientX) / 110)
    if (steps) drag.current.moved = true
    setIndex(Math.max(0, Math.min(n - 1, drag.current.start + steps)))
  }
  const onUp = () => {
    setTimeout(() => (drag.current = null), 0)
  }

  return (
    <div className={`gallery ${leaving ? 'leaving' : ''} ${zoom ? 'zoomed' : ''}`} role="dialog" aria-label={`Galleria ${g.title}`}
      onWheel={onWheel} onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerLeave={onUp}>
      <div className="gal-veil" onClick={() => !drag.current?.moved && close()} />
      <header className="gal-head">
        <span className="mono label">galleria · {g.title}</span>
        <span className="gal-count mono">{String(index + 1).padStart(2, '0')}<em> / {String(n).padStart(2, '0')}</em></span>
        <span className="gal-btns">
          <button className="icon-btn sm" onClick={() => setPlaying((p) => !p)} title={playing ? 'Pausa presentazione' : 'Presentazione'} aria-label="Presentazione">
            <Icon name={playing ? 'pause' : 'play'} size={14} />
          </button>
          <a className="icon-btn sm" href={src(g, index, true)} target="_blank" rel="noreferrer" title="Apri a piena risoluzione">
            <Icon name="external" size={13} />
          </a>
          <button className="icon-btn sm" onClick={close} aria-label="Chiudi galleria">
            <Icon name="close" size={14} />
          </button>
        </span>
      </header>

      <div className="gal-stage">
        {g.items.map((it) => {
          const d = it.i - index
          if (Math.abs(d) > VISIBLE) return null
          const side = Math.sign(d)
          const a = Math.abs(d)
          const x = d === 0 ? 0 : side * (60 + (a - 1) * 14) // in % della larghezza della carta centrale
          const style = {
            transform: `translateX(${x}%) translateZ(${d === 0 ? (zoom ? 120 : 0) : -260 - a * 30}px) rotateY(${d === 0 ? 0 : -side * 62}deg)`,
            zIndex: 100 - a,
            opacity: a > VISIBLE - 1 ? 0 : 1 - a * 0.08,
          } as React.CSSProperties
          return (
            <figure key={it.i} className={`gal-card ${d === 0 ? 'center' : ''}`} style={style}
              onClick={(e) => {
                e.stopPropagation()
                if (drag.current?.moved) return
                if (d === 0) setZoom((z) => !z)
                else setIndex(it.i)
              }}>
              <span className="hb tl" />
              <span className="hb tr" />
              <span className="hb bl" />
              <span className="hb br" />
              <img src={src(g, it.i, a <= 1)} alt={it.name} draggable={false} loading={a > 3 ? 'lazy' : 'eager'} />
              {d === 0 && <div className="gal-scan" />}
            </figure>
          )
        })}
      </div>

      <footer className="gal-foot">
        <div className="gal-caption">
          <b>{cur?.name}</b>
          <span className="mono dim">{[cur?.folder, cur?.date].filter(Boolean).join(' · ')}</span>
        </div>
        <div className="gal-scrub" onClick={(e) => {
          const r = (e.currentTarget as HTMLDivElement).getBoundingClientRect()
          setIndex(Math.round(((e.clientX - r.left) / r.width) * (n - 1)))
        }}>
          <div className="gal-fill" style={{ width: `${n > 1 ? (index / (n - 1)) * 100 : 100}%` }} />
          <div className="gal-knob" style={{ left: `${n > 1 ? (index / (n - 1)) * 100 : 100}%` }} />
        </div>
        <span className="mono dim gal-hint">← → scorri · invio ingrandisci · spazio presentazione · esc chiudi</span>
      </footer>
    </div>
  )
}
