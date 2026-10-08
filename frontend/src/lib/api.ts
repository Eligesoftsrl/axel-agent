import type { AgentConfig, Attachment, ChatMessage, OutputFile, ToolInfo } from '../store'

const BASE = import.meta.env?.VITE_API_URL ?? ''

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(BASE + path, {
    headers: { 'content-type': 'application/json' },
    ...init,
  })
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json()
}

export const api = {
  health: () => json<{ ok: boolean; demo: boolean }>('/api/health'),
  agents: () => json<AgentConfig[]>('/api/agents'),
  tools: () => json<ToolInfo[]>('/api/tools'),
  save: (a: AgentConfig) => json<AgentConfig>(`/api/agents/${a.id}`, { method: 'PUT', body: JSON.stringify(a) }),
  create: (a: Partial<AgentConfig>) => json<AgentConfig>('/api/agents', { method: 'POST', body: JSON.stringify(a) }),
  remove: (id: string) => json(`/api/agents/${id}`, { method: 'DELETE' }),

  integrations: (agentId: string) => json<Integrations>(`/api/integrations?agent_id=${agentId}`),
  googleDisconnect: () => json('/api/google/disconnect', { method: 'POST' }),
  spotifyDisconnect: () => json('/api/spotify/disconnect', { method: 'POST' }),
  background: (id: string) => json<{ id: string; title: string; status: string; result: string | null; steps: number }>(`/api/background/${id}`),
  backgroundList: () => json<{ id: string; title: string; status: string; steps: number; created_at: string; preview: string | null }[]>('/api/background'),
  backgroundCancel: (id: string) => json(`/api/background/${id}`, { method: 'DELETE' }),
  backup: () => json<BackupStatus>('/api/backup'),
  saveBackup: (s: Partial<BackupStatus>) => json<BackupStatus>('/api/backup', { method: 'PUT', body: JSON.stringify(s) }),
  backupRun: () => json<BackupStatus>('/api/backup/run', { method: 'POST' }),
  backupRestore: (name: string) => json<BackupStatus & { restored: string; safety: string }>('/api/backup/restore', { method: 'POST', body: JSON.stringify({ name }) }),
  news: () => json<NewsSettings>('/api/news'),
  saveNews: (s: Partial<NewsSettings>) => json<NewsSettings>('/api/news', { method: 'PUT', body: JSON.stringify(s) }),
  addFeed: (url: string) => json<NewsSettings & { added: { name: string; url: string } }>('/api/news/feed', { method: 'POST', body: JSON.stringify({ url }) }),
  deleteFeed: (url: string) => json<NewsSettings>(`/api/news/feed?url=${encodeURIComponent(url)}`, { method: 'DELETE' }),
  newsTest: () => json<{ text: string }>('/api/news/test', { method: 'POST' }),
  shipments: () => json<Shipment[]>('/api/shipments'),
  shipmentsCheck: () => json<Shipment[]>('/api/shipments/check', { method: 'POST' }),
  shipmentArchive: (id: number) => json(`/api/shipments/${id}`, { method: 'DELETE' }),
  maps: () => json<MapsSettings>('/api/maps'),
  saveMaps: (s: Partial<MapsSettings>) => json<MapsSettings>('/api/maps', { method: 'PUT', body: JSON.stringify(s) }),
  mapsTest: (destination: string) => json<{ text: string }>(`/api/maps/test?destination=${encodeURIComponent(destination)}`),
  telegramVoice: (on: boolean) => json<{ on: boolean }>('/api/telegram/voice', { method: 'PUT', body: JSON.stringify({ on }) }),
  memoryLearn: (agentId: string) => json<{ saved: string[]; updated: string[]; questions: string[] }>(`/api/memory/learn?agent_id=${agentId}`, { method: 'POST' }),
  memoryLearned: () => json<{ date?: string; saved?: string[]; updated?: string[]; questions?: string[] }>('/api/memory/learned'),
  ttsVoices: () => json<{ google: { name: string; gender: string; type: string }[]; google_key: boolean; google_error: string | null; mac: string[]; mac_available: boolean }>('/api/tts/voices'),
  upload: async (file: File) => {
    const r = await fetch(`${BASE}/api/upload?filename=${encodeURIComponent(file.name)}`, { method: 'POST', body: file })
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? `errore ${r.status}`)
    return (await r.json()) as Attachment
  },
  mcp: () => json<McpInfo>('/api/mcp'),
  mcpSave: (name: string, cfg: McpConfigInput) => json<McpInfo>(`/api/mcp/servers/${encodeURIComponent(name)}`, { method: 'PUT', body: JSON.stringify(cfg) }),
  mcpDelete: (name: string) => json<McpInfo>(`/api/mcp/servers/${encodeURIComponent(name)}`, { method: 'DELETE' }),
  mcpReload: () => json<McpInfo>('/api/mcp/reload', { method: 'POST' }),
  speed: () => json<SpeedSettings>('/api/speed'),
  saveSpeed: (s: Partial<SpeedSettings>) => json<SpeedSettings>('/api/speed', { method: 'PUT', body: JSON.stringify(s) }),
  usage: (days = 7) => json<UsageRow[]>(`/api/usage?days=${days}`),
  sttStatus: () => json<SttStatus>('/api/stt/status'),
  sttQuality: (quality: 'fast' | 'accurate') => json<SttStatus>('/api/stt/quality', { method: 'PUT', body: JSON.stringify({ quality }) }),
  sttWarmup: () => json<SttStatus>('/api/stt/warmup', { method: 'POST' }),
  stt: async (wav: Blob) => {
    const r = await fetch(BASE + '/api/stt', { method: 'POST', headers: { 'content-type': 'audio/wav' }, body: wav })
    if (!r.ok) throw new Error(r.status === 503 ? (await r.json()).detail : `Whisper: errore ${r.status}`)
    return (await r.json()) as { text: string; raw: string; confidence: number; discarded: string | null; duration: number; ms: number }
  },
  spotifyNow: () => json<{ text: string }>('/api/spotify/now'),
  spotifyDiagnose: () => json<{ checks: { name: string; ok: boolean; detail: string }[] }>('/api/spotify/diagnose'),
  spotifyState: () => json<{ data: SpotifyData | null }>('/api/spotify/state'),
  spotifyControl: (action: string, value?: number) =>
    json<{ message: string; data: SpotifyData | null }>('/api/spotify/control', { method: 'POST', body: JSON.stringify({ action, value }) }),
  telegramTest: () => json<{ ok: boolean }>('/api/telegram/test', { method: 'POST' }),
  telegramUnlink: () => json('/api/telegram/unlink', { method: 'POST' }),
  saveBriefing: (b: Briefing) => json<Briefing>('/api/briefing', { method: 'PUT', body: JSON.stringify(b) }),
  runBriefing: () => json<{ ok: boolean; channel: string }>('/api/briefing/run', { method: 'POST' }),
  reminders: () => json<Reminder[]>('/api/reminders'),
  vocabulary: () => json<string[]>('/api/vocabulary'),
  saveVocabulary: (w: string[]) => json<string[]>('/api/vocabulary', { method: 'PUT', body: JSON.stringify(w) }),
  huePair: () => json<{ ok: boolean; need_button?: boolean; ip?: string }>('/api/hue/pair', { method: 'POST' }),
  hueUnlink: () => json('/api/hue/unlink', { method: 'POST' }),
  saveProactive: (p: Partial<Proactive>) => json<Proactive>('/api/proactive', { method: 'PUT', body: JSON.stringify(p) }),
  tasks: () => json<Task[]>('/api/tasks'),
  mailTest: () => json('/api/mail/test', { method: 'POST' }),
  deleteTask: (id: number) => json(`/api/tasks/${id}`, { method: 'DELETE' }),
  deleteReminder: (id: number) => json(`/api/reminders/${id}`, { method: 'DELETE' }),
  memories: (agentId: string) => json<Memory[]>(`/api/memories?agent_id=${agentId}`),
  deleteMemory: (agentId: string, id: number) => json(`/api/memories/${id}?agent_id=${agentId}`, { method: 'DELETE' }),
  importClaude: async (file: File) => {
    const r = await fetch(`${BASE}/api/import/claude?filename=${encodeURIComponent(file.name)}`, { method: 'POST', body: file })
    if (!r.ok) throw new Error((await r.json()).detail ?? r.statusText)
    return r.json() as Promise<{ conversations: number; messages: number; skipped: number }>
  },
  approve: (id: string) => json<{ ok: boolean; result: string }>(`/api/actions/${id}/approve`, { method: 'POST' }),
  reject: (id: string) => json<{ ok: boolean; result: string }>(`/api/actions/${id}/reject`, { method: 'POST' }),
  notifications: (after: number) =>
    json<{ last: number; items: { id: number; kind: string; text: string }[] }>(`/api/notifications?after=${after}`),
}

