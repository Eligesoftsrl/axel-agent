import { live } from '../store'

/* ============================================================
 *  SINTESI VOCALE (TTS) — legge la risposta mentre arriva
 *  Due modi:
 *  - voci del browser (Web Speech API);
 *  - voci dal backend ("google:<voce>" = Google Cloud TTS, "mac:<voce>" = voci di macOS):
 *    audio vero, frase per frase con la successiva già pronta, bocca sincronizzata sul volume reale.
 * ============================================================ */

export const isServerVoice = (v: string) => v.startsWith('google:') || v.startsWith('mac:')

const synth = typeof window !== 'undefined' ? window.speechSynthesis : undefined

export function listVoices(): SpeechSynthesisVoice[] {
  return synth?.getVoices() ?? []
}

export function onVoicesReady(cb: () => void) {
  if (!synth) return
  if (synth.getVoices().length) cb()
  synth.addEventListener('voiceschanged', cb)
}

export class Speaker {
  private buffer = ''
  private queue = 0
  private finished = false
  private voiceName = ''
  private consumed = 0 // caratteri della risposta già passati alla sintesi
  enabled = true
  onStart?: () => void
  onEnd?: () => void
  /** chiamato se la voce del backend non è disponibile (si passa alla voce del browser) */
  onServerError?: (msg: string) => void
  private gen = 0
  private chain: Promise<void> = Promise.resolve()
  private current?: HTMLAudioElement
  private audioCtx?: AudioContext
  private analyser?: AnalyserNode
  private serverFailed = false

  setVoice(name: string) {
    this.voiceName = name
  }

  /** Aggiunge testo in streaming; parla appena ha una frase completa. */
  push(delta: string) {
    this.buffer += delta
    const re = /^([\s\S]*?[.!?;:\n])\s/
    let m
    while ((m = this.buffer.match(re)) && m[1].trim().length > 12) {
      this.speakChunk(m[1], this.consumed)
      this.consumed += m[0].length
      this.buffer = this.buffer.slice(m[0].length)
    }
  }

  /** Fine stream: legge il resto. */
  flush() {
    this.finished = true
    if (this.buffer.trim()) this.speakChunk(this.buffer, this.consumed)
    this.consumed += this.buffer.length
    this.buffer = ''
    if (this.queue === 0) this.end()
  }

  reset() {
    synth?.cancel()
    this.gen++
    this.chain = Promise.resolve()
    if (this.current) {
      this.current.pause()
      this.current.removeAttribute('src')
      this.current = undefined
    }
    this.buffer = ''
    this.queue = 0
    this.consumed = 0
    this.finished = false
    live.levelTarget = 0
    live.spoken = 0
  }

