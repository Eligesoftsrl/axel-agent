import { useCallback, useEffect, useState } from 'react'
import { api, type Briefing, type Integrations as Info, type Memory, type Proactive, type Reminder, type Task } from '../lib/api'
import { toast } from '../lib/controller'
import { useStore } from '../store'
import { AccordionCtx, BusyLabel, Card } from './Card'
import { Icon } from './Icon'
import { VoiceSpeedCard } from './VoiceSpeedCard'
import { McpCard } from './McpCard'
import { BackgroundCard, BackupCard, EmailRulesCard, LearningCard, MapsCard, NewsCard, ShipmentsCard } from './MoreCards'

const GIORNI = ['dom', 'lun', 'mar', 'mer', 'gio', 'ven', 'sab']
const REC: Record<string, string> = { none: '', daily: 'ogni giorno', weekdays: 'feriali', weekly: 'ogni settimana', monthly: 'ogni mese' }

function fmtDue(iso: string) {
  const d = new Date(iso)
  return `${GIORNI[d.getDay()]} ${d.toLocaleDateString('it-IT', { day: '2-digit', month: '2-digit' })} ${d.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })}`
}

const TABS = [
  { id: 'account', label: 'Account', icon: 'plug' },
  { id: 'routine', label: 'Routine', icon: 'clock' },
  { id: 'info', label: 'Info', icon: 'news' },
  { id: 'system', label: 'Sistema', icon: 'chip' },
  { id: 'memory', label: 'Memoria', icon: 'brain' },
] as const
type TabId = (typeof TABS)[number]['id']

/** la scheda Proattività salva solo i suoi campi (le regole email le gestisce la loro scheda) */
const saveToggles = (p: Proactive) => {
  const { vip_senders: _v, ignore_senders: _i, email_rules: _r, ...rest } = p
  return api.saveProactive(rest)
}

const saved = (k: string, d: string) => {
  try {
    return localStorage.getItem(k) ?? d
  } catch {
    return d
  }
}

