import { live, useStore, type ChatMessage } from '../store'
import { api, streamChat } from './api'
import { handsFree } from './handsfree'
import { correct, setVocabulary } from './vocab'
import { playNotify } from './sounds'
import { Listener, Speaker } from './voice'

/** Orchestratore: collega chat, voce e stato dell'avatar. */

export const speaker = new Speaker()
const listener = new Listener()
let abort: AbortController | undefined

speaker.onStart = () => {
  if (useStore.getState().state !== 'speaking') useStore.getState().set({ state: 'speaking' })
}
speaker.onServerError = (msg) => toast(`Voce di AXEL: ${msg} Uso la voce del browser.`, 'error')
speaker.onEnd = () => {
  const s = useStore.getState()
  if (s.state === 'speaking') s.set({ state: 'idle' })
  handsFree.afterSpeak() // conversazione continua
}

/* ---------- mani libere ---------- */

let interimSink: (t: string) => void = () => {}

export function setInterimSink(fn: (t: string) => void) {
  interimSink = fn
}

handsFree.setCallbacks({
  onCommand: (text) => send(correct(text)),
  onInterim: (t) => interimSink(t),
  onBargeIn: () => {
    stop()
    toast('Ok, mi fermo.', 'info')
  },
  onError: (msg) => toast(msg, 'error'),
  onEngine: (engine, note) => {
    if (engine === 'whisper') toast('Voce locale Whisper attiva', 'ok')
    else if (note) toast(note, 'info')
  },
})

export function setHandsFree(on: boolean) {
  if (on) handsFree.enable()
  else handsFree.disable()
  try {
    localStorage.setItem('axel.handsfree', on ? '1' : '0')
  } catch {
    /* ignore */
  }
  if (on) toast('Mani libere attive: di\' «Axel» quando vuoi', 'ok')
}

export function restoreHandsFree() {
  try {
    if (localStorage.getItem('axel.handsfree') === '1') handsFree.enable()
  } catch {
    /* ignore */
  }
}

export async function boot() {
  const { set } = useStore.getState()
  try {
    const [agents, tools, health, vocab] = await Promise.all([api.agents(), api.tools(), api.health(), api.vocabulary()])
    setVocabulary(vocab)
    const saved = localStorage.getItem('axel.agent')
    const current = agents.find((a) => a.id === saved) ?? agents[0]
    set({ agents, tools, demo: health.demo, currentId: current?.id ?? '' })
    speaker.setVoice(current?.voice ?? '')
  } catch {
    set({ activity: 'Backend non raggiungibile su /api — avvia uvicorn' })
  }
}

export function selectAgent(id: string) {
  const s = useStore.getState()
  stop()
  try {
    localStorage.setItem('axel.agent', id)
  } catch {
    /* ignore */
  }
  s.set({ currentId: id, messages: [], partial: '' })
  speaker.setVoice(s.agents.find((a) => a.id === id)?.voice ?? '')
}

export function stop() {
  abort?.abort()
  speaker.reset()
  useStore.getState().set({ state: 'idle' })
}

const GAL_NEXT = /^(?:axel[,\s]*)?(avanti|prossima|successiva|vai avanti|next|dopo|la prossima)[.!]?$/i
const GAL_PREV = /^(?:axel[,\s]*)?(indietro|precedente|torna indietro|prima|quella prima)[.!]?$/i
const GAL_CLOSE = /^(?:axel[,\s]*)?(chiudi|chiudi (?:la )?galleria|esci|basta(?: foto)?|ok basta)[.!]?$/i
const GAL_PLAY = /^(?:axel[,\s]*)?(presentazione|fai partire|avvia (?:la )?presentazione|scorri da sol[ae])[.!]?$/i

