import { create } from 'zustand'
import type { PendingAction, SpotifyData, WeatherData } from './lib/api'

export type AgentState = 'idle' | 'listening' | 'thinking' | 'speaking'

export interface AgentConfig {
  id: string
  name: string
  persona: string
  model: string
  max_tokens: number
  temperature: number | null
  tools: string[]
  voice: string
  accent: string
  accent2: string
}

export interface ToolInfo {
  id: string
  label: string
  description: string
}

export interface Attachment {
  id: string
  name: string
  kind: 'pdf' | 'image' | 'text' | 'data'
  size: number
}
export interface OutputFile {
  id: string
  name: string
  mime: string
  url: string
}
export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  tools?: string[]
  attachments?: Attachment[]
  files?: OutputFile[]
}

/**
 * Valori che cambiano a ogni frame (ampiezza voce, flusso dati).
 * Volutamente FUORI da React: la scena 3D li legge in useFrame senza re-render.
 */
export const live = {
  level: 0, // 0..1 ampiezza voce dell'agente (bocca, occhi, cuore)
  levelTarget: 0,
  mic: 0, // 0..1 ampiezza microfono utente
  pulse: 0, // impulso breve (arrivo token, tool call)
  spoken: 0,
  mailFlash: 0, // 0..1 bagliore del cuore all'arrivo di un'email
  heartScreen: { x: 0, y: 0 }, // posizione del cuore sullo schermo (px) // caratteri della risposta già pronunciati (per il testo laterale stile karaoke)
}

interface Store {
  state: AgentState
  agents: AgentConfig[]
  tools: ToolInfo[]
  currentId: string
  messages: ChatMessage[]
  partial: string // testo in arrivo
  activity: string // ultima attività (es. "tool: calculator")
  demo: boolean
  builderOpen: boolean
  historyOpen: boolean
  integrationsOpen: boolean
  pending: PendingAction[]
  toasts: { id: number; text: string; kind: string }[]
  conversationId: string
  handsFree: boolean
  handsFreeMode: 'off' | 'wake' | 'command'
  voiceEngine: 'whisper' | 'browser' | null
  /** modello che ha risposto all'ultimo messaggio (fastlane = corsia veloce) */
  lastModel: string
  widget: { kind: string; data: WeatherData; at: number } | null
  /** scheda Spotify (indipendente dal meteo: possono stare aperte insieme) */
  music: { data: SpotifyData; at: number } | null
  mailBubbles: import('./ui/MailBubbles').MailItem[]
  /** allegati pronti per il prossimo messaggio */
  drafts: (Attachment & { uploading?: boolean })[]
  /** file prodotti dall'ultima analisi (grafici…), mostrati come proiezione olografica */
  outputs: { files: OutputFile[]; at: number } | null
  /** risultato di un compito in background aperto dall'utente */
  taskView: { title: string; text: string; status: string } | null
  set: (p: Partial<Store>) => void
  current: () => AgentConfig | undefined
}

export const useStore = create<Store>((set, get) => ({
  state: 'idle',
  agents: [],
  tools: [],
  currentId: '',
  messages: [],
  partial: '',
  activity: '',
  demo: false,
  builderOpen: false,
  historyOpen: false,
  integrationsOpen: false,
  pending: [],
  toasts: [],
  conversationId: `ui-${Date.now().toString(36)}`,
  handsFree: false,
  handsFreeMode: 'off',
  voiceEngine: null,
  lastModel: '',
  widget: null,
  music: null,
  mailBubbles: [],
  drafts: [],
  outputs: null,
  taskView: null,
  set: (p) => set(p),
  current: () => get().agents.find((a) => a.id === get().currentId),
}))

export const DEFAULT_ACCENT = '#3ff0f7'
export const DEFAULT_ACCENT2 = '#1e7fe0'