export function Integrations() {
  const [tab, setTab] = useState<TabId>(() => saved('axel.intTab', 'account') as TabId)
  const [openId, setOpenRaw] = useState(() => saved('axel.intOpen', ''))
  const setOpen = (id: string) => {
    setOpenRaw(id)
    try {
      localStorage.setItem('axel.intOpen', id)
    } catch {
      /* ignore */
    }
  }
  const pickTab = (id: TabId) => {
    setTab(id)
    setOpen('')
    try {
      localStorage.setItem('axel.intTab', id)
    } catch {
      /* ignore */
    }
  }
  const { integrationsOpen, currentId, set } = useStore()
  const [info, setInfo] = useState<Info | null>(null)
  const [brief, setBrief] = useState<Briefing>({ enabled: false, time: '07:30', city: 'Roma' })
  const [rems, setRems] = useState<Reminder[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [pro, setPro] = useState<Proactive | null>(null)
  const [mems, setMems] = useState<Memory[]>([])
  const [busy, setBusy] = useState('')
  const [spDiag, setSpDiag] = useState<{ name: string; ok: boolean; detail: string }[] | null>(null)

  const load = useCallback(async () => {
    try {
      const [i, r, m, tk] = await Promise.all([api.integrations(currentId), api.reminders(), api.memories(currentId), api.tasks()])
      setTasks(tk)
      setPro((p) => (busy === 'pro-edit' && p ? p : i.proactive))
      setInfo(i)
      setRems(r)
      setMems(m)
      setBrief((b) => (busy === 'brief-edit' ? b : i.briefing))
    } catch {
      /* backend giù */
    }
  }, [currentId, busy])

  useEffect(() => {
    if (!integrationsOpen) return
    load()
    const iv = setInterval(load, 5000) // es. per vedere l'abbinamento Telegram appena avviene
    return () => clearInterval(iv)
  }, [integrationsOpen, load])

  const run = async (key: string, fn: () => Promise<unknown>, ok?: string) => {
    setBusy(key)
    try {
      await fn()
      if (ok) toast(ok, 'ok')
    } catch (e) {
      toast(`Errore: ${(e as Error).message}`, 'error')
    }
    setBusy('')
    load()
  }

  const g = info?.google
  const t = info?.telegram
  const sp = info?.spotify
  const claude = info?.history?.claude
  const attention = [g?.connected, t?.linked, sp?.connected, info?.hue?.linked].filter((x) => x === false).length

  return (
    <aside className={`panel integrations ${integrationsOpen ? 'open' : ''}`} aria-hidden={!integrationsOpen}>
      <div className="panel-head">
        <h2>Integrazioni</h2>
        <button className="icon-btn" onClick={() => set({ integrationsOpen: false })} aria-label="Chiudi">
          <Icon name="close" />
        </button>
      </div>

      <nav className="int-tabs" role="tablist">
        {TABS.map((tb) => (
          <button key={tb.id} role="tab" aria-selected={tab === tb.id} className={tab === tb.id ? 'on' : ''} onClick={() => pickTab(tb.id)}>
            <Icon name={tb.icon} size={16} />
            <span>{tb.label}</span>
            {tb.id === 'account' && attention > 0 && <i className="tab-dot" title="Da collegare" />}
          </button>
        ))}
      </nav>

      <AccordionCtx.Provider value={{ openId, setOpen }}>
      <div className="form int-list">
        {tab === 'account' && (
          <>
        <Card id="google" title="Google" status={g?.connected ? 'on' : g?.configured ? 'warn' : 'off'} summary={g?.connected ? g.email : g?.configured ? 'da collegare' : 'da configurare'}>
          {!g?.configured && (
            <p className="dim small">
              Manca il file <code>backend/data/google_client_secret.json</code>. Segui la guida "Google" nel README, poi torna qui.
            </p>
          )}
          {g?.configured && !g.connected && (
            <>
              <p className="dim small">Autorizza AXEL a leggere calendario ed email. Le email partono solo dopo la tua conferma.</p>
              <a className="send as-btn" href="/api/google/auth">
                Collega Google
              </a>
            </>
          )}
          {g?.connected && (
            <div className="row-between">
              <span className="small">Collegato come {g.email}</span>
              <button className="pill ghost sm" onClick={() => run('g', api.googleDisconnect, 'Google scollegato')}>
                Scollega
              </button>
            </div>
          )}
        </Card>
        <Card id="telegram" title="Telegram" status={t?.linked ? 'on' : t?.configured ? 'warn' : 'off'} summary={t?.linked ? `@${t.bot}` : t?.configured ? 'da abbinare' : 'da configurare'}>
          {!t?.configured && (
            <p className="dim small">
              Crea un bot con @BotFather e metti il token in <code>TELEGRAM_BOT_TOKEN</code> nel file .env, poi riavvia il backend (guida nel README).
            </p>
          )}
          {t?.configured && !t.linked && (
            <>
              <p className="small">Apri il bot e premi Avvia: il collegamento è automatico.</p>
              <a className="send as-btn" href={`https://t.me/${t.bot}?start=${t.pair_code}`} target="_blank" rel="noreferrer">
                Apri @{t.bot}
              </a>
              <p className="dim small">
                Oppure invia al bot il codice <code>{t.pair_code}</code>
              </p>
            </>
          )}
          {t?.linked && (
            <div className="row-between toggle-row">
              <span>
                <span className="small">Rispondi a voce ai vocali</span>
                <br />
                <em className="dim small">I vocali li trascrive Whisper; la risposta usa la voce italiana del Mac</em>
              </span>
              <label className="switch">
                <input type="checkbox" checked={t.voice_reply} onChange={(e) => run('tv', () => api.telegramVoice(e.target.checked))} />
                <span />
              </label>
            </div>
          )}
          {t?.linked && (
            <div className="row-between">
              <span className="small">Collegato a @{t.bot}</span>
              <span className="btns">
                <button className="pill ghost sm" disabled={busy === 'tt'} onClick={() => run('tt', api.telegramTest, 'Messaggio di prova inviato')}>
                  Prova
                </button>
                <button className="pill ghost sm" onClick={() => run('tu', api.telegramUnlink, 'Telegram scollegato')}>
                  Scollega
                </button>
              </span>
            </div>
          )}
        </Card>
        <Card id="spotify" title="Spotify" status={sp?.connected ? 'on' : sp?.configured ? 'warn' : 'off'} summary={sp?.connected ? sp.user : sp?.configured ? 'da collegare' : 'da configurare'}>
          {!sp?.configured && (
            <p className="dim small">
              Crea un'app su developer.spotify.com e metti <code>SPOTIFY_CLIENT_ID</code> e <code>SPOTIFY_CLIENT_SECRET</code> nel .env (guida nel README).
            </p>
          )}
          {sp?.configured && !sp.connected && (
            <>
              <p className="dim small">"Metti la mia playlist Focus", "abbassa il volume", "cosa sto ascoltando?". Il controllo richiede Premium.</p>
              <a className="send as-btn" href="/api/spotify/auth">
                Collega Spotify
              </a>
            </>
          )}
          {sp?.connected && (
            <div className="row-between">
              <span className="small">Collegato come {sp.user}</span>
              <span className="btns">
                <button className="pill ghost sm" onClick={() => run('sn', async () => toast((await api.spotifyNow()).text, 'info'))}>
                  In ascolto
                </button>
                <button className="pill ghost sm" disabled={busy === 'sdiag'} onClick={() => run('sdiag', async () => setSpDiag((await api.spotifyDiagnose()).checks))}>
                  <BusyLabel busy={busy === 'sdiag'} text="Diagnostica" busyText="Controllo…" />
                </button>
                <button className="pill ghost sm" onClick={() => run('sd', api.spotifyDisconnect, 'Spotify scollegato')}>
                  Scollega
                </button>
              </span>
            </div>
          )}
          {spDiag && (
            <ul className="diag">
              {spDiag.map((c) => (
                <li key={c.name} className={c.ok ? 'ok' : 'ko'}>
                  <b>{c.ok ? '✓' : '✕'} {c.name}</b>
                  <span className="dim small">{c.detail}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card id="hue" title="Luci Philips Hue" status={info?.hue?.linked ? 'on' : 'off'} summary={info?.hue?.linked ? 'collegato' : 'da abbinare'}>
          {!info?.hue?.linked ? (
            <>
              <p className="dim small">
                Premi il <b>pulsante rotondo sul Bridge Hue</b>, poi entro 30 secondi clicca Collega. Il Mac deve essere sulla stessa rete di casa.
              </p>
              <button
                className="send"
                disabled={busy === 'hue'}
                onClick={() =>
                  run('hue', async () => {
                    const r = await api.huePair()
                    if (r.ok) toast('Luci Hue collegate ✓', 'ok')
                    else if (r.need_button) toast('Premi prima il pulsante sul Bridge Hue, poi riprova', 'info')
                  })
                }
              >
                {busy === 'hue' ? 'Collego…' : 'Collega Bridge Hue'}
              </button>
            </>
          ) : (
            <div className="row-between">
              <span className="small">Bridge {info.hue.ip} · "accendi il soggiorno al 40%", "luci viola in camera"</span>
              <button className="pill ghost sm" onClick={() => run('hu', api.hueUnlink, 'Hue scollegato')}>
                Scollega
              </button>
            </div>
          )}
        </Card>
        <McpCard open={integrationsOpen} />
          </>
        )}
        {tab === 'routine' && (
          <>
        <Card id="briefing" title="Briefing mattutino" summary={brief.enabled ? `ogni giorno alle ${brief.time}` : 'spento'} right={<label className="switch">
              <input
                type="checkbox"
                checked={brief.enabled}
                onChange={(e) => {
                  const b = { ...brief, enabled: e.target.checked }
                  setBrief(b)
                  run('b', () => api.saveBriefing(b), b.enabled ? `Briefing attivo alle ${b.time}` : 'Briefing disattivato')
                }}
              />
              <span />
            </label>}>
          <p className="dim small">Meteo, appuntamenti, email importanti, promemoria e notizie, ogni mattina su Telegram.</p>
          <div className="row">
            <label>
              <span className="mono label">ora</span>
              <input type="time" value={brief.time} onFocus={() => setBusy('brief-edit')} onChange={(e) => setBrief({ ...brief, time: e.target.value })} />
            </label>
            <label>
              <span className="mono label">città meteo</span>
              <input value={brief.city} onFocus={() => setBusy('brief-edit')} onChange={(e) => setBrief({ ...brief, city: e.target.value })} />
            </label>
          </div>
          <div className="row-between">
            <button className="pill ghost sm" onClick={() => run('b', () => api.saveBriefing(brief), 'Impostazioni salvate')}>
              Salva
            </button>
            <button className="pill ghost sm" disabled={busy === 'br'} onClick={() => run('br', api.runBriefing, 'Briefing inviato')}>
              <BusyLabel busy={busy === 'br'} text="Invia ora" busyText="Preparo…" />
            </button>
          </div>
        </Card>
        {pro && (
          <Card id="proactive" title="Proattività" summary={`${[pro.event_alerts, pro.mail_bubbles, pro.email_alerts, pro.evening_recap, pro.shipments, pro.memory_learning].filter(Boolean).length} avvisi attivi`}>
            {(
              [
                ['event_alerts', 'Avvisi prima degli appuntamenti', 'Dal tuo Google Calendar'],
                ['mail_bubbles', 'Bolle nuove email', 'Dal cuore di AXEL, per ogni email in arrivo'],
                ['email_alerts', 'Email importanti', 'Filtrate da Claude: avviso anche su Telegram'],
                ['evening_recap', 'Riepilogo serale', 'Giornata, email senza risposta, cosa c’è domani'],
                ['shipments', 'Spedizioni', 'Pacchi in arrivo letti dalle email: avviso quando sono in consegna'],
                ['memory_learning', 'Memoria che impara', 'Ogni sera estrae dalle conversazioni cosa ricordare'],
              ] as const
            ).map(([key, label, hint]) => (
              <div key={key} className="row-between toggle-row">
                <span>
                  <span className="small">{label}</span>
                  <br />
                  <em className="dim small">{hint}</em>
                </span>
                <label className="switch">
                  <input
                    type="checkbox"
                    checked={pro[key]}
                    onChange={(e) => {
                      const p = { ...pro, [key]: e.target.checked }
                      setPro(p)
                      run('pro', () => saveToggles(p))
                    }}
                  />
                  <span />
                </label>
              </div>
            ))}
            <div className="row-between">
              <label className="inline">
                <span className="mono label">controlla email ogni</span>
                <select value={pro.email_interval_min} onChange={(e) => { const p = { ...pro, email_interval_min: +e.target.value }; setPro(p); run('pro', () => saveToggles(p), 'Salvato') }}>
                  {[2, 5, 10, 15, 30].map((m) => <option key={m} value={m}>{m} minuti</option>)}
                </select>
              </label>
              <button className="pill ghost sm" onClick={() => run('mt', api.mailTest)}>Prova bolla</button>
            </div>
            <div className="row">
              <label>
                <span className="mono label">minuti prima</span>
                <input type="number" min={1} max={120} value={pro.event_lead_min} onFocus={() => setBusy('pro-edit')}
                  onChange={(e) => setPro({ ...pro, event_lead_min: +e.target.value })}
                  onBlur={() => run('pro', () => saveToggles(pro), 'Salvato')} />
              </label>
              <label>
                <span className="mono label">ora riepilogo</span>
                <input type="time" value={pro.recap_time} onFocus={() => setBusy('pro-edit')}
                  onChange={(e) => setPro({ ...pro, recap_time: e.target.value })}
                  onBlur={() => run('pro', () => saveToggles(pro), 'Salvato')} />
              </label>
            </div>
            <p className="dim small">Gli avvisi arrivano su Telegram e, se l’app è aperta, AXEL te li dice a voce.</p>
          </Card>
        )}
        <Card id="tasks" title="Compiti ricorrenti" summary={tasks.length ? `${tasks.length} programmati` : 'nessuno'}>
          {tasks.length === 0 && (
            <p className="dim small">Dettali a voce: "ogni venerdì alle 18 fammi il riepilogo della settimana e delle email senza risposta".</p>
          )}
          <ul className="list">
            {tasks.map((t) => (
              <li key={t.id}>
                <span>
                  <b>{t.title}</b> <em className="dim">· {REC[t.recurrence] || 'una volta'}</em>
                  <br />
                  <span className="dim">prossima: {fmtDue(t.due_at)}</span>
                </span>
                <button className="icon-btn sm" onClick={() => run('t', () => api.deleteTask(t.id))} aria-label="Elimina">
                  <Icon name="trash" size={14} />
                </button>
              </li>
            ))}
          </ul>
        </Card>
        <Card id="reminders" title="Promemoria" summary={rems.length ? `${rems.length} attivi` : 'nessuno'}>
          {rems.length === 0 && <p className="dim small">Nessuno. Prova a dire: "ricordami domani alle 9 di chiamare Marco".</p>}
          <ul className="list">
            {rems.map((r) => (
              <li key={r.id}>
                <span>
                  <b>{fmtDue(r.due_at)}</b> {REC[r.recurrence] && <em className="dim">· {REC[r.recurrence]}</em>}
                  <br />
                  {r.text}
                </span>
                <button className="icon-btn sm" onClick={() => run('r', () => api.deleteReminder(r.id))} aria-label="Elimina">
                  <Icon name="trash" size={14} />
                </button>
              </li>
            ))}
          </ul>
        </Card>
        <EmailRulesCard open={integrationsOpen} />
        <BackgroundCard open={integrationsOpen} />
          </>
        )}
        {tab === 'info' && (
          <>
        <NewsCard open={integrationsOpen} />
        <ShipmentsCard open={integrationsOpen} />
        <MapsCard open={integrationsOpen} />
          </>
        )}
        {tab === 'system' && (
          <>
        <VoiceSpeedCard open={integrationsOpen} />
        <BackupCard open={integrationsOpen} />
        <Card id="mac" title="Controllo del Mac" status={info?.mac ? 'on' : 'off'} summary={info?.mac ? 'attivo' : 'solo su macOS'}>
          <p className="dim small">
            {info?.mac
              ? 'Attivo. La prima volta macOS chiederà dei permessi (Automazione per Note e Finder, Registrazione schermo per gli screenshot) all’app da cui avvii il backend: concedili. Cestino, spostamenti e comandi da terminale chiedono sempre conferma.'
              : 'Disponibile quando il backend gira su macOS.'}
          </p>
        </Card>
          </>
        )}
        {tab === 'memory' && (
          <>
        <LearningCard open={integrationsOpen} />
        <Card id="memories" title="Ricordi" summary={`${mems.length} salvati`}>
          {(
            <ul className="list">
              {mems.map((m) => (
                <li key={m.id}>
                  <span>
                    <em className="mono dim">{m.category}</em>
                    <br />
                    {m.content}
                  </span>
                  <button className="icon-btn sm" onClick={() => run('m', () => api.deleteMemory(currentId, m.id))} aria-label="Elimina">
                    <Icon name="trash" size={14} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card id="claude" title="Chat di claude.ai" summary={claude ? `${claude.conversations} chat importate` : 'non importate'}>
          <p className="dim small">
            Su claude.ai vai in Impostazioni → Privacy → Esporta dati: ti arriva via email uno .zip. Caricalo qui e AXEL potrà cercare nelle tue chat.
          </p>
          <label className="pill ghost sm file">
            <BusyLabel busy={busy === 'imp'} text="Carica export (.zip o .json)" busyText="Importo…" />
            <input
              type="file"
              accept=".zip,.json"
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (!f) return
                run('imp', async () => {
                  const r = await api.importClaude(f)
                  toast(`Importate ${r.conversations} chat (${r.messages} messaggi)${r.skipped ? `, ${r.skipped} già presenti` : ''}`, 'ok')
                })
                e.target.value = ''
              }}
            />
          </label>
        </Card>
          </>
        )}
      </div>
      </AccordionCtx.Provider>
    </aside>
  )
}