import { resolveAction } from '../lib/controller'
import { useStore } from '../store'

const LABEL: Record<string, string> = {
  gmail_send: 'Invio email',
  calendar_create_event: 'Nuovo evento',
  calendar_delete_event: 'Elimina evento',
  mac_trash: 'Sposta nel Cestino',
  mac_move: 'Sposta file',
  mac_run_command: 'Comando da terminale',
}

/** Schede di conferma per le azioni preparate da AXEL. */
export function ConfirmCards() {
  const pending = useStore((s) => s.pending)
  if (!pending.length) return null
  return (
    <div className="confirms">
      {pending.map((a) => (
        <div key={a.id} className="confirm-card">
          <div className="mono label">{LABEL[a.name] ?? a.name} · richiede conferma</div>
          <pre>{a.summary}</pre>
          <div className="row-between">
            <button className="pill ghost sm" onClick={() => resolveAction(a.id, false)}>
              Annulla
            </button>
            <button className="send" onClick={() => resolveAction(a.id, true)}>
              Conferma
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}

export function Toasts() {
  const toasts = useStore((s) => s.toasts)
  return (
    <div className="toasts" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast ${t.kind}`}>
          {t.text}
        </div>
      ))}
    </div>
  )
}
