import { live, useStore } from '../store'
import { api } from './api'
import type { Segment, WhisperSource } from './whisper'

export type VoiceEngine = 'auto' | 'whisper' | 'browser'

/**
 * Modalità "mani libere":
 * - ascolto continuo della parola di attivazione "Axel" (anche "Axel, che ore sono?" in un'unica frase);
 * - dopo una risposta a una domanda fatta a voce resta in ascolto qualche secondo per il seguito
 *   (non dopo avvisi, notifiche o messaggi scritti), scartando rumori, frasi spezzate ed eco;
 * - mentre parla non ascolta nulla tranne "stop", "basta", "fermati", "aspetta" detti da soli.
 * Usa la Web Speech API di Chrome/Edge (riconoscimento continuo, riavviato automaticamente).
 */

type Rec = {
  lang: string
  continuous: boolean
  interimResults: boolean
  start: () => void
  stop: () => void
  abort: () => void
  onresult: ((e: { resultIndex: number; results: ArrayLike<ArrayLike<{ transcript: string; confidence: number }> & { isFinal: boolean }> }) => void) | null
  onend: (() => void) | null
  onerror: ((e: { error: string }) => void) | null
}

const WAKE = /\b(?:ehi |hey |ok )?(axel|axl|aksel|acsel|accel|axe l|ax el|exel|aksell)\b[,.!?]?\s*/i
/** varianti che Whisper a volte produce per "Axel", valide solo a inizio frase */
const WAKE_START = /^\s*(?:ehi |hey |ok )?(excel|axe|access|ascel|axell|hexel)\b[,.!?]?\s*/i
const STOP = /\b(stop|basta|fermati|ferma|aspetta|silenzio|zitto)\b/i
const FOLLOW_UP_MS = 6000
const COMMAND_MS = 8000
/** Chrome consegna i risultati anche 1-2 s dopo l'audio: tutto ciò che arriva in questa finestra è la sua voce. */
const AFTER_SPEAK_DEAF_MS = 1600
/** Risposte brevi valide anche da sole nel seguito della conversazione. */
const SHORT_OK = /^(si|sì|no|ok|okay|certo|vai|fallo|esatto|giusto|grazie|perfetto|annulla|conferma|confermo|dopo|ancora|altro|avanti|indietro|più forte|più piano)$/i
const MIN_CONFIDENCE = 0.55

interface Callbacks {
  onCommand: (text: string) => void
  onInterim: (text: string) => void
  onBargeIn: () => void
  onError: (msg: string) => void
  onEngine?: (engine: 'whisper' | 'browser', note?: string) => void
}

class HandsFree {
  enabled = false
  mode: 'wake' | 'command' = 'wake'
  private rec?: Rec
  private timer?: ReturnType<typeof setTimeout>
  private cb?: Callbacks
  private restarting = false
  private ignoreUntil = 0
  /** true quando l'ultimo turno è partito dalla voce: solo allora resta in ascolto del seguito */
  private voiceTurn = false
  /** ultime frasi dette da AXEL, per riconoscere l'eco */
  private recent: string[] = []
  /** motore attivo: Whisper locale (preferito) o riconoscimento del browser */
  active: 'whisper' | 'browser' = 'browser'
  private whisper?: WhisperSource
  private generation = 0
  /** con Whisper attivo, il riconoscitore del browser serve solo a mostrare le parole in tempo reale */
  private liveWords = false
  private recBackoff = 0
  private interimTimer?: ReturnType<typeof setTimeout>

  supported() {
    const W = window as unknown as Record<string, unknown>
    return !!(W.SpeechRecognition || W.webkitSpeechRecognition || navigator.mediaDevices?.getUserMedia)
  }

  preferredEngine(): VoiceEngine {
    try {
      return (localStorage.getItem('axel.voiceEngine') as VoiceEngine) || 'auto'
    } catch {
      return 'auto'
    }
  }

  /** Cambia motore (salvato nel browser) e riavvia l'ascolto se attivo. */
  async setEngine(e: VoiceEngine) {
    try {
      localStorage.setItem('axel.voiceEngine', e)
    } catch {
      /* ignore */
    }
    if (this.enabled) {
      this.disable()
      this.enable()
    }
  }

  setCallbacks(cb: Callbacks) {
    this.cb = cb
  }

  enable() {
    if (this.enabled || !this.supported()) return
    this.enabled = true
    this.mode = 'wake'
    this.publish()
    void this.start()
  }

