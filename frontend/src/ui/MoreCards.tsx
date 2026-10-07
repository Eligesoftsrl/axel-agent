import { useCallback, useEffect, useState } from 'react'
import { api, type BackupStatus, type MapsSettings, type NewsSettings, type Proactive, type Shipment } from '../lib/api'
import { toast } from '../lib/controller'
import { useStore } from '../store'
import { BusyLabel, Card } from './Card'

/** Schede di Integrazioni: compiti in background, spedizioni, notizie, mappe, memoria che impara. */

function usePoll<T>(open: boolean, fn: () => Promise<T>, ms = 6000) {
  const [data, setData] = useState<T | null>(null)
  const load = useCallback(async () => {
    try {
      setData(await fn())
    } catch {
      /* backend giù */
    }
  }, [fn])
  useEffect(() => {
    if (!open) return
    load()
    const iv = setInterval(load, ms)
    return () => clearInterval(iv)
  }, [open, load, ms])
  return [data, setData, load] as const
}

const STATUS_IT: Record<string, string> = { running: 'in corso', done: 'completato', error: 'errore', cancelled: 'annullato' }

export function BackgroundCard({ open }: { open: boolean }) {
  const [rows, , load] = usePoll(open, api.backgroundList, 4000)
  const set = useStore((s) => s.set)
  return (
    <Card id="background" title="Compiti in background" summary={(() => { const n = rows?.filter((r) => r.status === 'running').length ?? 0; return n ? `${n} in corso` : rows?.length ? `${rows.length} recenti` : 'nessuno' })()}>
      <p className="dim small">«Axel, cercami con calma un volo per Lisbona sotto i 200 €»: un sotto-agente lavora mentre fai altro, poi arriva la bolla.</p>
      {(rows ?? []).slice(0, 6).map((r) => (
        <div key={r.id} className="row-between list-row">
          <span className="small">
            <b>{r.title}</b>
            <br />
            <em className="dim">{STATUS_IT[r.status] ?? r.status} · {r.steps} passi</em>
          </span>
          <span className="btns">
            {r.status === 'running' ? (
              <button className="pill ghost sm" onClick={async () => { await api.backgroundCancel(r.id); load() }}>Annulla</button>
            ) : (
              <button className="pill ghost sm" onClick={async () => { const t = await api.background(r.id); set({ taskView: { title: t.title, text: t.result ?? '', status: t.status } }) }}>Leggi</button>
            )}
          </span>
        </div>
      ))}
    </Card>
  )
}

export function ShipmentsCard({ open }: { open: boolean }) {
  const [rows, setRows, load] = usePoll<Shipment[]>(open, api.shipments, 15000)
  const [busy, setBusy] = useState(false)
  return (
    <Card id="shipments" title="Spedizioni" summary={rows?.length ? `${rows.length} in arrivo` : 'nessuna'}>
      {!rows?.length && <p className="dim small">Le rilevo dalle email di negozi e corrieri (Amazon, BRT, GLS, Poste, DHL…) e ti avviso quando sono in consegna.</p>}
      {(rows ?? []).map((r) => (
        <div key={r.id} className="row-between list-row">
          <span className="small">
            <b>{r.item || 'Pacco'}</b>{r.merchant ? <em className="dim"> · {r.merchant}</em> : null}
            <br />
            <em className={r.status === 'out_for_delivery' ? 'ok-text' : r.status === 'exception' ? 'err-text' : 'dim'}>
              {r.label}{r.eta && r.status !== 'delivered' ? ` · previsto ${new Date(r.eta).toLocaleDateString('it-IT', { day: '2-digit', month: '2-digit' })}` : ''}
              {r.carrier ? ` · ${r.carrier}` : ''}
            </em>
          </span>
          <span className="btns">
            {r.link && <a className="pill ghost sm" href={r.link} target="_blank" rel="noreferrer">Traccia</a>}
            <button className="pill ghost sm" title="Archivia" onClick={async () => { await api.shipmentArchive(r.id); load() }}>✓</button>
          </span>
        </div>
      ))}
      <button className="pill ghost sm" disabled={busy} onClick={async () => { setBusy(true); try { setRows(await api.shipmentsCheck()) } catch (e) { toast((e as Error).message, 'error') } setBusy(false) }}>
        <BusyLabel busy={busy} text="Controlla ora" busyText="Controllo le email…" />
      </button>
    </Card>
  )
}

