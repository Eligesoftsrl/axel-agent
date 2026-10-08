import { useEffect, useRef, useState } from 'react'
import { boot, restoreHandsFree, send, setHandsFree, setInterimSink, speaker, startNotificationPolling, stop, toast, toggleListen } from './lib/controller'
import { handsFree } from './lib/handsfree'
import { playWakeup, preloadSounds, setSoundsMuted } from './lib/sounds'
import { sttSupported } from './lib/voice'
import { Scene } from './scene/Scene'
import { useStore } from './store'
import { Builder } from './ui/Builder'
import { History } from './ui/History'
import { Icon } from './ui/Icon'
import { Integrations } from './ui/Integrations'
import { Lyrics } from './ui/Lyrics'
import { ConfirmCards, Toasts } from './ui/Overlays'
import { WeatherHUD } from './ui/WeatherHUD'
import { MailBubbles } from './ui/MailBubbles'
import { SpotifyHUD } from './ui/SpotifyHUD'
import { Gallery } from './ui/Gallery'
import { ClipButton, DraftChips, DropZone, OutputsHUD, TaskViewHUD } from './ui/Attachments'

const STATE_LABEL = {
  idle: 'In attesa',
  listening: 'Ascolto',
  thinking: 'Elaborazione',
  speaking: 'Trasmissione',
} as const

export default function App() {
  const { state, activity, demo, set, handsFree: hf, handsFreeMode } = useStore()
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const agent = useStore((s) => s.current())
  const [input, setInput] = useState('')
  const [interim, setInterim] = useState('')
  const [muted, setMuted] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!menuOpen) return
    const close = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [menuOpen])

  useEffect(() => {
    boot()
    preloadSounds()
    playWakeup()
    setInterimSink(setInterim)
    restoreHandsFree()
    const iv = startNotificationPolling()
    // ritorno dal consenso Google
    const q = new URLSearchParams(location.search)
    for (const svc of ['google', 'spotify'] as const) {
      const v = q.get(svc)
      if (!v) continue
      const name = svc === 'google' ? 'Google' : 'Spotify'
      if (v === 'ok') toast(`${name} collegato ✓`, 'ok')
      else toast(`Collegamento ${name} non riuscito: ${q.get('msg') ?? ''}`, 'error')
      set({ integrationsOpen: true })
      history.replaceState(null, '', location.pathname)
    }
    return () => clearInterval(iv)
  }, [set])

  useEffect(() => {
    speaker.enabled = !muted
    setSoundsMuted(muted)
  }, [muted])

  const drafts = useStore((s) => s.drafts)
  const submit = (e?: React.FormEvent) => {
    e?.preventDefault()
    const ready = drafts.filter((d) => !d.uploading)
    if (!input.trim() && !ready.length) return
    send(input, ready)
    setInput('')
    set({ drafts: [] })
  }

  return (
    <div className="app" style={{ ['--a' as string]: agent?.accent ?? '#3ff0f7', ['--b' as string]: agent?.accent2 ?? '#1e7fe0' }}>
      <Scene />

      <div className="hud-frame" aria-hidden>
        <span className="corner tl" />
        <span className="corner tr" />
        <span className="corner bl" />
        <span className="corner br" />
      </div>

      <header className="topbar">
        <div className="brand">
          <span className="logo" />
          <div>
            <div className="brand-name">{agent?.name ?? 'AXEL'}</div>
            <div className="mono dim">agent studio · {agent?.model || 'default model'}</div>
          </div>
        </div>
        <div className="menu" ref={menuRef}>
          <button className={`icon-btn gear ${menuOpen ? 'open' : ''}`} onClick={() => setMenuOpen((v) => !v)} aria-label="Menu" aria-expanded={menuOpen}>
            <Icon name="gear" size={20} />
          </button>
          {menuOpen && (
            <div className="menu-pop" role="menu">
              <button role="menuitem" onClick={() => { set({ historyOpen: !useStore.getState().historyOpen }); setMenuOpen(false) }}>
                <Icon name="history" size={16} /> Cronologia
              </button>
              <button role="menuitem" onClick={() => { set({ integrationsOpen: true, builderOpen: false }); setMenuOpen(false) }}>
                <Icon name="plug" size={16} /> Integrazioni
              </button>
              <button role="menuitem" onClick={() => { set({ builderOpen: true, integrationsOpen: false }); setMenuOpen(false) }}>
                <Icon name="sliders" size={16} /> Costruisci agente
              </button>
            </div>
          )}
        </div>
      </header>

      <aside className="status">
        <div className={`ring ring-${state}`}>
          <span />
        </div>
        <div>
          <div className="mono label">stato</div>
          <div className="status-text">{STATE_LABEL[state]}</div>
          {hf && state === 'idle' && <div className="mono dim activity">{handsFreeMode === 'command' ? 'ti ascolto…' : 'di’ «Axel»'}</div>}
          {activity && <div className="mono dim activity">{activity}</div>}
          {demo && <div className="mono warn">modalità demo · nessuna API key</div>}
        </div>
      </aside>

      <Lyrics interim={interim} />
      <ConfirmCards />
      <WeatherHUD />
      <SpotifyHUD />
      <MailBubbles />
      <OutputsHUD />
      <TaskViewHUD />
      <Gallery />
      <DropZone />
      <DraftChips />

      <form className="composer" onSubmit={submit}>
        <button
          type="button"
          className={`icon-btn mic ${state === 'listening' ? 'on' : ''}`}
          title={sttSupported() ? 'Parla' : 'Riconoscimento vocale non supportato in questo browser'}
          disabled={!sttSupported()}
          onClick={() => toggleListen(setInterim)}
        >
          <Icon name="mic" />
        </button>
        <ClipButton />
        <input
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={`Scrivi a ${agent?.name ?? 'AXEL'}…`}
          aria-label="Messaggio"
        />
        {state === 'thinking' || state === 'speaking' ? (
          <button type="button" className="icon-btn" onClick={stop} title="Interrompi">
            <Icon name="stop" />
          </button>
        ) : (
          <button type="submit" className="send" disabled={!input.trim() && !drafts.some((d) => !d.uploading)}>
            Invia
          </button>
        )}
        <button
          type="button"
          className={`icon-btn ear ${hf ? 'on' : ''} ${hf && handsFreeMode === 'wake' ? 'idle' : ''}`}
          disabled={!handsFree.supported()}
          onClick={() => setHandsFree(!hf)}
          title={hf ? 'Mani libere attive: di’ «Axel» (clic per disattivare)' : 'Mani libere: attiva la parola «Axel»'}
        >
          <Icon name="ear" />
        </button>
        <button type="button" className="icon-btn" onClick={() => setMuted((m) => !m)} title={muted ? 'Attiva voce' : 'Silenzia voce'}>
          <Icon name={muted ? 'mute' : 'volume'} />
        </button>
      </form>

      <History />
      <Builder />
      <Integrations />
      <Toasts />
    </div>
  )
}