export async function send(text: string, attachments: import('../store').Attachment[] = []) {
  const s = useStore.getState()
  // galleria aperta: "avanti", "indietro", "chiudi" la comandano direttamente (niente Claude, niente Spotify)
  if (s.gallery && !attachments.length) {
    const t = text.trim()
    const { galleryNav } = await import('../ui/Gallery')
    if (GAL_NEXT.test(t)) return galleryNav.go(1)
    if (GAL_PREV.test(t)) return galleryNav.go(-1)
    if (GAL_CLOSE.test(t)) return galleryNav.close()
    if (GAL_PLAY.test(t)) return galleryNav.play()
  }
  const agent = s.current()
  if ((!text.trim() && !attachments.length) || !agent) return
  if (!text.trim()) text = 'Analizza questo file e dimmi le cose importanti.'
  stop()
  speaker.reset()
  speaker.setVoice(agent.voice)

  const history: ChatMessage[] = [...s.messages, { role: 'user', content: text.trim(), ...(attachments.length ? { attachments } : {}) }]
  s.set({ messages: history, partial: '', state: 'thinking', activity: 'connessione al nucleo…' })
  abort = new AbortController()

  let reply = ''
  const usedTools: string[] = []
  const files: import('../store').OutputFile[] = []
  let gotMusic = false
  try {
    for await (const ev of streamChat(agent.id, history, abort.signal, s.conversationId)) {
      const set = useStore.getState().set
      if (ev.type === 'text') {
        reply += ev.delta
        live.pulse = Math.min(1, live.pulse + 0.15)
        set({ partial: reply, activity: '' })
        speaker.push(ev.delta)
      } else if (ev.type === 'tool_use') {
        usedTools.push(ev.name)
        live.pulse = 1
        set({ state: 'thinking', activity: `strumento · ${ev.name}` })
      } else if (ev.type === 'tool_result') {
        set({ activity: `${ev.name} ✓` })
      } else if (ev.type === 'file') {
        files.push(ev.file)
        set({ outputs: { files: [...files], at: Date.now() } })
        playNotify()
      } else if (ev.type === 'meta') {
        set({ lastModel: ev.model })
      } else if (ev.type === 'widget') {
        if (ev.widget === 'gallery') {
          set({ gallery: { data: ev.data, at: Date.now() } })
          playNotify()
        } else if (ev.widget === 'spotify') {
          gotMusic = true
          set({ music: { data: ev.data, at: Date.now() } })
        }
        else set({ widget: { kind: ev.widget, data: ev.data as import('./api').WeatherData, at: Date.now() } })
        playNotify()
      } else if (ev.type === 'confirm') {
        live.pulse = 1
        set({ pending: [...useStore.getState().pending, ev.action] })
      } else if (ev.type === 'error') {
        throw new Error(ev.message)
      }
    }
    speaker.flush()
    // rete di sicurezza: comando Spotify eseguito ma la scheda non è arrivata (Spotify lento ad aggiornarsi)
    if (!gotMusic && usedTools.some((t) => t.startsWith('spotify_') || t === 'corsia veloce') && !useStore.getState().music) {
      for (const delay of [1500, 3500]) {
        setTimeout(() => {
          if (useStore.getState().music) return
          api.spotifyState().then((r) => r.data && useStore.getState().set({ music: { data: r.data, at: Date.now() } })).catch(() => {})
        }, delay)
      }
    }
  } catch (e) {
    if ((e as Error).name === 'AbortError') return
    reply = reply || `Errore: ${(e as Error).message}`
    speaker.reset()
    useStore.getState().set({ state: 'idle' })
  }
  useStore.getState().set({
    messages: [...history, { role: 'assistant', content: reply.trim(), tools: usedTools, ...(files.length ? { files } : {}) }],
    activity: '',
  })
}

export async function toggleListen(onInterim: (t: string) => void) {
  const s = useStore.getState()
  if (handsFree.enabled) {
    // in mani libere il microfono è già aperto: basta passare in ascolto di un comando
    interimSink = onInterim
    handsFree.listenForCommand()
    return
  }
  if (s.state === 'listening') {
    listener.stop()
    return
  }
  stop()
  listener.onInterim = onInterim
  listener.onFinal = (t) => {
    onInterim('')
    send(correct(t))
  }
  listener.onStop = () => {
    if (useStore.getState().state === 'listening') useStore.getState().set({ state: 'idle' })
  }
  try {
    s.set({ state: 'listening' })
    await listener.start()
  } catch (e) {
    s.set({ state: 'idle', activity: (e as Error).message })
  }
}

/* ---------- conferme azioni ---------- */