export function NewsCard({ open }: { open: boolean }) {
  const [ns, setNs] = useState<NewsSettings | null>(null)
  const [url, setUrl] = useState('')
  const [preview, setPreview] = useState('')
  const [busy, setBusy] = useState(false)
  const [adding, setAdding] = useState(false)
  useEffect(() => {
    if (open) api.news().then(setNs).catch(() => {})
  }, [open])
  if (!ns) return null
  const save = async (patch: Partial<NewsSettings>) => setNs(await api.saveNews({ ...patch }))
  const has = (u: string) => ns.feeds.some((f) => f.url === u)
  // fonti: preimpostate + aggiunte da te (anche quelle disattivate restano come pulsante)
  const custom = [...(ns.custom ?? []), ...ns.feeds.filter((f) => !ns.presets.some((p) => p.url === f.url) && !(ns.custom ?? []).some((c) => c.url === f.url))]
  const sources = [...ns.presets.map((p) => ({ ...p, custom: false })), ...custom.map((c) => ({ ...c, name: c.name || new URL(c.url).hostname, custom: true }))]
  const addFeed = async () => {
    if (!url.trim()) return
    setAdding(true)
    try {
      const r = await api.addFeed(url.trim())
      setNs(r)
      setUrl('')
      toast(`Aggiunta «${r.added.name}»`, 'ok')
    } catch (e) {
      toast((e as Error).message.replace(/^\d+ /, '').replace(/^\{"detail":"|"\}$/g, ''), 'error')
    }
    setAdding(false)
  }
  return (
    <Card id="news" title="Notizie su misura" status={ns.feeds.length ? 'on' : 'off'} summary={ns.feeds.length ? `${ns.feeds.length} fonti` : 'nessuna fonte'}>
      <label>
        <span className="mono label">i tuoi interessi</span>
        <textarea rows={2} value={ns.interests} placeholder="es. intelligenza artificiale, sviluppo software, startup, Napoli, F1"
          onChange={(e) => setNs({ ...ns, interests: e.target.value })} onBlur={() => save({ interests: ns.interests })} />
      </label>
      <div className="mcp-presets">
        {sources.map((p) => (
          <span key={p.url} className={`feed-chip ${has(p.url) ? 'on' : ''}`} title={p.url}>
            <button type="button" onClick={() => save({ feeds: has(p.url) ? ns.feeds.filter((f) => f.url !== p.url) : [...ns.feeds, p] })}>
              {has(p.url) ? '✓ ' : '+ '}{p.name}
            </button>
            {p.custom && (
              <button type="button" className="feed-del" aria-label={`Elimina ${p.name}`} title="Elimina questa fonte"
                onClick={async () => setNs(await api.deleteFeed(p.url))}>×</button>
            )}
          </span>
        ))}
      </div>
      <div className="row">
        <input value={url} placeholder="Feed RSS o indirizzo del sito" onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') void addFeed() }} />
        <button className="pill ghost sm" disabled={!url.trim() || adding} onClick={() => void addFeed()}>
          <BusyLabel busy={adding} text="Aggiungi" busyText="Controllo…" />
        </button>
      </div>
      <div className="row-between toggle-row">
        <span className="small">Nel briefing del mattino</span>
        <label className="switch">
          <input type="checkbox" checked={ns.in_briefing} onChange={(e) => save({ in_briefing: e.target.checked })} />
          <span />
        </label>
      </div>
      <button className="pill ghost sm" disabled={busy || !ns.feeds.length} onClick={async () => { setBusy(true); try { setPreview((await api.newsTest()).text) } catch (e) { toast((e as Error).message, 'error') } setBusy(false) }}>
        <BusyLabel busy={busy} text="Prova adesso" busyText="Leggo le fonti…" />
      </button>
      {preview && <pre className="news-preview">{preview}</pre>}
    </Card>
  )
}

