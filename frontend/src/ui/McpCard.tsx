import { useCallback, useEffect, useState } from 'react'
import { api, type McpConfigInput, type McpInfo, type McpServer } from '../lib/api'
import { toast } from '../lib/controller'
import { BusyLabel, Card } from './Card'

/** Collegamenti MCP: server locali (comando) o remoti (URL) i cui strumenti diventano strumenti di AXEL. */

interface Field {
  key: string
  label: string
  placeholder?: string
  value?: string
  type?: 'text' | 'password'
  help?: string
  optional?: boolean
}

interface Preset {
  id: string
  label: string
  hint: string
  /** campi semplici: da questi si costruiscono comando, argomenti e variabili */
  fields?: Field[]
  build?: (v: Record<string, string>) => Partial<Record<'command' | 'args' | 'env' | 'url' | 'headers' | 'description', string>>
  name: string
  kind: 'cmd' | 'url'
  command?: string
  args?: string
  env?: string
  url?: string
  headers?: string
  description?: string
}

const q = (v: string) => (/\s/.test(v) ? `"${v}"` : v)
const enc = encodeURIComponent

const PRESETS: Preset[] = [
  { id: 'fs', label: 'File di una cartella', name: 'cartella', kind: 'cmd',
    hint: 'AXEL potrà leggere, cercare e (con la tua conferma) creare o modificare file solo dentro la cartella che indichi. Serve Node.js, che hai già per il frontend.',
    fields: [{ key: 'folder', label: 'cartella', value: '~/Documents', placeholder: '~/Documents/Clienti',
      help: 'Percorso sul Mac. ~ è la tua cartella Home. Trucco: trascina la cartella dal Finder nel Terminale per vederne il percorso.' }],
    build: (v) => ({ command: 'npx', args: `-y @modelcontextprotocol/server-filesystem ${q(v.folder || '~/Documents')}`,
      description: `file della cartella ${(v.folder || '~/Documents').split('/').filter(Boolean).pop()}` }) },
  { id: 'fetch', label: 'Pagine web', name: 'web', kind: 'cmd',
    hint: 'AXEL potrà aprire un link e leggerne il contenuto come testo. Non serve nient\'altro (usa uv, già installato).',
    build: () => ({ command: 'uvx', args: 'mcp-server-fetch', description: 'lettura di pagine web' }) },
  { id: 'github', label: 'GitHub', name: 'github', kind: 'url',
    hint: 'Repository, issue e pull request. Crea un token su github.com → Settings → Developer settings → Personal access tokens (Fine-grained) con accesso in lettura ai repository.',
    fields: [{ key: 'token', label: 'token GitHub', type: 'password', placeholder: 'github_pat_… oppure ghp_…' }],
    build: (v) => ({ url: 'https://api.githubcopilot.com/mcp/', headers: `Authorization=Bearer ${v.token ?? ''}`, description: 'repository, issue, pull request' }) },
  { id: 'notion', label: 'Notion', name: 'notion', kind: 'cmd',
    hint: 'Su notion.so/profile/integrations crea un\'integrazione interna e copia il token. Poi in Notion, su ogni pagina che AXEL deve vedere: ··· → Connessioni → aggiungi l\'integrazione.',
    fields: [{ key: 'token', label: 'token integrazione Notion', type: 'password', placeholder: 'ntn_…' }],
    build: (v) => ({ command: 'npx', args: '-y @notionhq/notion-mcp-server', env: `NOTION_TOKEN=${v.token ?? ''}`, description: 'pagine e database Notion' }) },
  { id: 'pg', label: 'Database Postgres', name: 'database', kind: 'cmd',
    hint: 'AXEL potrà interrogare il database in sola lettura (non può modificare i dati): "quanto abbiamo fatturato a settembre?". Usa i dati di accesso del database, meglio un utente di sola lettura.',
    fields: [
      { key: 'host', label: 'server', value: 'localhost', placeholder: 'localhost o indirizzo del server' },
      { key: 'port', label: 'porta', value: '5432', placeholder: '5432' },
      { key: 'db', label: 'nome database', placeholder: 'gestionale' },
      { key: 'user', label: 'utente', placeholder: 'axel_lettura' },
      { key: 'password', label: 'password', type: 'password', placeholder: '••••••', optional: true },
    ],
    build: (v) => ({ command: 'uvx', args: 'postgres-mcp --access-mode=restricted',
      env: `DATABASE_URI=postgresql://${enc(v.user ?? '')}${v.password ? ':' + enc(v.password) : ''}@${v.host || 'localhost'}:${v.port || '5432'}/${enc(v.db ?? '')}`,
      description: `database ${v.db ?? ''} (sola lettura)` }) },
  { id: 'custom', label: 'Personalizzato', name: '', kind: 'cmd',
    hint: 'Qualsiasi server MCP. Copia comando e argomenti dalla pagina del server (la parte "command" e "args" della configurazione per Claude Desktop), oppure l\'URL se è un server remoto.' },
]