export interface Briefing {
  enabled: boolean
  time: string
  city: string
  last_date?: string | null
}
export interface Integrations {
  google: { configured: boolean; connected: boolean; email: string | null }
  telegram: { configured: boolean; linked: boolean; bot: string | null; pair_code: string | null; voice_reply: boolean }
  spotify: { configured: boolean; connected: boolean; user: string | null }
  proactive: Proactive
  mac: boolean
  hue: { linked: boolean; ip: string | null }
  briefing: Briefing
  history: Record<string, { conversations: number; messages: number }>
  memories: number
}
export interface Proactive {
  event_alerts: boolean
  event_lead_min: number
  email_alerts: boolean
  mail_bubbles: boolean
  email_interval_min: number
  evening_recap: boolean
  recap_time: string
  shipments: boolean
  memory_learning: boolean
  learning_time: string
  vip_senders: string[]
  ignore_senders: string[]
  email_rules: string
}
export interface BackupStatus {
  enabled: boolean
  folder: string
  folder_effective: string
  time: string
  keep: number
  last: { name: string; size: number; at: string; folder: string } | null
  error: { at: string; error: string } | null
  backups: { name: string; size: number; created: string }[]
}
export interface NewsSettings {
  feeds: { name: string; url: string }[]
  custom: { name: string; url: string }[]
  interests: string
  in_briefing: boolean
  count: number
  presets: { name: string; url: string }[]
}
export interface Shipment {
  id: number
  item: string | null
  merchant: string | null
  carrier: string | null
  tracking: string | null
  status: string
  label: string
  eta: string | null
  link: string | null
  updated_at: string
}
export interface MapsSettings {
  home: string
  work: string
  mode: string
  leave_alerts: boolean
  buffer_min: number
  provider: 'google' | 'openstreetmap'
  traffic: boolean
}
export interface Task {
  id: number
  title: string
  prompt: string
  due_at: string
  recurrence: string
}
export interface Reminder {
  id: number
  text: string
  due_at: string
  recurrence: string
}
export interface Memory {
  id: number
  category: string
  content: string
  created_at: string
}
export interface PendingAction {
  id: string
  name: string
  summary: string
}