export function MapsCard({ open }: { open: boolean }) {
  const [m, setM] = useState<MapsSettings | null>(null)
  const [dest, setDest] = useState('')
  const [res, setRes] = useState('')
  useEffect(() => {
    if (open) api.maps().then(setM).catch(() => {})
  }, [open])
  if (!m) return null
  const save = async (patch: Partial<MapsSettings>) => setM(await api.saveMaps(patch))
  return (
    <Card id="maps" title="Mappe e traffico" status={m.home ? 'on' : 'off'} summary={m.home ? (m.traffic ? 'con traffico' : 'senza traffico') : 'imposta casa'}>
      {!m.traffic && <p className="dim small">Per i tempi con il traffico aggiungi <code>GOOGLE_MAPS_API_KEY</code> nel .env (guida nel README).</p>}
      <label>
        <span className="mono label">casa</span>
        <input value={m.home} placeholder="Via, numero, città" onChange={(e) => setM({ ...m, home: e.target.value })} onBlur={() => save({ home: m.home })} />
      </label>
      <label>
        <span className="mono label">ufficio</span>
        <input value={m.work} placeholder="Via, numero, città" onChange={(e) => setM({ ...m, work: e.target.value })} onBlur={() => save({ work: m.work })} />
      </label>
      <div className="row">
        <label>
          <span className="mono label">mezzo</span>
          <select value={m.mode} onChange={(e) => save({ mode: e.target.value })}>
            <option value="drive">Auto</option>
            <option value="moto">Moto</option>
            <option value="transit">Mezzi pubblici</option>
            <option value="bike">Bici</option>
            <option value="walk">A piedi</option>
          </select>
        </label>
        <label>
          <span className="mono label">margine (min)</span>
          <input type="number" min={0} max={60} value={m.buffer_min} onChange={(e) => setM({ ...m, buffer_min: +e.target.value })} onBlur={() => save({ buffer_min: m.buffer_min })} />
        </label>
      </div>
      <div className="row-between toggle-row">
        <span>
          <span className="small">Avviso «parti ora»</span>
          <br />
          <em className="dim small">Per gli appuntamenti con un indirizzo, calcolando il traffico da casa</em>
        </span>
        <label className="switch">
          <input type="checkbox" checked={m.leave_alerts} onChange={(e) => save({ leave_alerts: e.target.checked })} />
          <span />
        </label>
      </div>
      <div className="row">
        <input value={dest} placeholder="Prova: indirizzo di destinazione" onChange={(e) => setDest(e.target.value)} />
        <button className="pill ghost sm" disabled={!dest.trim()} onClick={async () => setRes((await api.mapsTest(dest)).text)}>Calcola</button>
      </div>
      {res && <pre className="news-preview">{res}</pre>}
    </Card>
  )
}

export function LearningCard({ open }: { open: boolean }) {
  const currentId = useStore((s) => s.currentId)
  const [last, , load] = usePoll(open, api.memoryLearned, 30000)
  const [busy, setBusy] = useState(false)
  const items = [...(last?.saved ?? []), ...(last?.updated ?? [])]
  return (
    <Card id="learning" title="Memoria che impara" summary={last?.date ? `ultima: ${last.date}` : 'ogni sera'}>
      <p className="dim small">Ogni sera AXEL rilegge le conversazioni del giorno e salva fatti, preferenze, persone e decisioni. Se ha dubbi te lo chiede.</p>
      {items.length > 0 && (
        <ul className="learned">
          {items.map((x) => <li key={x}>{x}</li>)}
        </ul>
      )}
      {(last?.questions ?? []).length > 0 && <p className="small">Domande: {(last?.questions ?? []).join(' · ')}</p>}
      <button className="pill ghost sm" disabled={busy} onClick={async () => {
        setBusy(true)
        try {
          const r = await api.memoryLearn(currentId)
          toast(r.saved.length + r.updated.length ? `Ho imparato ${r.saved.length + r.updated.length} cose nuove` : 'Niente di nuovo da ricordare oggi', 'ok')
          load()
        } catch (e) {
          toast((e as Error).message, 'error')
        }
        setBusy(false)
      }}>
        <BusyLabel busy={busy} text="Impara adesso dalla giornata" busyText="Rileggo la giornata…" />
      </button>
    </Card>
  )
}

