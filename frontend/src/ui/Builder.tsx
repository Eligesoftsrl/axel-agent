import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { selectAgent } from '../lib/controller'
import { isServerVoice, listVoices, onVoicesReady } from '../lib/voice'
import { speaker } from '../lib/controller'
import { getVocabulary, setVocabulary } from '../lib/vocab'
import { useStore, type AgentConfig } from '../store'
import { Icon } from './Icon'

const MODELS = [
  { id: '', label: 'Default del server' },
  { id: 'claude-opus-5-5', label: 'Claude Opus 5.5 · massima qualità' },
  { id: 'claude-sonnet-5-5', label: 'Claude Sonnet 5.5 · bilanciato' },
  { id: 'claude-haiku-4-5-20251001', label: 'Claude Haiku 4.5 · più veloce' },
]

const PRESETS: { name: string; a: string; b: string }[] = [
  { name: 'Oceano', a: '#3ff0f7', b: '#1e7fe0' },
  { name: 'Abisso', a: '#7fd8ff', b: '#0b3fb0' },
  { name: 'Aurora', a: '#5dffb0', b: '#2b7bff' },
  { name: 'Solare', a: '#ffcf5a', b: '#ff3d7f' },
]

export function Builder() {
  const { builderOpen, agents, tools, currentId, set } = useStore()
  const agent = agents.find((a) => a.id === currentId)
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([])
  const [srv, setSrv] = useState<Awaited<ReturnType<typeof api.ttsVoices>> | null>(null)
  useEffect(() => {
    if (builderOpen) api.ttsVoices().then(setSrv).catch(() => {})
  }, [builderOpen])
  const [saving, setSaving] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')

  const [vocab, setVocab] = useState('')
  useEffect(() => {
    if (builderOpen) setVocab(getVocabulary().join(', '))
  }, [builderOpen])

  useEffect(() => {
    onVoicesReady(() => setVoices(listVoices()))
  }, [])

  if (!agent) return <aside className={`panel builder ${builderOpen ? 'open' : ''}`} />

  // modifica live: la scena 3D si aggiorna subito (colori, nome)
  const patch = (p: Partial<AgentConfig>) => {
    setSaving('idle')
    set({ agents: agents.map((a) => (a.id === agent.id ? { ...a, ...p } : a)) })
  }

  const save = async () => {
    setSaving('saving')
    try {
      await api.save(agent)
      setSaving('saved')
    } catch {
      setSaving('error')
    }
  }

  const create = async () => {
    const a = await api.create({ name: 'Nuovo agente' })
    set({ agents: [...useStore.getState().agents, a] })
    selectAgent(a.id)
  }

  const remove = async () => {
    if (agents.length <= 1 || !confirm(`Eliminare ${agent.name}?`)) return
    await api.remove(agent.id)
    const rest = agents.filter((a) => a.id !== agent.id)
    set({ agents: rest })
    selectAgent(rest[0].id)
  }

  const testVoice = () => {
    if (isServerVoice(agent.voice)) {
      void speaker.test(agent.voice, `Ciao, sono ${agent.name}. Il mio nucleo dati è online.`)
      return
    }
    const u = new SpeechSynthesisUtterance(`Ciao, sono ${agent.name}. Il mio nucleo dati è online.`)
    const v = voices.find((x) => x.name === agent.voice) ?? voices.find((x) => x.lang.startsWith('it'))
    if (v) u.voice = v
    speechSynthesis.cancel()
    speechSynthesis.speak(u)
  }

  const itVoices = voices.filter((v) => v.lang.startsWith('it'))
  const voiceHint = isServerVoice(agent.voice)
    ? agent.voice.startsWith('google:') ? 'Google Cloud: quota gratuita mensile, poi a consumo.' : 'Voce del Mac generata dal backend.'
    : !srv?.google_key ? 'Per una voce maschile neurale aggiungi la chiave Google (README, «Voce di AXEL»).' : ''
  const otherVoices = voices.filter((v) => !v.lang.startsWith('it'))

  return (
    <aside className={`panel builder ${builderOpen ? 'open' : ''}`} aria-hidden={!builderOpen}>
      <div className="panel-head">
        <h2>Costruisci agente</h2>
        <button className="icon-btn" onClick={() => set({ builderOpen: false })} aria-label="Chiudi">
          <Icon name="close" />
        </button>
      </div>

      <div className="agent-tabs">
        {agents.map((a) => (
          <button key={a.id} className={`chip ${a.id === currentId ? 'active' : ''}`} onClick={() => selectAgent(a.id)}>
            <i style={{ background: `linear-gradient(135deg, ${a.accent}, ${a.accent2})` }} />
            {a.name}
          </button>
        ))}
        <button className="chip add" onClick={create} title="Nuovo agente">
          <Icon name="plus" size={14} />
        </button>
      </div>

      <div className="form">
        <label>
          <span className="mono label">identità</span>
          <input value={agent.name} onChange={(e) => patch({ name: e.target.value })} />
        </label>

        <label>
          <span className="mono label">personalità · system prompt</span>
          <textarea rows={7} value={agent.persona} onChange={(e) => patch({ persona: e.target.value })} />
        </label>

        <label>
          <span className="mono label">parole da riconoscere · nomi, aziende, luoghi</span>
          <textarea
            rows={2}
            value={vocab}
            placeholder="es. Perfexia, Tenuta Leone, Unimatica"
            onChange={(e) => setVocab(e.target.value)}
            onBlur={async () => {
              const list = vocab.split(/[,\n]/).map((w) => w.trim()).filter(Boolean)
              try {
                setVocabulary(await api.saveVocabulary(list))
              } catch {
                /* backend giù */
              }
            }}
          />
          <small className="dim">Il riconoscimento vocale storpia i nomi propri: AXEL li corregge e li usa nelle ricerche.</small>
        </label>

        <label>
          <span className="mono label">motore</span>
          <select value={agent.model} onChange={(e) => patch({ model: e.target.value })}>
            {MODELS.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>
        </label>

        <div className="row">
          <label>
            <span className="mono label">max token</span>
            <input type="number" min={64} max={8192} step={64} value={agent.max_tokens} onChange={(e) => patch({ max_tokens: +e.target.value })} />
          </label>
          <label>
            <span className="mono label">temperatura {agent.temperature === null ? '· auto' : agent.temperature.toFixed(2)}</span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={agent.temperature ?? 0.7}
              onChange={(e) => patch({ temperature: +e.target.value })}
              onDoubleClick={() => patch({ temperature: null })}
              title="Doppio clic per tornare ad auto"
            />
          </label>
        </div>

        <fieldset>
          <span className="mono label">strumenti</span>
          <div className="tools">
            {tools.map((t) => {
              const on = agent.tools.includes(t.id)
              return (
                <button
                  type="button"
                  key={t.id}
                  className={`tool ${on ? 'on' : ''}`}
                  onClick={() => patch({ tools: on ? agent.tools.filter((x) => x !== t.id) : [...agent.tools, t.id] })}
                >
                  <b>{t.label}</b>
                  <small>{t.description}</small>
                </button>
              )
            })}
          </div>
        </fieldset>

        <label>
          <span className="mono label">voce</span>
          <div className="row tight">
            <select value={agent.voice} onChange={(e) => patch({ voice: e.target.value })}>
              <option value="">Automatica (italiano)</option>
              {srv?.google_key && (
                <optgroup label={srv.google.length ? 'Google Cloud · voci neurali' : 'Google Cloud (chiave non valida)'}>
                  {(srv.google.length ? srv.google : [{ name: 'it-IT-Chirp3-HD-Charon', gender: 'male', type: 'Chirp3-HD' }]).map((v) => (
                    <option key={v.name} value={`google:${v.name}`}>
                      {v.gender === 'male' ? '♂' : v.gender === 'female' ? '♀' : '·'} {v.name.replace('it-IT-', '')}
                    </option>
                  ))}
                </optgroup>
              )}
              {srv?.mac_available && srv.mac.length > 0 && (
                <optgroup label="Voci del Mac (gratis, offline)">
                  {srv.mac.map((v) => (
                    <option key={v} value={`mac:${v}`}>{v}</option>
                  ))}
                </optgroup>
              )}
              {itVoices.length > 0 && (
                <optgroup label="Italiano">
                  {itVoices.map((v) => (
                    <option key={v.name} value={v.name}>{v.name}</option>
                  ))}
                </optgroup>
              )}
              <optgroup label="Altre lingue">
                {otherVoices.map((v) => (
                  <option key={v.name} value={v.name}>{v.name} · {v.lang}</option>
                ))}
              </optgroup>
            </select>
            <button type="button" className="icon-btn" onClick={testVoice} title="Prova voce">
              <Icon name="play" />
            </button>
          </div>
          {voiceHint && <em className="dim small">{voiceHint}</em>}
          {srv?.google_error && <em className="small err-text">{srv.google_error}</em>}
        </label>

        <fieldset>
          <span className="mono label">aspetto</span>
          <span className="mono label">colori</span>
          <div className="presets">
            {PRESETS.map((p) => (
              <button
                type="button"
                key={p.name}
                className={`preset ${agent.accent === p.a && agent.accent2 === p.b ? 'active' : ''}`}
                onClick={() => patch({ accent: p.a, accent2: p.b })}
              >
                <i style={{ background: `linear-gradient(135deg, ${p.a}, ${p.b})` }} />
                {p.name}
              </button>
            ))}
          </div>
          <div className="row tight">
            <input type="color" value={agent.accent} onChange={(e) => patch({ accent: e.target.value })} aria-label="Colore primario" />
            <input type="color" value={agent.accent2} onChange={(e) => patch({ accent2: e.target.value })} aria-label="Colore secondario" />
          </div>
        </fieldset>
      </div>

      <div className="panel-foot">
        <button className="icon-btn danger" onClick={remove} disabled={agents.length <= 1} title="Elimina agente">
          <Icon name="trash" />
        </button>
        <span className="mono dim">
          {saving === 'saving' ? 'salvataggio…' : saving === 'saved' ? 'salvato ✓' : saving === 'error' ? 'errore di salvataggio' : ''}
        </span>
        <button className="send" onClick={save}>
          Salva agente
        </button>
      </div>
    </aside>
  )
}