const STATUS: Record<McpServer['status'], string> = {
  idle: 'fermo', connecting: 'collegamento…', connected: 'collegato', error: 'errore', disabled: 'disattivato',
}
const APPROVAL: Record<string, string> = {
  'auto-read': 'Conferma le modifiche',
  ask: 'Conferma sempre',
  auto: 'Nessuna conferma',
}

const pairs = (txt: string) =>
  Object.fromEntries(
    txt
      .split('\n')
      .map((l) => l.trim())
      .filter((l) => l.includes('='))
      .map((l) => [l.slice(0, l.indexOf('=')).trim(), l.slice(l.indexOf('=') + 1).trim()]),
  )

/** divide gli argomenti rispettando le virgolette: -y "una cartella/con spazi" */
const splitArgs = (txt: string) => (txt.match(/"[^"]*"|'[^']*'|\S+/g) ?? []).map((a) => a.replace(/^["']|["']$/g, ''))

export function McpCard({ open }: { open: boolean }) {
  const [info, setInfo] = useState<McpInfo | null>(null)
  const [adding, setAdding] = useState<Preset | null>(null)
  const [form, setForm] = useState({ name: '', kind: 'cmd' as 'cmd' | 'url', command: '', args: '', env: '', url: '', headers: '', description: '', approval: 'auto-read' })
  const [busy, setBusy] = useState('')
  const [expanded, setExpanded] = useState('')
  const [vals, setVals] = useState<Record<string, string>>({})
  const [advanced, setAdvanced] = useState(false)

  const load = useCallback(async () => {
    try {
      setInfo(await api.mcp())
    } catch {
      /* backend giù */
    }
  }, [])

  useEffect(() => {
    if (!open) return
    load()
    const iv = setInterval(load, 4000)
    return () => clearInterval(iv)
  }, [open, load])

  const pick = (p: Preset) => {
    setAdding(p)
    const v = Object.fromEntries((p.fields ?? []).map((f) => [f.key, f.value ?? '']))
    setVals(v)
    setAdvanced(p.id === 'custom')
    const b = p.build?.(v) ?? {}
    setForm({ name: p.name, kind: p.kind, command: b.command ?? '', args: b.args ?? '', env: b.env ?? '', url: b.url ?? '', headers: b.headers ?? '', description: b.description ?? '', approval: 'auto-read' })
  }

  /** un campo semplice è cambiato: ricostruisce comando, argomenti e variabili */
  const setVal = (key: string, value: string) => {
    const v = { ...vals, [key]: value }
    setVals(v)
    if (adding?.build) setForm((f) => ({ ...f, ...adding.build!(v) }))
  }

  const save = async () => {
    const name = form.name.trim()
    if (!name) return toast('Dai un nome al collegamento', 'error')
    const missing = (adding?.fields ?? []).find((f) => !f.optional && !(vals[f.key] ?? '').trim())
    if (missing) return toast(`Compila il campo «${missing.label}»`, 'error')
    if (form.kind === 'cmd' && !form.command.trim()) return toast('Manca il comando (vedi Opzioni avanzate)', 'error')
    if (form.kind === 'url' && !form.url.trim()) return toast("Manca l'URL del server", 'error')
    const cfg: McpConfigInput =
      form.kind === 'url'
        ? { url: form.url.trim(), headers: pairs(form.headers), approval: form.approval, enabled: true, description: form.description, keep_secrets: false }
        : { command: form.command.trim(), args: splitArgs(form.args), env: pairs(form.env), approval: form.approval, enabled: true, description: form.description, keep_secrets: false }
    setBusy('save')
    try {
      setInfo(await api.mcpSave(name, cfg))
      setAdding(null)
      toast(`Collegamento «${name}» salvato: mi collego…`, 'ok')
    } catch (e) {
      toast((e as Error).message.replace(/^\d+ /, ''), 'error')
    }
    setBusy('')
  }

  const update = async (s: McpServer, patch: Partial<McpConfigInput>) => {
    const base: McpConfigInput = {
      command: s.config.command, args: s.config.args, url: s.config.url, transport: s.config.transport,
      description: s.config.description, approval: s.approval, enabled: s.enabled, keep_secrets: true,
    }
    setBusy(s.name)
    try {
      setInfo(await api.mcpSave(s.name, { ...base, ...patch }))
    } catch (e) {
      toast((e as Error).message, 'error')
    }
    setBusy('')
  }

  const servers = info?.servers ?? []
  const tools = servers.reduce((a, s) => a + s.tools.length, 0)

  return (
    <Card id="mcp" title="Collegamenti MCP" status={servers.some((x) => x.status === 'error') ? 'warn' : servers.length ? 'on' : 'off'} summary={servers.length ? `${servers.length} server · ${tools} strumenti` : 'nessuno'}>
      {info && !info.available && (
        <p className="dim small">
          Manca il pacchetto Python <code>mcp</code>: nel backend esegui <code>uv pip install -r requirements.txt</code> e riavvia.
        </p>
      )}
      <p className="dim small">
        Collega servizi esterni con i loro strumenti già pronti: AXEL li usa quando servono. Le azioni che modificano dati chiedono conferma.
      </p>

      {servers.map((s) => (
        <div key={s.name} className="mcp-server">
          <div className="row-between">
            <span>
              <span className={`dot inline ${s.status === 'connected' ? 'on' : s.status === 'error' ? 'err' : ''}`} /> <b className="small">{s.name}</b>
              <em className="dim small"> · {STATUS[s.status]}{s.status === 'connected' ? ` · ${s.tools.length} strumenti` : ''}</em>
            </span>
            <span className="btns">
              {s.tools.length > 0 && (
                <button className="pill ghost sm" onClick={() => setExpanded(expanded === s.name ? '' : s.name)}>
                  {expanded === s.name ? 'Nascondi' : 'Strumenti'}
                </button>
              )}
              <label className="switch" title={s.enabled ? 'Disattiva' : 'Attiva'}>
                <input type="checkbox" checked={s.enabled} disabled={busy === s.name} onChange={(e) => update(s, { enabled: e.target.checked })} />
                <span />
              </label>
            </span>
          </div>
          {s.error && <p className="small err-text">{s.error}</p>}
          <div className="row-between">
            <select value={s.approval} disabled={busy === s.name} onChange={(e) => update(s, { approval: e.target.value })}>
              {Object.entries(APPROVAL).map(([k, l]) => (
                <option key={k} value={k}>{l}</option>
              ))}
            </select>
            <button className="pill ghost sm" onClick={async () => { if (confirm(`Rimuovere il collegamento «${s.name}»?`)) setInfo(await api.mcpDelete(s.name)) }}>
              Rimuovi
            </button>
          </div>
          {expanded === s.name && (
            <ul className="mcp-tools">
              {s.tools.map((t) => (
                <li key={t.name}>
                  <code>{t.name}</code> {t.read_only && <span className="tag">lettura</span>}
                  <br />
                  <span className="dim small">{t.description}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}

      {!adding ? (
        <div className="mcp-presets">
          {PRESETS.map((p) => (
            <button key={p.id} className="pill ghost sm" onClick={() => pick(p)}>
              + {p.label}
            </button>
          ))}
        </div>
      ) : (
        <div className="mcp-form">
          <b className="small">{adding.label}</b>
          <p className="dim small">{adding.hint}</p>
          {(adding.fields ?? []).map((f) => (
            <label key={f.key}>
              <span className="mono label">{f.label}{f.optional ? ' (facoltativo)' : ''}</span>
              <input type={f.type ?? 'text'} value={vals[f.key] ?? ''} placeholder={f.placeholder} autoComplete="off"
                onChange={(e) => setVal(f.key, e.target.value)} />
              {f.help && <em className="dim small">{f.help}</em>}
            </label>
          ))}
          <label>
            <span className="mono label">nome del collegamento</span>
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value.replace(/[^A-Za-z0-9_-]/g, '') })} placeholder="es. clienti" />
          </label>
          {adding.id !== 'custom' && (
            <button type="button" className="link-btn" onClick={() => setAdvanced((x) => !x)}>
              {advanced ? '▴ Nascondi opzioni avanzate' : '▾ Opzioni avanzate (comando e variabili)'}
            </button>
          )}
          {advanced && (<>
          <div className="row">
            <label>
              <span className="mono label">tipo</span>
              <select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value as 'cmd' | 'url' })}>
                <option value="cmd">Locale (comando)</option>
                <option value="url">Remoto (URL)</option>
              </select>
            </label>
          </div>
          {form.kind === 'cmd' ? (
            <>
              <label>
                <span className="mono label">comando e argomenti</span>
                <div className="row">
                  <input style={{ maxWidth: 90 }} value={form.command} onChange={(e) => setForm({ ...form, command: e.target.value })} placeholder="npx" />
                  <input value={form.args} onChange={(e) => setForm({ ...form, args: e.target.value })} placeholder="-y pacchetto-server-mcp" />
                </div>
              </label>
              <label>
                <span className="mono label">variabili (una per riga, NOME=valore)</span>
                <textarea rows={2} value={form.env} onChange={(e) => setForm({ ...form, env: e.target.value })} placeholder="TOKEN=..." />
              </label>
            </>
          ) : (
            <>
              <label>
                <span className="mono label">url del server</span>
                <input value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} placeholder="https://…/mcp" />
              </label>
              <label>
                <span className="mono label">intestazioni (una per riga, Nome=valore)</span>
                <textarea rows={2} value={form.headers} onChange={(e) => setForm({ ...form, headers: e.target.value })} placeholder="Authorization=Bearer ..." />
              </label>
            </>
          )}
          </>)}
          <label>
            <span className="mono label">a cosa serve (aiuta AXEL a sceglierlo)</span>
            <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </label>
          <label>
            <span className="mono label">conferme</span>
            <select value={form.approval} onChange={(e) => setForm({ ...form, approval: e.target.value })}>
              {Object.entries(APPROVAL).map(([k, l]) => (
                <option key={k} value={k}>{l}</option>
              ))}
            </select>
          </label>
          <div className="row-between">
            <button className="pill ghost sm" onClick={() => setAdding(null)}>Annulla</button>
            <button className="send as-btn" disabled={busy === 'save'} onClick={save}><BusyLabel busy={busy === 'save'} text="Salva e collega" busyText="Salvo…" /></button>
          </div>
          <p className="dim small">Token e password restano solo sul tuo Mac, in <code>backend/data/mcp.json</code>.</p>
        </div>
      )}
      {servers.length > 0 && (
        <button className="pill ghost sm" disabled={busy === 'reload'} onClick={async () => { setBusy('reload'); try { setInfo(await api.mcpReload()) } finally { setBusy('') } }}>
          <BusyLabel busy={busy === 'reload'} text="Ricollega tutti" busyText="Ricollego…" />
        </button>
      )}
    </Card>
  )
}