  /** Sceglie il motore: Whisper se il backend lo ha (o se scelto), altrimenti il browser. */
  private async start() {
    const gen = ++this.generation
    const pref = this.preferredEngine()
    let note = ''
    if (pref !== 'browser') {
      try {
        const st = await api.sttStatus()
        if (gen !== this.generation || !this.enabled) return
        if (st.available) {
          const { WhisperSource } = await import('./whisper')
          const src = new WhisperSource({
            onSegment: (seg) => this.onSegment(seg),
            onSpeechStart: () => {
              live.mic = 0.7
              if (this.mode === 'command' && !this.speakingNow()) useStore.getState().set({ state: 'listening' })
            },
            onSpeechEnd: () => this.transcribing(),
            shouldTranscribe: (a, b, during) => this.shouldTranscribe(a, b, during),
            onMisfire: () => {},
            onError: (msg) => this.whisperFailed(msg),
            isSpeaking: () => this.speakingNow() || Date.now() < this.ignoreUntil,
            onLevel: (v) => {
              if (v > 0.5) live.mic = Math.max(live.mic, v * 0.6)
            },
          })
          await src.start()
          if (gen !== this.generation || !this.enabled) {
            void src.stop()
            return
          }
          this.whisper = src
          this.active = 'whisper'
          this.cb?.onEngine?.('whisper')
          // parole in tempo reale (solo visualizzazione) con il riconoscitore del browser, se c'è
          const W = window as unknown as Record<string, unknown>
          if (W.SpeechRecognition || W.webkitSpeechRecognition) {
            this.liveWords = true
            this.boot()
          }
          if (!st.loaded) void api.sttWarmup().catch((e) => this.whisperFailed((e as Error).message))
          this.publish()
          return
        }
        note = 'Whisper non installato: uso il riconoscimento del browser.'
      } catch (e) {
        console.warn('[AXEL] Whisper non avviato:', e)
        note = `Whisper non disponibile (${(e as Error).message}): uso il riconoscimento del browser.`
      }
      if (pref === 'whisper') this.cb?.onError(note)
    }
    if (gen !== this.generation || !this.enabled) return
    this.active = 'browser'
    this.cb?.onEngine?.('browser', pref === 'auto' ? undefined : note)
    this.boot()
    this.publish()
  }

  private whisperFailed(msg: string) {
    if (!this.enabled || this.active !== 'whisper') return
    this.cb?.onError(`Voce locale: ${msg}. Passo al riconoscimento del browser.`)
    void this.whisper?.stop()
    this.whisper = undefined
    this.active = 'browser'
    this.liveWords = false
    this.cb?.onEngine?.('browser', msg)
    if (!this.rec) this.boot() // se il riconoscitore "parole live" è già acceso, ora lavora lui
    this.publish()
  }

  /** Whisper sta trascrivendo una frase: se era per AXEL mostra i puntini. */
  private transcribing() {
    if (this.speakingNow() || Date.now() < this.ignoreUntil) return
    const st = useStore.getState()
    if (this.mode === 'command' || st.state === 'listening') {
      this.cb?.onInterim(`${this.lastInterim || ''} …`.trim())
      this.armInterimClear()
    }
  }

  private lastInterim = ''
  /** ultime frasi del riconoscitore live: servono a non far lavorare Whisper sulle frasi non rivolte ad AXEL */
  private wsLog: { at: number; wake: boolean }[] = []

  private shouldTranscribe(startedAt: number, endedAt: number, duringSpeech: boolean) {
    if (this.mode === 'command' || duringSpeech || !this.liveWords) return true
    const heard = this.wsLog.filter((e) => e.at >= startedAt - 300 && e.at <= endedAt + 400)
    if (!heard.length) return true // il browser non ha capito niente: meglio chiedere a Whisper
    return heard.some((e) => e.wake) // ha sentito parlare, ma senza "Axel": non è per lui
  }

  private armInterimClear() {
    clearTimeout(this.interimTimer)
    this.interimTimer = setTimeout(() => {
      // Whisper ha scartato la frase (rumore): pulisci e, se in attesa della parola chiave, torna a riposo
      this.lastInterim = ''
      this.cb?.onInterim('')
      if (this.mode === 'wake' && useStore.getState().state === 'listening') useStore.getState().set({ state: 'idle' })
    }, 6000)
  }

