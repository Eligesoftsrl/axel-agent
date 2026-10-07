import { useEffect, useMemo, useRef, useState } from 'react'
import { live, useStore } from '../store'

/**
 * Testo laterale stile "lyrics" delle storie Instagram:
 * - le parole compaiono con una dissolvenza mentre arrivano
 * - la riga in pronuncia è al centro e le parole si illuminano mentre AXEL le dice
 * - le righe passate scorrono in alto e sfumano; a fine risposta tutto svanisce
 */

interface Word {
  w: string
  start: number
  i: number
}

function tokenize(text: string): Word[] {
  const out: Word[] = []
  const re = /\S+/g
  let m
  while ((m = re.exec(text))) out.push({ w: m[0].replace(/[*#_`]/g, ''), start: m.index, i: out.length })
  return out.filter((x) => x.w)
}

function wrap(words: Word[], max: number): Word[][] {
  const lines: Word[][] = []
  let cur: Word[] = []
  let len = 0
  for (const w of words) {
    const prevEndsSentence = cur.length > 0 && /[.!?:;]$/.test(cur[cur.length - 1].w)
    if (cur.length && (len + 1 + w.w.length > max || prevEndsSentence)) {
      lines.push(cur)
      cur = []
      len = 0
    }
    cur.push(w)
    len += (cur.length > 1 ? 1 : 0) + w.w.length
  }
  if (cur.length) lines.push(cur)
  return lines
}

/** Legge live.spoken a ogni frame ma aggiorna React solo quando cambia parola. */
function useSpoken(words: Word[]) {
  const [idx, setIdx] = useState(-1)
  const last = useRef(-1)
  useEffect(() => {
    let raf = 0
    const tick = () => {
      const s = live.spoken
      let n = -1
      for (let k = 0; k < words.length && words[k].start < s; k++) n = k
      if (n !== last.current) {
        last.current = n
        setIdx(n)
      }
      raf = requestAnimationFrame(tick)
    }
    tick()
    return () => cancelAnimationFrame(raf)
  }, [words])
  return idx
}

export function Lyrics({ interim }: { interim: string }) {
  const { state, partial } = useStore()
  const [hidden, setHidden] = useState(true)
  const mobile = typeof window !== 'undefined' && window.innerWidth < 760

  const source = interim || partial
  const words = useMemo(() => tokenize(source), [source])
  const lines = useMemo(() => wrap(words, mobile ? 30 : 22), [words, mobile])
  const spokenIdx = useSpoken(words)

  // visibile mentre c'è attività, svanisce qualche secondo dopo
  useEffect(() => {
    if (state !== 'idle' || interim) {
      setHidden(false)
      return
    }
    const t = setTimeout(() => setHidden(true), 4500)
    return () => clearTimeout(t)
  }, [state, interim, partial])

  const allLit = !!interim || state === 'idle'
  const litUpTo = allLit ? words.length - 1 : spokenIdx
  let cur = lines.findIndex((l) => l[l.length - 1].i > litUpTo)
  if (cur < 0) cur = lines.length - 1
  if (state === 'thinking' && spokenIdx < 0) cur = lines.length - 1 // mentre arriva: segue l'ultima riga

  const LH = mobile ? 34 : 46
  const H = mobile ? 136 : 320
  const offset = H / 2 - (cur * LH + LH / 2)

  return (
    <section className={`lyrics ${hidden ? 'gone' : ''}`} aria-live="polite" style={{ height: H }}>
      {state === 'thinking' && !source && (
        <div className="lyrics-thinking" style={{ top: H / 2 - 6 }}>
          <span />
          <span />
          <span />
        </div>
      )}
      <div className="lyrics-track" style={{ transform: `translateY(${offset}px)` }}>
        {lines.map((line, li) => {
          const d = li - cur
          const op = d === 0 ? 1 : d === -1 ? 0.42 : d === 1 ? 0.5 : Math.abs(d) === 2 ? 0.16 : 0
          return (
            <div key={li} className={`lyric-line ${d === 0 ? 'cur' : ''} ${interim ? 'interim' : ''}`} style={{ height: LH, opacity: op }}>
              {line.map((w) => (
                <span key={w.i} className={`w ${w.i <= litUpTo ? 'lit' : ''}`}>
                  {w.w}
                </span>
              ))}
            </div>
          )
        })}
      </div>
    </section>
  )
}
