import { useEffect, useRef } from 'react'
import { useStore } from '../store'
import { Icon } from './Icon'

export function History() {
  const { historyOpen, messages, partial, state, set } = useStore()
  const agent = useStore((s) => s.current())
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length, partial])

  return (
    <aside className={`panel history ${historyOpen ? 'open' : ''}`}>
      <div className="panel-head">
        <h2>Cronologia</h2>
        <button className="icon-btn" onClick={() => set({ historyOpen: false })} aria-label="Chiudi">
          <Icon name="close" />
        </button>
      </div>
      <div className="msgs">
        {messages.length === 0 && <p className="dim">Nessun messaggio. Scrivi o premi il microfono.</p>}
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            <div className="mono who">{m.role === 'user' ? 'tu' : agent?.name}</div>
            <div>{m.content}</div>
            {!!m.tools?.length && <div className="mono dim tools-used">⟡ {m.tools.join(' · ')}</div>}
          </div>
        ))}
        {state !== 'idle' && partial && (
          <div className="msg assistant streaming">
            <div className="mono who">{agent?.name}</div>
            <div>{partial}</div>
          </div>
        )}
        <div ref={end} />
      </div>
      {messages.length > 0 && (
        <button className="pill ghost" onClick={() => set({ messages: [], partial: '' })}>
          Nuova conversazione
        </button>
      )}
    </aside>
  )
}