const lines = (t: string) => t.split('\n').map((x) => x.trim()).filter(Boolean)

export function EmailRulesCard({ open }: { open: boolean }) {
  const currentId = useStore((s) => s.currentId)
  const [pro, setPro] = useState<Proactive | null>(null)
  const [vip, setVip] = useState('')
  const [ign, setIgn] = useState('')
  const [rules, setRules] = useState('')
  useEffect(() => {
    if (!open) return
    api.integrations(currentId || 'axel').then((i) => {
      setPro(i.proactive)
      setVip((i.proactive.vip_senders ?? []).join('\n'))
      setIgn((i.proactive.ignore_senders ?? []).join('\n'))
      setRules(i.proactive.email_rules ?? '')
    }).catch(() => {})
  }, [open, currentId])
  if (!pro) return null
  const save = async (patch: Partial<Proactive>) => {
    try {
      setPro(await api.saveProactive(patch))
    } catch (e) {
      toast((e as Error).message, 'error')
    }
  }
  const n = lines(vip).length
  return (
    <Card id="emailrules" title="Email importanti" status={pro.email_alerts ? 'on' : 'off'} summary={pro.email_alerts ? (n ? `${n} mittenti prioritari` : 'decide Claude') : 'avvisi spenti'}>
      <p className="dim small">
        Come decide: prima le tue regole qui sotto, poi Claude legge mittente, oggetto e anteprima delle email nuove e
        avvisa solo per persone reali, clienti, scadenze, pagamenti e sicurezza (ignora newsletter e pubblicità).
      </p>
      <label>
        <span className="mono label">mittenti prioritari · avviso sempre</span>
        <textarea rows={3} value={vip} placeholder={'uno per riga, ad esempio:\nmario.rossi@cliente.it\n@perfexia.it  (tutto il dominio)\nCommercialista  (parte del nome)'}
          onChange={(e) => setVip(e.target.value)} onBlur={() => save({ vip_senders: lines(vip) })} />
      </label>
      <label>
        <span className="mono label">mittenti da ignorare · mai avvisi</span>
        <textarea rows={2} value={ign} placeholder={'uno per riga, ad esempio:\n@newsletter.amazon.it'}
          onChange={(e) => setIgn(e.target.value)} onBlur={() => save({ ignore_senders: lines(ign) })} />
      </label>
      <label>
        <span className="mono label">cosa conta per te (in parole tue)</span>
        <textarea rows={2} value={rules} placeholder="es. avvisami per fatture e scadenze fiscali, richieste di preventivo, problemi sui server dei clienti; non per le conferme d'ordine"
          onChange={(e) => setRules(e.target.value)} onBlur={() => save({ email_rules: rules })} />
      </label>
      <div className="row-between toggle-row">
        <span className="small">Avvisi per le email importanti</span>
        <label className="switch">
          <input type="checkbox" checked={pro.email_alerts} onChange={(e) => save({ email_alerts: e.target.checked })} />
          <span />
        </label>
      </div>
    </Card>
  )
}

