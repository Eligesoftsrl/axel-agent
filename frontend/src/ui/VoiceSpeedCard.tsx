import { useCallback, useEffect, useState } from 'react'
import { api, type SpeedSettings, type SttStatus, type UsageRow } from '../lib/api'
import { toast } from '../lib/controller'
import { handsFree, type VoiceEngine } from '../lib/handsfree'
import { useStore } from '../store'
import { BusyLabel, Card } from './Card'

/** Pannello "Voce e velocità": Whisper locale, corsia veloce, scelta automatica del modello, consumi di oggi. */

const fmt = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : String(n))

export function VoiceSpeedCard({ open }: { open: boolean }) {
  const engineNow = useStore((s) => s.voiceEngine)
  const [speed, setSpeed] = useState<SpeedSettings | null>(null)
  const [stt, setStt] = useState<SttStatus | null>(null)
  const [usage, setUsage] = useState<UsageRow[]>([])
  const [pref, setPref] = useState<VoiceEngine>(handsFree.preferredEngine())
  const [warming, setWarming] = useState(false)

  const load = useCallback(async () => {
    try {
      const [sp, st, us] = await Promise.all([api.speed(), api.sttStatus(), api.usage(1)])
      setSpeed(sp)
      setStt(st)
      setUsage(us)
    } catch {
      /* backend giù */
    }
  }, [])

  useEffect(() => {
    if (!open) return
    load()
    const iv = setInterval(load, 8000)
    return () => clearInterval(iv)
  }, [open, load])

  const save = async (patch: Partial<SpeedSettings>) => {
    if (!speed) return
    setSpeed({ ...speed, ...patch })
    try {
      setSpeed(await api.saveSpeed(patch))
    } catch (e) {
      toast(`Errore: ${(e as Error).message}`, 'error')
    }
  }

  const warmup = async () => {
    setWarming(true)
    try {
      setStt(await api.sttWarmup())
      toast('Modello Whisper pronto', 'ok')
    } catch (e) {
      toast((e as Error).message.replace(/^\d+ /, ''), 'error')
    }
    setWarming(false)
  }

  const today = usage.filter((u) => u.day === usage[0]?.day)
  const llm = today.filter((u) => u.channel !== 'fastlane')
  const fast = today.filter((u) => u.channel === 'fastlane').reduce((a, u) => a + u.calls, 0)
  const calls = llm.reduce((a, u) => a + u.calls, 0)
  const input = llm.reduce((a, u) => a + u.input + u.cache_read + u.cache_write, 0)
  const cached = llm.reduce((a, u) => a + u.cache_read, 0)
  const out = llm.reduce((a, u) => a + u.output, 0)
  const haiku = llm.filter((u) => u.model.includes('haiku')).reduce((a, u) => a + u.calls, 0)
  const ms = llm.filter((u) => u.avg_ms).map((u) => u.avg_ms as number)
  const avgMs = ms.length ? Math.round(ms.reduce((a, b) => a + b, 0) / ms.length) : 0

  return (
    <Card id="voice" title="Voce e velocità" status={stt?.available ? 'on' : 'warn'} summary={stt?.available ? `Whisper ${stt.quality === 'fast' ? 'veloce' : 'preciso'}${calls ? ` · ${calls} richieste oggi` : ''}` : 'riconoscimento del browser'}>

      <div className="row-between">
        <span>
          <span className="small">Riconoscimento vocale</span>
          <br />
          <em className="dim small">
            {stt?.available
              ? `Whisper locale · ${stt.engine === 'mlx' ? 'chip Apple' : 'CPU'} · ${stt.model}${stt.loaded ? ' · pronto' : ' · da caricare'}`
              : 'Whisper non installato: uso il browser (vedi README, «Voce locale»)'}
            {engineNow && ` · ora in uso: ${engineNow === 'whisper' ? 'Whisper' : 'browser'}`}
          </em>
        </span>
      </div>
      <div className="seg three">
        {(
          [
            ['auto', 'Automatico'],
            ['whisper', 'Whisper'],
            ['browser', 'Browser'],
          ] as const
        ).map(([k, l]) => (
          <button key={k} className={pref === k ? 'on' : ''} onClick={() => { setPref(k); void handsFree.setEngine(k) }}>
            {l}
          </button>
        ))}
      </div>
      {stt?.available && (
        <div className="row-between">
          <span className="small">
            Qualità Whisper
            <br />
            <em className="dim small">
              {stt.avg_ms != null ? `trascrizione media ${(stt.avg_ms / 1000).toFixed(1)} s · ultima ${((stt.last_ms ?? 0) / 1000).toFixed(1)} s` : 'nessuna frase ancora'}
            </em>
          </span>
          <div className="seg" style={{ minWidth: 170, marginBottom: 0 }}>
            {(
              [
                ['fast', 'Veloce'],
                ['accurate', 'Precisa'],
              ] as const
            ).map(([k, l]) => (
              <button
                key={k}
                className={stt.quality === k ? 'on' : ''}
                onClick={async () => {
                  try {
                    setStt(await api.sttQuality(k))
                    void warmup()
                  } catch (e) {
                    toast((e as Error).message, 'error')
                  }
                }}
              >
                {l}
              </button>
            ))}
          </div>
        </div>
      )}
      {stt?.available && !stt.loaded && (
        <button className="pill ghost sm" disabled={warming} onClick={warmup}>
          <BusyLabel busy={warming} text="Prepara il modello Whisper" busyText="Carico il modello…" />
        </button>
      )}
      {stt?.error && <p className="dim small">Ultimo errore: {stt.error}</p>}

      {speed && (
        <>
          {(
            [
              ['fastlane', 'Corsia veloce', 'Luci, musica, volume e ora eseguiti subito, senza Claude'],
              ['router', 'Modello automatico', 'Haiku per le richieste brevi, il modello principale per il resto'],
            ] as const
          ).map(([key, label, hint]) => (
            <div key={key} className="row-between toggle-row">
              <span>
                <span className="small">{label}</span>
                <br />
                <em className="dim small">{hint}</em>
              </span>
              <label className="switch">
                <input type="checkbox" checked={speed[key]} onChange={(e) => save({ [key]: e.target.checked })} />
                <span />
              </label>
            </div>
          ))}
        </>
      )}

      <div className="usage-grid">
        <div><span className="mono label">richieste oggi</span>{calls}{fast ? <em className="dim"> + {fast} veloci</em> : null}</div>
        <div><span className="mono label">da cache</span>{input ? Math.round((cached / input) * 100) : 0}%</div>
        <div><span className="mono label">token in / out</span>{fmt(input)} / {fmt(out)}</div>
        <div><span className="mono label">prima parola</span>{avgMs ? `${(avgMs / 1000).toFixed(1)} s` : '–'}</div>
      </div>
      {calls > 0 && <p className="dim small">{haiku} risposte su {calls} date da Haiku.</p>}
    </Card>
  )
}
