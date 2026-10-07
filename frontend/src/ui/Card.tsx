import { createContext, useContext, useEffect, useRef, type ReactNode } from 'react'
import { Icon } from './Icon'

/**
 * Scheda richiudibile del pannello Integrazioni: chiusa mostra una sola riga (nome, stato, riassunto),
 * aperta il contenuto. Una sola scheda aperta alla volta per restare compatti.
 */

export type Status = 'on' | 'warn' | 'off' | 'none'

interface Accordion {
  openId: string
  setOpen: (id: string) => void
}
export const AccordionCtx = createContext<Accordion>({ openId: '', setOpen: () => {} })

export function Card({ id, title, summary, status = 'none', right, children }: {
  id: string
  title: string
  summary?: ReactNode
  status?: Status
  /** elemento sempre visibile a destra (es. interruttore), non apre la scheda */
  right?: ReactNode
  children: ReactNode
}) {
  const { openId, setOpen } = useContext(AccordionCtx)
  const open = openId === id
  const ref = useRef<HTMLElement>(null)
  useEffect(() => {
    // all'apertura tiene la scheda in vista (le altre si chiudono e il contenuto sopra si accorcia)
    if (open) requestAnimationFrame(() => ref.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }))
  }, [open])
  return (
    <section ref={ref} className={`card fold ${open ? 'open' : ''}`}>
      <header>
        <button type="button" className="fold-head" onClick={() => setOpen(open ? '' : id)} aria-expanded={open}>
          <span className={`dot ${status === 'on' ? 'on' : status === 'warn' ? 'warn' : status === 'none' ? 'ghost' : ''}`} />
          <b>{title}</b>
          {summary != null && <span className="fold-sum">{summary}</span>}
          <span className="fold-chev"><Icon name="chev" size={14} /></span>
        </button>
        {right && <span className="fold-right">{right}</span>}
      </header>
      {open && <div className="fold-body">{children}</div>}
    </section>
  )
}

/** Etichetta di pulsante che non cambia larghezza quando passa a "in corso…" (niente salti nel pannello). */
export function BusyLabel({ busy, text, busyText }: { busy: boolean; text: string; busyText: string }) {
  return (
    <span className="busy-label">
      <span style={{ visibility: busy ? 'hidden' : 'visible' }}>{text}</span>
      <span style={{ visibility: busy ? 'visible' : 'hidden' }}>{busyText}</span>
    </span>
  )
}