export async function resolveAction(id: string, approve: boolean) {
  const s = useStore.getState()
  s.set({ pending: s.pending.filter((p) => p.id !== id) })
  try {
    const res = approve ? await api.approve(id) : await api.reject(id)
    const msg = approve ? (res.ok ? `Fatto. ${res.result}` : res.result) : 'Va bene, annullato.'
    const st = useStore.getState()
    const msgs = [...st.messages]
    const last = msgs[msgs.length - 1]
    // accoda all'ultima risposta (l'API vuole ruoli alternati)
    if (last?.role === 'assistant') msgs[msgs.length - 1] = { ...last, content: `${last.content}\n\n[${msg}]` }
    else msgs.push({ role: 'assistant', content: msg })
    st.set({ messages: msgs })
    toast(msg, approve && res.ok ? 'ok' : 'info')
    speaker.reset()
    speaker.push(approve ? (res.ok ? 'Fatto.' : 'Non ci sono riuscito.') : 'Annullato.')
    speaker.flush()
  } catch (e) {
    toast(`Errore: ${(e as Error).message}`, 'error')
  }
}

/* ---------- notifiche (promemoria, briefing) ---------- */

let toastId = 0
export function toast(text: string, kind = 'info') {
  const id = ++toastId
  const s = useStore.getState()
  s.set({ toasts: [...s.toasts, { id, text, kind }] })
  setTimeout(() => {
    const st = useStore.getState()
    st.set({ toasts: st.toasts.filter((t) => t.id !== id) })
  }, kind === 'reminder' ? 12000 : 6000)
}

let lastNotif = -1
export function startNotificationPolling() {
  const poll = async () => {
    try {
      const r = await api.notifications(lastNotif)
      if (lastNotif >= 0) {
        let mailKey = Date.now()
        for (const n of r.items) {
          if (n.kind === 'mail') {
            try {
              const m = JSON.parse(n.text)
              const st = useStore.getState()
              st.set({ mailBubbles: [...st.mailBubbles, { ...m, key: mailKey++ }].slice(-6) })
              live.mailFlash = 1
              live.pulse = 1
              playNotify()
            } catch {
              /* ignore */
            }
            continue
          }
          if (n.kind === 'task_done') {
            try {
              const t = JSON.parse(n.text)
              const st = useStore.getState()
              st.set({ mailBubbles: [...st.mailBubbles, { key: mailKey++, id: t.id, from: t.title, subject: t.summary, snippet: t.summary, link: '', kind: 'task' as const }].slice(-6) })
              live.mailFlash = 1
              live.pulse = 1
              playNotify()
              if (st.state === 'idle') {
                speaker.reset()
                speaker.push(`Ho finito il compito: ${t.title}. `)
                speaker.flush()
              }
            } catch {
              /* ignore */
            }
            continue
          }
          if (n.kind === 'alert' && n.text.startsWith('✉️')) {
            playNotify()
            // l'email importante ha già la sua bolla: qui solo la voce
            if (useStore.getState().state === 'idle') {
              speaker.reset()
              speaker.push(n.text.replace('✉️', '').split('\n')[0] + ' ')
              speaker.flush()
            }
            continue
          }
          const label: Record<string, string> = {
            briefing: 'Briefing inviato ☀️',
            recap: 'Riepilogo serale inviato 🌙',
            task: `${n.text.split('\n')[0]} · inviato`,
          }
          toast(label[n.kind] ?? n.text.split('\n')[0], n.kind === 'alert' || n.kind === 'shipment' ? 'reminder' : n.kind)
          playNotify()
          // promemoria e avvisi vengono anche detti ad alta voce se AXEL è libero
          if ((n.kind === 'reminder' || n.kind === 'alert' || n.kind === 'shipment') && useStore.getState().state === 'idle') {
            speaker.reset()
            speaker.push(n.text.replace(/\p{Extended_Pictographic}|\uFE0F/gu, '').split('\n')[0] + ' ')
            speaker.flush()
          }
        }
      }
      lastNotif = r.last
    } catch {
      /* backend non raggiungibile: riprova */
    }
  }
  poll()
  return setInterval(poll, 15000)
}
