import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { send, speaker } from '../lib/controller'
import { live, useStore } from '../store'
import { Icon } from './Icon'

/**
 * Bolle delle nuove email: nascono dal cuore di AXEL e fluttuano di lato, trasparenti.
 * Icona: busta olografica; se esiste frontend/public/mail-icon.svg viene usata quella.
 */

export interface MailItem {
  key: number
  id: string
  from: string
  subject: string
  snippet: string
  link: string
  /** 'task' = compito in background completato */
  kind?: 'mail' | 'task'
}

function TaskIcon() {
  return (
    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" className="env-icon" aria-hidden>
      <circle cx="12" cy="12" r="8.5" />
      <path d="m8 12.3 2.6 2.6L16.2 9" />
      <circle cx="19" cy="6" r="2.6" className="env-dot" />
    </svg>
  )
}

const LIFE_MS = 32000
const TASK_LIFE_MS = 90000
let customIcon: boolean | null = null

function Envelope() {
  const [useCustom, setUseCustom] = useState(customIcon === true)
  useEffect(() => {
    if (customIcon !== null) return
    fetch('/mail-icon.svg', { method: 'HEAD' })
      .then((r) => {
        customIcon = r.ok && (r.headers.get('content-type') ?? '').includes('svg')
        setUseCustom(customIcon)
      })
      .catch(() => (customIcon = false))
  }, [])
  if (useCustom) return <img src="/mail-icon.svg" alt="" width={26} height={26} />
  return (
    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" className="env-icon" aria-hidden>
      <rect x="3" y="5.5" width="18" height="13" rx="2.2" />
      <path d="m3.8 7 8.2 6.2L20.2 7" />
      <circle cx="19" cy="6" r="2.6" className="env-dot" />
    </svg>
  )
}

async function openTask(id: string) {
  try {
    const t = await api.background(id)
    useStore.getState().set({ taskView: { title: t.title, text: t.result ?? '', status: t.status } })
  } catch {
    /* ignore */
  }
}

function Bubble({ m, slot, onDone }: { m: MailItem; slot: number; onDone: () => void }) {
  const [start] = useState(() => ({ x: live.heartScreen.x, y: live.heartScreen.y }))
  const [leaving, setLeaving] = useState(false)
  const weatherOpen = useStore((s) => !!s.widget)
  useEffect(() => {
    const life = m.kind === 'task' ? TASK_LIFE_MS : LIFE_MS
    const t1 = setTimeout(() => setLeaving(true), life)
    const t2 = setTimeout(onDone, life + 700)
    return () => {
      clearTimeout(t1)
      clearTimeout(t2)
    }
  }, [onDone, m.kind])
  const close = () => {
    setLeaving(true)
    setTimeout(onDone, 600)
  }
  const mobile = window.innerWidth < 760
  const W = mobile ? window.innerWidth - 32 : 320
  // se il widget meteo è aperto a destra, la bolla si affianca a sinistra del widget
  const tx = mobile ? 16 : window.innerWidth - W - 40 - (weatherOpen ? 346 : 0)
  const ty = (mobile ? 150 : 104) + slot * (mobile ? 92 : 104)
  return (
    <div
      className={`mail-bubble ${leaving ? 'leaving' : ''}`}
      style={
        {
          width: W,
          '--sx': `${start.x - W / 2}px`,
          '--sy': `${start.y - 30}px`,
          '--tx': `${tx}px`,
          '--ty': `${ty}px`,
          '--mx': `${(start.x + tx) / 2 + (mobile ? 0 : 60) - W / 2}px`,
          '--my': `${Math.min(start.y, ty) - 40}px`,
        } as React.CSSProperties
      }
    >
      <div className="mail-float" style={{ animationDelay: `${slot * 0.6}s` }}>
        <div className="mail-glow" />
        {m.kind === 'task' ? (
          <button className="mail-icon" title="Leggi il risultato" onClick={() => openTask(m.id)}>
            <TaskIcon />
          </button>
        ) : (
          <a className="mail-icon" href={m.link} target="_blank" rel="noreferrer" title="Apri in Gmail">
            <Envelope />
          </a>
        )}
        <div className="mail-text">
          <div className="mono label">{m.kind === 'task' ? 'compito completato' : 'nuova email'}</div>
          <b>{m.from}</b>
          <span>{m.subject}</span>
        </div>
        <div className="mail-actions">
          <button className="icon-btn sm" title={m.kind === 'task' ? 'Fammelo dire da AXEL' : 'Fammela leggere da AXEL'} onClick={() => {
            if (m.kind === 'task') {
              speaker.reset()
              speaker.push(`${m.from}. ${m.snippet} `)
              speaker.flush()
              openTask(m.id)
            } else send(`Leggimi e riassumimi l'email di ${m.from} con oggetto "${m.subject}"`)
            close()
          }}>
            <Icon name="volume" size={13} />
          </button>
          <button className="icon-btn sm" title="Chiudi" onClick={close}>
            <Icon name="close" size={13} />
          </button>
        </div>
      </div>
    </div>
  )
}

export function MailBubbles() {
  const items = useStore((s) => s.mailBubbles)
  const set = useStore((s) => s.set)
  const visible = items.slice(-3)
  return (
    <div className="mail-layer" aria-live="polite">
      {visible.map((m, i) => (
        <Bubble key={m.key} m={m} slot={i} onDone={() => set({ mailBubbles: useStore.getState().mailBubbles.filter((x) => x.key !== m.key) })} />
      ))}
    </div>
  )
}