const kb = (n: number) => (n > 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1e3))} kB`)
const when = (iso: string) => new Date(iso).toLocaleString('it-IT', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })

export function BackupCard({ open }: { open: boolean }) {
  const [b, setB, load] = usePoll<BackupStatus>(open, api.backup, 20000)
  const [busy, setBusy] = useState('')
  const [showAll, setShowAll] = useState(false)
  if (!b) return null
  const save = async (patch: Partial<BackupStatus>) => setB(await api.saveBackup(patch))
  const run = async () => {
    setBusy('run')
    try {
      setB(await api.backupRun())
      toast('Copia di sicurezza creata', 'ok')
    } catch (e) {
      toast((e as Error).message, 'error')
    }
    setBusy('')
  }
  const restore = async (name: string) => {
    if (!confirm(`Ripristinare la copia ${name}?\n\nMemoria, cronologia e impostazioni torneranno a quel momento. Lo stato attuale viene salvato prima in un'altra copia.`)) return
    setBusy(name)
    try {
      const r = await api.backupRestore(name)
      toast(`Ripristinata. Lo stato precedente è in ${r.safety}. Ricarica la pagina.`, 'ok')
      load()
    } catch (e) {
      toast((e as Error).message, 'error')
    }
    setBusy('')
  }
  const list = showAll ? b.backups : b.backups.slice(0, 3)
  return (
    <Card id="backup" title="Copia di sicurezza" status={b.error ? 'warn' : b.enabled && b.last ? 'on' : 'off'}
      summary={b.error ? 'ultima copia non riuscita' : b.last ? `ultima: ${when(b.last.at)}` : b.enabled ? 'stanotte la prima' : 'spenta'}
      right={<label className="switch"><input type="checkbox" checked={b.enabled} onChange={(e) => save({ enabled: e.target.checked })} /><span /></label>}>
      <p className="dim small">
        Ogni notte salva memoria, conversazioni, impostazioni, agenti e collegamenti in un file .zip. Se il Mac era spento, la fa appena si riaccende.
        Contiene anche gli accessi a Google e Spotify: tienila in un posto solo tuo.
      </p>
      {b.error && <p className="small err-text">{b.error.error}</p>}
      <label>
        <span className="mono label">cartella</span>
        <input value={b.folder} placeholder={b.folder_effective} onChange={(e) => setB({ ...b, folder: e.target.value })} onBlur={() => save({ folder: b.folder })} />
        <em className="dim small">{b.folder ? '' : 'Predefinita: '}{b.folder_effective}</em>
      </label>
      <div className="row">
        <label>
          <span className="mono label">ora</span>
          <input type="time" value={b.time} onChange={(e) => setB({ ...b, time: e.target.value })} onBlur={() => save({ time: b.time })} />
        </label>
        <label>
          <span className="mono label">copie da tenere</span>
          <input type="number" min={3} max={90} value={b.keep} onChange={(e) => setB({ ...b, keep: +e.target.value })} onBlur={() => save({ keep: b.keep })} />
        </label>
      </div>
      <button className="pill ghost sm" disabled={!!busy} onClick={run}>
        <BusyLabel busy={busy === 'run'} text="Fai una copia adesso" busyText="Salvo…" />
      </button>
      {b.backups.length > 0 && (
        <>
          <span className="mono label">copie disponibili ({b.backups.length})</span>
          {list.map((x) => (
            <div key={x.name} className="row-between list-row">
              <span className="small">
                {when(x.created)} <em className="dim">· {kb(x.size)}{x.name.includes('prima-ripristino') ? ' · prima di un ripristino' : x.name.includes('manuale') ? ' · manuale' : ''}</em>
              </span>
              <button className="pill ghost sm" disabled={!!busy} onClick={() => restore(x.name)}>
                <BusyLabel busy={busy === x.name} text="Ripristina" busyText="Ripristino…" />
              </button>
            </div>
          ))}
          {b.backups.length > 3 && (
            <button className="pill ghost sm" onClick={() => setShowAll((v) => !v)}>{showAll ? 'Mostra meno' : 'Mostra tutte'}</button>
          )}
        </>
      )}
    </Card>
  )
}
