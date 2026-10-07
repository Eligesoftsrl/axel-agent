/**
 * Suoni dell'interfaccia (file in public/sounds):
 * - wakeup.mp3   all'apertura della pagina
 * - notifica.mp3 quando arrivano notifiche, bolle email o compare un widget
 * Rispettano il pulsante "silenzia". Se il browser blocca l'autoplay, il suono di avvio
 * parte al primo clic o tasto premuto.
 */

const cache: Record<string, HTMLAudioElement> = {}
let muted = false
let lastNotify = 0

function audio(name: string, volume: number) {
  if (!cache[name]) {
    const a = new Audio(`/sounds/${name}.mp3`)
    a.preload = 'auto'
    cache[name] = a
  }
  cache[name].volume = volume
  return cache[name]
}

export function setSoundsMuted(m: boolean) {
  muted = m
}

export function preloadSounds() {
  audio('notifica', 0.55)
  audio('wakeup', 0.7)
}

/** Suono di notifica (non più di uno ogni 1,5 s, anche se arrivano più eventi insieme). */
export function playNotify() {
  if (muted) return
  const now = Date.now()
  if (now - lastNotify < 1500) return
  lastNotify = now
  const a = audio('notifica', 0.55)
  a.currentTime = 0
  a.play().catch(() => {})
}

/** Suono di avvio: prova subito, altrimenti alla prima interazione. */
export function playWakeup() {
  if (muted) return
  const a = audio('wakeup', 0.7)
  a.currentTime = 0
  a.play().catch(() => {
    const once = () => {
      if (!muted) {
        a.currentTime = 0
        a.play().catch(() => {})
      }
      window.removeEventListener('pointerdown', once)
      window.removeEventListener('keydown', once)
    }
    window.addEventListener('pointerdown', once, { once: true })
    window.addEventListener('keydown', once, { once: true })
  })
}