  /** Testo provvisorio dal browser mentre Whisper lavora: solo da vedere, mai eseguito. */
  private displayInterim(text: string) {
    if (!text || this.speakingNow() || Date.now() < this.ignoreUntil || this.isEcho(text)) return
    if (this.mode === 'wake') {
      const m = text.match(WAKE)
      if (!m) return
      live.pulse = 1
      if (useStore.getState().state === 'idle') useStore.getState().set({ state: 'listening' })
      this.lastInterim = text.slice((m.index ?? 0) + m[0].length).trim()
    } else {
      this.lastInterim = text.replace(WAKE, '').trim()
      live.mic = 0.6
    }
    this.cb?.onInterim(this.lastInterim)
    this.armInterimClear()
  }

  /** Frase completa trascritta da Whisper. */
  private onSegment(seg: Segment) {
    if (!this.enabled) return
    clearTimeout(this.interimTimer)
    this.lastInterim = ''
    this.handle(seg.text, true, seg.confidence, { at: seg.startedAt, duringSpeech: seg.duringSpeech })
  }

  disable() {
    this.enabled = false
    this.generation++
    this.liveWords = false
    clearTimeout(this.timer)
    clearTimeout(this.interimTimer)
    void this.whisper?.stop()
    this.whisper = undefined
    try {
      this.rec?.abort()
    } catch {
      /* ignore */
    }
    this.rec = undefined
    if (useStore.getState().state === 'listening') useStore.getState().set({ state: 'idle' })
    this.publish()
  }

  /** Passa subito in ascolto di un comando (es. tocco sul microfono o dopo la parola chiave). */
  listenForCommand(ms = COMMAND_MS) {
    if (!this.enabled) return
    this.mode = 'command'
    this.voiceTurn = true
    const s = useStore.getState()
    if (s.state === 'idle') s.set({ state: 'listening' })
    clearTimeout(this.timer)
    this.timer = setTimeout(() => this.backToWake(), ms)
    this.publish()
  }

  /** Chiamato quando AXEL ha finito di parlare: conversazione continua. */
  afterSpeak() {
    const said = useStore.getState().partial
    if (said) this.recent = [...this.recent, said].slice(-4)
    if (!this.enabled) return
    // butta via la "coda" della sua voce ancora in elaborazione nel riconoscitore
    this.ignoreUntil = Date.now() + AFTER_SPEAK_DEAF_MS
    if (this.rec) {
      try {
        this.rec.abort() // onend lo riavvia pulito
      } catch {
        /* ignore */
      }
    }
    // Resta in ascolto del seguito solo se gli hai parlato tu a voce
    // (non dopo un avviso, una notifica o un messaggio scritto).
    const follow = this.voiceTurn
    this.voiceTurn = false
    if (follow) this.listenForCommand(FOLLOW_UP_MS)
    else this.backToWake()
    this.voiceTurn = false
  }

  /** Mentre AXEL parla: non ascolta niente (tranne "stop"), anche se parla una notifica. */
  private speakingNow() {
    const st = useStore.getState().state
    return st === 'speaking' || st === 'thinking' || !!window.speechSynthesis?.speaking
  }

