/**
 * Vocabolario personale: corregge nelle trascrizioni vocali i nomi propri che il riconoscimento
 * storpia ("perfezia", "per fexia" → "Perfexia"). Confronto fuzzy su finestre di 1-3 parole.
 */

let words: string[] = []

export function setVocabulary(list: string[]) {
  words = list.filter((w) => w.trim().length >= 3)
}

export function getVocabulary() {
  return words
}

const norm = (s: string) =>
  s
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]/g, '')

function lev(a: string, b: string): number {
  const dp = Array.from({ length: a.length + 1 }, (_, i) => [i, ...Array(b.length).fill(0)])
  for (let j = 1; j <= b.length; j++) dp[0][j] = j
  for (let i = 1; i <= a.length; i++)
    for (let j = 1; j <= b.length; j++)
      dp[i][j] = Math.min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1))
  return dp[a.length][b.length]
}

/** Somiglianza 0..1 con un piccolo aiuto per le confusioni tipiche del parlato (x/z/s, ph/f, k/c). */
function similarity(a: string, b: string) {
  const phon = (s: string) => s.replace(/ph/g, 'f').replace(/[xz]/g, 's').replace(/k/g, 'c').replace(/y/g, 'i').replace(/(.)\1/g, '$1')
  const pa = phon(a)
  const pb = phon(b)
  return 1 - lev(pa, pb) / Math.max(pa.length, pb.length, 1)
}

export function correct(text: string): string {
  if (!words.length || !text) return text
  const tokens = text.split(/(\s+)/) // mantiene gli spazi
  const wordIdx = tokens.map((t, i) => (t.trim() ? i : -1)).filter((i) => i >= 0)
  const out = [...tokens]
  const used = new Set<number>()
  for (const target of words) {
    const tn = norm(target)
    if (tn.length < 4) continue
    let best: { from: number; to: number; sim: number } | null = null
    for (let w = 0; w < wordIdx.length; w++) {
      for (let span = 1; span <= 3 && w + span <= wordIdx.length; span++) {
        const idxs = wordIdx.slice(w, w + span)
        if (idxs.some((i) => used.has(i))) continue
        const cand = norm(idxs.map((i) => tokens[i]).join(''))
        if (!cand || Math.abs(cand.length - tn.length) > 3) continue
        if (cand === tn) {
          best = { from: w, to: w + span, sim: 1 }
          break
        }
        const sim = similarity(cand, tn)
        if (sim >= 0.72 && cand[0] === tn[0] && (!best || sim > best.sim)) best = { from: w, to: w + span, sim }
      }
    }
    if (best) {
      const idxs = wordIdx.slice(best.from, best.to)
      const trail = tokens[idxs[idxs.length - 1]].match(/[.,!?;:]+$/)?.[0] ?? ''
      out[idxs[0]] = target + trail
      for (let k = 1; k < idxs.length; k++) {
        out[idxs[k]] = ''
        if (idxs[k] - 1 >= 0) out[idxs[k] - 1] = '' // spazio prima
      }
      idxs.forEach((i) => used.add(i))
    }
  }
  return out.join('').replace(/\s{2,}/g, ' ').trim()
}
