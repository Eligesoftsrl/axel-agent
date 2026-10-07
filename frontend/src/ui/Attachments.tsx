import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import { toast } from '../lib/controller'
import { useStore } from '../store'
import { Icon } from './Icon'

/** Allegati: trascina un file ovunque nella finestra o usa la graffetta. */

const ACCEPT = '.pdf,.png,.jpg,.jpeg,.gif,.webp,.xlsx,.xls,.csv,.docx,.pptx,.txt,.md,.json'
const fmtSize = (n: number) => (n > 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1e3))} kB`)

export async function addFiles(files: FileList | File[]) {
  for (const f of Array.from(files)) {
    const temp = { id: `tmp-${Math.random().toString(36).slice(2)}`, name: f.name, kind: 'data' as const, size: f.size, uploading: true }
    useStore.getState().set({ drafts: [...useStore.getState().drafts, temp] })
    try {
      const a = await api.upload(f)
      useStore.getState().set({ drafts: useStore.getState().drafts.map((d) => (d.id === temp.id ? a : d)) })
    } catch (e) {
      useStore.getState().set({ drafts: useStore.getState().drafts.filter((d) => d.id !== temp.id) })
      toast(`${f.name}: ${(e as Error).message}`, 'error')
    }
  }
}

export function ClipButton() {
  const ref = useRef<HTMLInputElement>(null)
  return (
    <>
      <button type="button" className="icon-btn" title="Allega un file (PDF, Excel, CSV, immagini…)" onClick={() => ref.current?.click()}>
        <Icon name="clip" />
      </button>
      <input ref={ref} type="file" multiple accept={ACCEPT} hidden onChange={(e) => { if (e.target.files) void addFiles(e.target.files); e.target.value = '' }} />
    </>
  )
}

export function DraftChips() {
  const drafts = useStore((s) => s.drafts)
  const set = useStore((s) => s.set)
  if (!drafts.length) return null
  return (
    <div className="drafts">
      {drafts.map((d) => (
        <span key={d.id} className={`draft ${d.uploading ? 'up' : ''}`}>
          <Icon name="file" size={13} />
          <span className="draft-name">{d.name}</span>
          <em>{d.uploading ? 'carico…' : fmtSize(d.size)}</em>
          {!d.uploading && (
            <button type="button" aria-label="Rimuovi" onClick={() => set({ drafts: drafts.filter((x) => x.id !== d.id) })}>
              <Icon name="close" size={11} />
            </button>
          )}
        </span>
      ))}
    </div>
  )
}

export function DropZone() {
  const [over, setOver] = useState(false)
  useEffect(() => {
    let depth = 0
    const enter = (e: DragEvent) => {
      if (!e.dataTransfer?.types.includes('Files')) return
      e.preventDefault()
      depth++
      setOver(true)
    }
    const leave = () => {
      depth = Math.max(0, depth - 1)
      if (!depth) setOver(false)
    }
    const overFn = (e: DragEvent) => e.dataTransfer?.types.includes('Files') && e.preventDefault()
    const drop = (e: DragEvent) => {
      if (!e.dataTransfer?.files.length) return
      e.preventDefault()
      depth = 0
      setOver(false)
      void addFiles(e.dataTransfer.files)
    }
    window.addEventListener('dragenter', enter)
    window.addEventListener('dragleave', leave)
    window.addEventListener('dragover', overFn)
    window.addEventListener('drop', drop)
    return () => {
      window.removeEventListener('dragenter', enter)
      window.removeEventListener('dragleave', leave)
      window.removeEventListener('dragover', overFn)
      window.removeEventListener('drop', drop)
    }
  }, [])
  if (!over) return null
  return (
    <div className="dropzone">
      <div className="dropzone-inner">
        <span className="hb tl" />
        <span className="hb tr" />
        <span className="hb bl" />
        <span className="hb br" />
        <Icon name="file" size={34} />
        <b>Rilascia per darlo ad AXEL</b>
        <span className="mono dim">PDF · Excel · CSV · Word · immagini</span>
      </div>
    </div>
  )
}

/** Proiezione olografica dei file prodotti (grafici, tabelle esportate). */
export function OutputsHUD() {
  const outputs = useStore((s) => s.outputs)
  const set = useStore((s) => s.set)
  const [sel, setSel] = useState(0)
  useEffect(() => setSel(0), [outputs?.at])
  if (!outputs?.files.length) return null
  const f = outputs.files[Math.min(sel, outputs.files.length - 1)]
  const isImg = f.mime.startsWith('image/')
  return (
    <aside className="hud-outputs" key={outputs.at}>
      <span className="hb tl" />
      <span className="hb tr" />
      <span className="hb bl" />
      <span className="hb br" />
      <div className="hud-scan" />
      <header>
        <span className="mono label">analisi · {f.name}</span>
        <span className="sp-head-btns">
          <a className="icon-btn sm" href={f.url} download={f.name} title="Scarica">
            <Icon name="download" size={14} />
          </a>
          <button className="icon-btn sm" onClick={() => set({ outputs: null })} aria-label="Chiudi">
            <Icon name="close" size={14} />
          </button>
        </span>
      </header>
      {isImg ? (
        <a href={f.url} target="_blank" rel="noreferrer" className="out-img">
          <img src={f.url} alt={f.name} />
        </a>
      ) : (
        <a className="out-file" href={f.url} download={f.name}>
          <Icon name="file" size={28} />
          <span>{f.name}</span>
          <em className="mono dim">scarica</em>
        </a>
      )}
      {outputs.files.length > 1 && (
        <div className="out-strip">
          {outputs.files.map((x, i) => (
            <button key={x.id} className={i === sel ? 'on' : ''} onClick={() => setSel(i)}>
              {x.mime.startsWith('image/') ? <img src={x.url} alt="" /> : <Icon name="file" size={16} />}
            </button>
          ))}
        </div>
      )}
    </aside>
  )
}

/** Risultato di un compito in background, nello stesso stile olografico. */
export function TaskViewHUD() {
  const view = useStore((s) => s.taskView)
  const set = useStore((s) => s.set)
  if (!view) return null
  return (
    <aside className="hud-outputs hud-task">
      <span className="hb tl" />
      <span className="hb tr" />
      <span className="hb bl" />
      <span className="hb br" />
      <header>
        <span className="mono label">compito · {view.title}</span>
        <button className="icon-btn sm" onClick={() => set({ taskView: null })} aria-label="Chiudi">
          <Icon name="close" size={14} />
        </button>
      </header>
      <div className="task-text">{linkify(view.text || (view.status === 'running' ? 'In corso…' : '(nessun risultato)'))}</div>
    </aside>
  )
}

function linkify(text: string) {
  return text.split(/(https?:\/\/[^\s)]+)/g).map((part, i) =>
    /^https?:\/\//.test(part) ? (
      <a key={i} href={part} target="_blank" rel="noreferrer">{part.replace(/^https?:\/\/(www\.)?/, '').slice(0, 48)}</a>
    ) : (
      <span key={i}>{part}</span>
    ),
  )
}