export type StreamEvent =
  | { type: 'text'; delta: string }
  | { type: 'tool_use'; name: string }
  | { type: 'tool_result'; name: string; output: string }
  | { type: 'done'; usage: Record<string, number> | null; fast?: boolean }
  | { type: 'meta'; model: string }
  | { type: 'file'; file: OutputFile }
  | { type: 'error'; message: string }
  | { type: 'confirm'; action: PendingAction }
  | { type: 'widget'; widget: 'weather'; data: WeatherData }
  | { type: 'widget'; widget: 'spotify'; data: SpotifyData }
  | { type: 'widget'; widget: 'gallery'; data: import('../ui/Gallery').GalleryData }

/** POST /api/chat e legge lo stream SSE evento per evento. */
export async function* streamChat(
  agentId: string,
  messages: ChatMessage[],
  signal?: AbortSignal,
  conversationId?: string,
): AsyncGenerator<StreamEvent> {
  const r = await fetch(BASE + '/api/chat', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      agent_id: agentId,
      messages: messages.map(({ role, content, attachments }) => ({ role, content, attachments: attachments?.map((a) => a.id) ?? [] })),
      conversation_id: conversationId,
    }),
    signal,
  })
  if (!r.ok || !r.body) throw new Error(`HTTP ${r.status}`)

  const reader = r.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let idx
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      const line = chunk.split('\n').find((l) => l.startsWith('data: '))
      if (line) yield JSON.parse(line.slice(6)) as StreamEvent
    }
  }
}

export interface McpServer {
  name: string
  status: 'idle' | 'connecting' | 'connected' | 'error' | 'disabled'
  error: string
  approval: 'auto-read' | 'ask' | 'auto'
  enabled: boolean
  config: { command?: string; args?: string[]; url?: string; transport?: string; description?: string; env_keys: string[]; header_keys: string[] }
  tools: { name: string; description: string; read_only: boolean }[]
}
export interface McpInfo {
  available: boolean
  servers: McpServer[]
  config_path: string
}
export interface McpConfigInput {
  command?: string
  args?: string[]
  env?: Record<string, string>
  url?: string
  headers?: Record<string, string>
  transport?: string
  approval: string
  enabled: boolean
  description?: string
  keep_secrets?: boolean
}

export interface SpeedSettings {
  fastlane: boolean
  router: boolean
  fast_model: string
}
export interface UsageRow {
  day: string
  channel: string
  model: string
  calls: number
  input: number
  output: number
  cache_read: number
  cache_write: number
  avg_ms: number | null
}
export interface SttStatus {
  available: boolean
  engine: string | null
  model: string
  loaded: boolean
  error: string | null
  quality: 'fast' | 'accurate'
  last_ms: number | null
  avg_ms: number | null
}

export interface SpotifyData {
  track: string
  artists: string
  album: string
  art: string
  url: string
  is_playing: boolean
  progress_ms: number
  duration_ms: number
  device: string
  volume: number | null
  shuffle: boolean
}

export interface WeatherData {
  city: string
  region: string
  current: { temp: number; feels: number; humidity: number; wind: number; code: number; desc: string; kind: string; is_day: boolean }
  today: { sunrise: string; sunset: string }
  daily: { date: string; desc: string; kind: string; tmin: number; tmax: number; rain: number }[]
  hourly: { time: string; temp: number; kind: string; rain: number }[]
}