  private speakChunk(text: string, start: number) {
    const lead = text.length - text.trimStart().length
    const clean = text.replace(/[*#_`>|]/g, '').trim()
    if (!clean) return
    const base = start + lead
    if (this.enabled && isServerVoice(this.voiceName) && !this.serverFailed) {
      this.speakServer(clean, base)
      return
    }
    if (!this.enabled || !synth) {
      // senza audio: anima comunque la bocca per una durata stimata
      this.queue++
      if (this.queue === 1) this.onStart?.()
      const ms = clean.length * 55
      const t0 = performance.now()
      const iv = setInterval(() => {
        live.levelTarget = 0.35 + Math.random() * 0.6
        live.spoken = Math.max(live.spoken, base + ((performance.now() - t0) / ms) * clean.length)
      }, 90)
      setTimeout(() => {
        clearInterval(iv)
        live.spoken = Math.max(live.spoken, base + clean.length)
        this.done()
      }, ms)
      return
    }
    const u = new SpeechSynthesisUtterance(clean)
    const v = listVoices().find((x) => x.name === this.voiceName)
      ?? listVoices().find((x) => x.lang.startsWith('it'))
    if (v) {
      u.voice = v
      u.lang = v.lang
    } else u.lang = 'it-IT'
    u.rate = 1.02
    u.pitch = 0.9

    let iv: ReturnType<typeof setInterval> | undefined
    u.onstart = () => {
      if (this.queue === 1) this.onStart?.()
      // la Web Speech API non espone l'audio: simuliamo l'inviluppo
      // alcune voci (es. quelle Google di Chrome) non emettono onboundary:
      // stima l'avanzamento dal tempo (~15 caratteri/s), le boundary vere lo correggono
      const t0 = performance.now()
      iv = setInterval(() => {
        live.levelTarget = 0.25 + Math.random() * 0.55
        const est = base + Math.min(clean.length - 1, (performance.now() - t0) / 66)
        live.spoken = Math.max(live.spoken, est)
      }, 85)
    }
    u.onboundary = (e) => {
      live.levelTarget = 0.9
      live.pulse = 1
      // illumina la parola in pronuncia
      const len = e.charLength || (clean.slice(e.charIndex).match(/^\S+/)?.[0].length ?? 1)
      live.spoken = Math.max(live.spoken, base + e.charIndex + len)
    }
    const fin = () => {
      clearInterval(iv)
      live.spoken = Math.max(live.spoken, base + clean.length)
      this.done()
    }
    u.onend = fin
    u.onerror = fin
    this.queue++
    synth.speak(u)
  }

  /* ---------- voce dal backend ---------- */

  private fetchAudio(text: string): Promise<string> {
    return fetch('/api/tts', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text, voice: this.voiceName }),
    }).then(async (r) => {
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? `errore ${r.status}`)
      return URL.createObjectURL(await r.blob())
    })
  }

  private speakServer(clean: string, base: number) {
    this.queue++
    const gen = this.gen
    const audio = this.fetchAudio(clean) // parte subito: mentre suona la frase prima, questa si prepara
    audio.catch(() => {}) // gestito sotto
    this.chain = this.chain.then(async () => {
      if (gen !== this.gen) return
      try {
        const url = await audio
        if (gen !== this.gen) return URL.revokeObjectURL(url)
        await this.play(url, clean, base, gen)
        URL.revokeObjectURL(url)
      } catch (e) {
        if (gen !== this.gen) return
        // voce del backend non disponibile: avvisa una volta e continua con la voce del browser
        this.serverFailed = true
        this.onServerError?.((e as Error).message)
        setTimeout(() => (this.serverFailed = false), 60000)
        this.onStart?.()
        await new Promise<void>((res) => {
          // tempo massimo: se la voce del browser non risponde non restiamo bloccati
          const timer = setTimeout(res, 2000 + clean.length * 90)
          const ok = () => {
            clearTimeout(timer)
            res()
          }
          if (!synth) return ok()
          const u = new SpeechSynthesisUtterance(clean)
          const v = listVoices().find((x) => x.lang.startsWith('it'))
          if (v) u.voice = v
          u.lang = 'it-IT'
          u.onend = u.onerror = ok
          synth.speak(u)
        })
      }
      if (gen === this.gen) {
        live.spoken = Math.max(live.spoken, base + clean.length)
        this.done()
      }
    })
  }

  private ensureAnalyser(): boolean {
    try {
      if (!this.audioCtx) {
        this.audioCtx = new AudioContext()
        this.analyser = this.audioCtx.createAnalyser()
        this.analyser.fftSize = 512
        this.analyser.connect(this.audioCtx.destination)
      }
      if (this.audioCtx.state === 'suspended') void this.audioCtx.resume()
      return this.audioCtx.state === 'running'
    } catch {
      return false
    }
  }

  private play(url: string, clean: string, base: number, gen: number): Promise<void> {
    return new Promise((resolve) => {
      const el = new Audio(url)
      this.current = el
      const routed = this.ensureAnalyser() && !!this.analyser && !!this.audioCtx
      if (routed) {
        try {
          this.audioCtx!.createMediaElementSource(el).connect(this.analyser!)
        } catch {
          /* già collegato */
        }
      }
      const data = new Uint8Array(256)
      let raf = 0
      const tick = () => {
        if (gen !== this.gen || el.paused) return
        if (el.duration > 0) live.spoken = Math.max(live.spoken, base + Math.min(1, el.currentTime / el.duration) * clean.length)
        if (routed) {
          this.analyser!.getByteTimeDomainData(data)
          let sum = 0
          for (const v of data) sum += ((v - 128) / 128) ** 2
          live.levelTarget = Math.min(1, Math.sqrt(sum / data.length) * 5.5)
        } else {
          live.levelTarget = 0.25 + Math.random() * 0.55
        }
        raf = requestAnimationFrame(tick)
      }
      const finish = () => {
        cancelAnimationFrame(raf)
        live.levelTarget = 0
        if (this.current === el) this.current = undefined
        resolve()
      }
      el.onplay = () => {
        this.onStart?.()
        raf = requestAnimationFrame(tick)
      }
      el.onended = finish
      el.onerror = finish
      el.onpause = () => {
        if (gen !== this.gen) finish()
      }
      el.play().catch(finish)
    })
  }

  /** Prova una voce (anche del backend) con una frase. */
  async test(voice: string, text: string) {
    this.reset()
    const prev = this.voiceName
    this.voiceName = voice
    this.push(text + ' ')
    this.flush()
    this.voiceName = prev
  }

  private done() {
    this.queue = Math.max(0, this.queue - 1)
    live.levelTarget = 0
    if (this.queue === 0 && this.finished) this.end()
  }

  private end() {
    this.finished = false
    live.levelTarget = 0
    this.onEnd?.()
  }
}