  /** Vero se la frase sentita è (quasi) un pezzo di ciò che AXEL ha appena detto. */
  private isEcho(text: string) {
    const n = (s: string) => s.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9 ]/g, ' ').replace(/\s+/g, ' ').trim()
    const t = n(text)
    if (!t) return false
    const replies = [useStore.getState().partial || '', ...this.recent].map(n).filter(Boolean)
    const tw = t.split(' ').filter((w) => w.length > 2)
    return replies.some((reply) => {
      if (t.length > 3 && reply.includes(t)) return true
      if (tw.length < 2) return false
      const rw = new Set(reply.split(' '))
      return tw.filter((w) => rw.has(w)).length / tw.length >= 0.5
    })
  }

  private backToWake() {
    this.mode = 'wake'
    this.voiceTurn = false
    this.cb?.onInterim('')
    if (useStore.getState().state === 'listening') useStore.getState().set({ state: 'idle' })
    this.publish()
  }

  private publish() {
    useStore.getState().set({
      handsFree: this.enabled,
      handsFreeMode: this.enabled ? this.mode : 'off',
      voiceEngine: this.enabled ? this.active : null,
    })
  }

  private boot() {
    const W = window as unknown as Record<string, new () => Rec>
    const Ctor = W.SpeechRecognition || W.webkitSpeechRecognition
    if (!Ctor) {
      this.cb?.onError('Questo browser non ha il riconoscimento vocale: usa Chrome o installa Whisper (vedi README).')
      this.disable()
      return
    }
    const rec = new Ctor()
    rec.lang = 'it-IT'
    rec.continuous = true
    rec.interimResults = true

    rec.onresult = (e) => {
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i]
        if (this.active === 'whisper') {
          const t = r[0].transcript.trim()
          this.wsLog = [...this.wsLog.filter((x) => Date.now() - x.at < 20000), { at: Date.now(), wake: WAKE.test(t) || WAKE_START.test(t) || /\b(ax|aks|acc|ex)[a-z]*l\b/i.test(t) }]
          this.displayInterim(t)
        }
        else this.handle(r[0].transcript.trim(), r.isFinal, r[0].confidence ?? 0)
      }
    }
    rec.onerror = (e) => {
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
        this.cb?.onError('Microfono non autorizzato: consenti l’accesso al microfono per usare le mani libere.')
        this.disable()
      }
      // 'no-speech', 'aborted', 'network': gestiti dal riavvio in onend (con pausa se è un errore vero)
      this.recBackoff = e.error === 'network' || e.error === 'audio-capture' ? Math.min(8000, (this.recBackoff || 1000) * 2) : 0
    }
    rec.onend = () => {
      // Chrome chiude la sessione dopo un po' di silenzio: la riapriamo
      if (this.enabled && (this.active === 'browser' || this.liveWords) && !this.restarting) {
        this.restarting = true
        const delay = this.recBackoff || 250
        setTimeout(() => {
          this.restarting = false
          if (!this.enabled || (this.active !== 'browser' && !this.liveWords)) return
          try {
            rec.start()
          } catch {
            this.boot()
          }
        }, delay)
      }
    }
    rec.onresult = ((orig) => (ev: Parameters<NonNullable<Rec['onresult']>>[0]) => {
      this.recBackoff = 0
      orig?.(ev)
    })(rec.onresult)
    this.rec = rec
    try {
      rec.start()
    } catch {
      /* già avviato */
    }
  }

  private handle(text: string, final: boolean, confidence = 0, meta?: { at: number; duringSpeech: boolean }) {
    const at = meta?.at ?? Date.now()
    if (!text || at < this.ignoreUntil) return
    if (this.isEcho(text)) return // è la voce di AXEL captata dal microfono
    // Whisper: una variante di "Axel" a inizio frase vale come parola chiave
    if (this.active === 'whisper' && !WAKE.test(text) && WAKE_START.test(text)) text = text.replace(WAKE_START, 'Axel, ')

    // Mentre parla o pensa ascolta SOLO un "stop" detto da solo (frase breve, definitiva)
    if (meta?.duringSpeech || this.speakingNow()) {
      const words = text.split(/\s+/).length
      if (final && words <= 3 && STOP.test(text)) {
        this.cb?.onBargeIn()
        this.listenForCommand()
      }
      return
    }

    if (this.mode === 'wake') {
      const m = text.match(WAKE)
      if (!m) return
      live.pulse = 1
      const rest = text.slice((m.index ?? 0) + m[0].length).trim()
      if (final) {
        if (rest.length > 2) {
          this.mode = 'wake'
          this.voiceTurn = true
          this.cb?.onInterim('')
          this.cb?.onCommand(rest)
        } else {
          this.listenForCommand()
        }
      } else {
        // reazione immediata: AXEL si mette in ascolto mentre stai ancora parlando
        if (useStore.getState().state === 'idle') useStore.getState().set({ state: 'listening' })
        if (rest) this.cb?.onInterim(rest)
      }
      return
    }

    // modalità comando (dopo "Axel" o nel seguito della conversazione)
    const named = WAKE.test(text)
    const clean = text.replace(WAKE, '').trim()
    live.mic = 0.6
    if (!final) {
      this.cb?.onInterim(clean)
      clearTimeout(this.timer)
      this.timer = setTimeout(() => this.backToWake(), COMMAND_MS)
      return
    }
    clearTimeout(this.timer)
    this.cb?.onInterim('')
    // filtro anti-rumore: frasi spezzate, a bassa confidenza o di una parola sola
    // (TV, persone nella stanza, eco) non vengono prese come comandi
    const words = clean.split(/\s+/).filter((w) => w.length > 1)
    const plausible = named || SHORT_OK.test(clean.replace(/[.,!?]/g, '').trim()) || (words.length >= 2 && (confidence === 0 || confidence >= MIN_CONFIDENCE))
    if (clean.length > 1 && plausible) {
      this.mode = 'wake'
      this.voiceTurn = true
      this.cb?.onCommand(clean)
      this.publish()
    } else {
      // rumore: resta in ascolto per il tempo rimasto, poi torna ad aspettare "Axel"
      this.timer = setTimeout(() => this.backToWake(), 2500)
    }
  }
}

export const handsFree = new HandsFree()
