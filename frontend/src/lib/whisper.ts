/**
 * Sorgente audio per le mani libere con Whisper locale:
 * - il microfono parte con cancellazione dell'eco e soppressione del rumore;
 * - un rilevatore di voce (Silero VAD, nel browser) registra solo quando qualcuno parla;
 * - ogni frase intera va al backend (/api/stt) che la trascrive con Whisper sul Mac.
 * Nessun audio esce dal computer.
 */
import { api } from './api'

export interface Segment {
  text: string
  confidence: number
  startedAt: number
  endedAt: number
  /** la frase è iniziata mentre AXEL parlava (o subito dopo) */
  duringSpeech: boolean
}

interface Opts {
  onSegment: (s: Segment) => void
  onSpeechStart: () => void
  onSpeechEnd?: () => void
  onMisfire: () => void
  onError: (msg: string) => void
  /** vero mentre AXEL sta parlando: decide come trattare l'audio catturato */
  isSpeaking: () => boolean
  /** decide se vale la pena trascrivere (es. in attesa di "Axel" scarta le frasi chiaramente non per lui) */
  shouldTranscribe?: (startedAt: number, endedAt: number, duringSpeech: boolean) => boolean
  /** livello del microfono 0..1 per l'animazione */
  onLevel?: (v: number) => void
}

type MicVADType = Awaited<ReturnType<typeof import('@ricky0123/vad-web').MicVAD.new>>

const MAX_DURING_SPEECH_S = 2.2 // mentre parla accetta solo frasi brevi (es. "stop")

export class WhisperSource {
  private vad?: MicVADType
  private startedAt = 0
  private startedDuringSpeech = false
  private opts: Opts
  private inflight = 0

  constructor(opts: Opts) {
    this.opts = opts
  }

  async start() {
    const { MicVAD } = await import('@ricky0123/vad-web')
    const base = `${location.origin}/vad/`
    this.vad = await MicVAD.new({
      model: 'v5',
      baseAssetPath: base,
      onnxWASMBasePath: base,
      positiveSpeechThreshold: 0.6,
      negativeSpeechThreshold: 0.4,
      redemptionMs: 480, // pausa che chiude la frase (più corta = risposta più rapida)
      preSpeechPadMs: 300,
      minSpeechMs: 300,
      getStream: () =>
        navigator.mediaDevices.getUserMedia({
          audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        }),
      onSpeechStart: () => {
        this.startedAt = Date.now()
        this.startedDuringSpeech = this.opts.isSpeaking()
        this.opts.onSpeechStart()
      },
      onVADMisfire: () => this.opts.onMisfire(),
      onFrameProcessed: (p) => this.opts.onLevel?.(p.isSpeech),
      onSpeechEnd: (audio) => {
        this.opts.onSpeechEnd?.()
        void this.process(audio)
      },
    })
    await this.vad.start()
  }

  private async process(audio: Float32Array) {
    const startedAt = this.startedAt
    const duringSpeech = this.startedDuringSpeech || this.opts.isSpeaking()
    const seconds = audio.length / 16000
    if (duringSpeech && seconds > MAX_DURING_SPEECH_S) return // è la sua voce, non un "stop"
    if (this.inflight > 1) return // frasi in coda (rumore continuo): salta
    if (this.opts.shouldTranscribe) {
      await new Promise((r) => setTimeout(r, 250)) // lascia arrivare le ultime parole del riconoscitore live
      if (!this.opts.shouldTranscribe(startedAt, Date.now(), duringSpeech)) return
    }
    this.inflight++
    try {
      const r = await api.stt(encodeWav(audio))
      if (r.text) this.opts.onSegment({ text: r.text, confidence: r.confidence, startedAt, endedAt: Date.now(), duringSpeech })
    } catch (e) {
      this.opts.onError((e as Error).message)
    } finally {
      this.inflight--
    }
  }

  async stop() {
    try {
      await this.vad?.destroy()
    } catch {
      /* ignore */
    }
    this.vad = undefined
  }
}

/** Float32 [-1,1] a 16 kHz → WAV PCM 16 bit mono */
export function encodeWav(samples: Float32Array, rate = 16000): Blob {
  const buf = new ArrayBuffer(44 + samples.length * 2)
  const v = new DataView(buf)
  const w = (o: number, s: string) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)))
  w(0, 'RIFF')
  v.setUint32(4, 36 + samples.length * 2, true)
  w(8, 'WAVE')
  w(12, 'fmt ')
  v.setUint32(16, 16, true)
  v.setUint16(20, 1, true)
  v.setUint16(22, 1, true)
  v.setUint32(24, rate, true)
  v.setUint32(28, rate * 2, true)
  v.setUint16(32, 2, true)
  v.setUint16(34, 16, true)
  w(36, 'data')
  v.setUint32(40, samples.length * 2, true)
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]))
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true)
  }
  return new Blob([buf], { type: 'audio/wav' })
}