/* ============================================================
 *  RICONOSCIMENTO VOCALE (STT) + livello microfono
 * ============================================================ */

type SR = {
  lang: string
  interimResults: boolean
  continuous: boolean
  start: () => void
  stop: () => void
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null
  onend: (() => void) | null
  onerror: ((e: { error: string }) => void) | null
}

export const sttSupported = () =>
  typeof window !== 'undefined' &&
  !!((window as unknown as Record<string, unknown>).SpeechRecognition ||
    (window as unknown as Record<string, unknown>).webkitSpeechRecognition)

export class Listener {
  private rec?: SR
  private stream?: MediaStream
  private raf = 0
  onInterim?: (t: string) => void
  onFinal?: (t: string) => void
  onStop?: () => void

  async start() {
    const W = window as unknown as Record<string, new () => SR>
    const Ctor = W.SpeechRecognition || W.webkitSpeechRecognition
    if (!Ctor) throw new Error('Riconoscimento vocale non supportato (usa Chrome o Edge)')
    const rec = new Ctor()
    rec.lang = 'it-IT'
    rec.interimResults = true
    rec.continuous = false
    let finalText = ''
    rec.onresult = (e) => {
      let interim = ''
      for (let i = 0; i < e.results.length; i++) {
        const r = e.results[i]
        if (r.isFinal) finalText += r[0].transcript
        else interim += r[0].transcript
      }
      this.onInterim?.(finalText + interim)
    }
    rec.onend = () => {
      this.stopMeter()
      if (finalText.trim()) this.onFinal?.(finalText.trim())
      this.onStop?.()
    }
    rec.onerror = () => {}
    this.rec = rec
    rec.start()
    this.startMeter()
  }

  stop() {
    this.rec?.stop()
  }

  private async startMeter() {
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const ctx = new AudioContext()
      const an = ctx.createAnalyser()
      an.fftSize = 512
      ctx.createMediaStreamSource(this.stream).connect(an)
      const data = new Uint8Array(an.frequencyBinCount)
      const tick = () => {
        an.getByteTimeDomainData(data)
        let sum = 0
        for (const v of data) sum += ((v - 128) / 128) ** 2
        live.mic = Math.min(1, Math.sqrt(sum / data.length) * 6)
        this.raf = requestAnimationFrame(tick)
      }
      tick()
    } catch {
      /* il meter è solo estetico */
    }
  }

  private stopMeter() {
    cancelAnimationFrame(this.raf)
    this.stream?.getTracks().forEach((t) => t.stop())
    live.mic = 0
  }
}
