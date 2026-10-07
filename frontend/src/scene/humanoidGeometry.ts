import * as THREE from 'three'

/**
 * Busto umanoide procedurale definito da una SDF (signed distance field).
 * La superficie viene campionata ad anelli orizzontali di punti, come
 * curve di livello: è ciò che dà l'aspetto "scansione dati" all'avatar.
 *
 * Vuoi un volto diverso? Modifica le primitive qui sotto, oppure
 * sostituisci tutto caricando un .glb e campionandone i vertici
 * (MeshSurfaceSampler di three/examples) con lo stesso shader.
 */

type V = [number, number, number]

const smin = (a: number, b: number, k: number) => {
  const h = Math.max(k - Math.abs(a - b), 0) / k
  return Math.min(a, b) - h * h * k * 0.25
}
const smax = (a: number, b: number, k: number) => -smin(-a, -b, k)

function ell(x: number, y: number, z: number, c: V, r: V) {
  const px = (x - c[0]) / r[0], py = (y - c[1]) / r[1], pz = (z - c[2]) / r[2]
  const k0 = Math.hypot(px, py, pz)
  const k1 = Math.hypot(px / r[0], py / r[1], pz / r[2])
  return k1 === 0 ? -Math.min(...r) : (k0 * (k0 - 1)) / k1
}

function cap(x: number, y: number, z: number, a: V, b: V, r: number) {
  const pax = x - a[0], pay = y - a[1], paz = z - a[2]
  const bax = b[0] - a[0], bay = b[1] - a[1], baz = b[2] - a[2]
  const h = Math.min(1, Math.max(0, (pax * bax + pay * bay + paz * baz) / (bax * bax + bay * bay + baz * baz)))
  return Math.hypot(pax - bax * h, pay - bay * h, paz - baz * h) - r
}

export type HeadStyle = 'visor' | 'classic'
export let HEAD_STYLE: HeadStyle = 'visor'
export const setHeadStyle = (h: HeadStyle) => (HEAD_STYLE = h)

/** Testa liscia, volto a V, recesso orizzontale per la fascia luminosa. */
function headVisor(x: number, y: number, z: number, ax: number) {
  let d = ell(x, y, z, [0, 1.62, -0.07], [0.275, 0.33, 0.38]) // calotta liscia, fronte bassa
  // volto a V: linee dritte dagli zigomi alla punta del mento
  const tp = 0.15 + 0.85 * Math.min(1, Math.max(0, (y - 1.11) / 0.44))
  d = smin(d, ell(x / tp, y, z, [0, 1.47, 0.04], [0.3, 0.37, 0.29]), 0.07)
  d = smin(d, ell(ax, y, z, [0.185, 1.49, 0.1], [0.07, 0.055, 0.14]), 0.06) // zigomi
  d = smin(d, ell(x, y, z, [0, 1.12, 0.14], [0.034, 0.04, 0.05]), 0.04) // punta del mento
  d = smin(d, ell(x, y, z, [0, 1.622, 0.22], [0.24, 0.03, 0.07]), 0.04) // tettoia sopra la fascia
  d = smax(d, -ell(ax, y, z, [0.15, 1.36, 0.23], [0.05, 0.1, 0.05]), 0.05) // guance scavate
  d = smin(d, cap(x, y, z, [0, 1.53, 0.305], [0, 1.15, 0.165], 0.009), 0.018) // linea centrale
  d = smax(d, -ell(x, y, z, [0, 1.567, 0.34], [0.25, 0.022, 0.09]), 0.01) // recesso fascia
  return d
}

function headClassic(x: number, y: number, z: number, ax: number) {
  let d = ell(x, y, z, [0, 1.66, -0.04], [0.33, 0.42, 0.42])
  d = smin(d, ell(x, y, z, [0, 1.44, 0.06], [0.25, 0.31, 0.31]), 0.15)
  d = smin(d, ell(x, y, z, [0, 1.27, 0.11], [0.17, 0.13, 0.19]), 0.12) // mandibola
  d = smin(d, ell(x, y, z, [0, 1.17, 0.2], [0.09, 0.07, 0.08]), 0.06) // mento
  d = smin(d, ell(ax, y, z, [0.165, 1.49, 0.19], [0.1, 0.07, 0.1]), 0.06) // zigomi
  d = smin(d, ell(x, y, z, [0, 1.645, 0.29], [0.25, 0.05, 0.09]), 0.05) // arcata
  d = smin(d, cap(x, y, z, [0, 1.6, 0.35], [0, 1.46, 0.43], 0.034), 0.05) // naso
  d = smin(d, ell(x, y, z, [0, 1.45, 0.39], [0.058, 0.032, 0.05]), 0.03) // narici
  d = smax(d, -ell(ax, y, z, [0.115, 1.575, 0.38], [0.068, 0.04, 0.06]), 0.04) // orbite
  d = smin(d, ell(x, y, z, [0, 1.336, 0.352], [0.09, 0.022, 0.04]), 0.025) // labbro sup
  d = smin(d, ell(x, y, z, [0, 1.3, 0.346], [0.08, 0.024, 0.04]), 0.025) // labbro inf
  d = smax(d, -ell(x, y, z, [0, 1.318, 0.39], [0.085, 0.006, 0.05]), 0.01) // rima
  d = smin(d, ell(ax, y, z, [0.33, 1.52, -0.02], [0.035, 0.09, 0.065]), 0.03) // orecchie
  return d
}

export function humanoidSDF(x: number, y: number, z: number): number {
  const ax = Math.abs(x) // simmetria
  // --- testa
  let d = HEAD_STYLE === 'visor' ? headVisor(x, y, z, ax) : headClassic(x, y, z, ax)
  // --- collo e busto
  d = smin(d, cap(x, y, z, [0, 0.9, -0.03], [0, 1.32, -0.05], HEAD_STYLE === 'visor' ? 0.155 : 0.13), 0.1)
  d = smin(d, cap(x, y, z, [-0.5, 0.85, -0.05], [0.5, 0.85, -0.05], 0.13), 0.2) // trapezio
  d = smin(d, ell(ax, y, z, [0.68, 0.72, -0.02], [0.22, 0.2, 0.2]), 0.15) // spalle
  d = smin(d, ell(x, y, z, [0, 0.45, 0], [0.72, 0.5, 0.3]), 0.2) // torace
  d = smin(d, ell(ax, y, z, [0.22, 0.6, 0.15], [0.22, 0.15, 0.13]), 0.1) // pettorali
  return d
}

export function surfaceRadius(y: number, ang: number, hint = 1.3): number {
  const cx = Math.cos(ang), cz = Math.sin(ang)
  const R = 1.3
  // parte vicino al raggio precedente (hint), assicurandosi di essere fuori
  let r = Math.min(R, hint + 0.06)
  while (r < R && humanoidSDF(cx * r, y, cz * r) < 0) r += 0.06
  r = Math.min(r, R)
  // marcia dall'esterno verso l'asse fino al primo ingresso nella forma
  let prev = r
  while (r > 0) {
    if (humanoidSDF(cx * r, y, cz * r) < 0) break
    prev = r
    r -= 0.012
  }
  if (r <= 0) return -1
  let lo = r, hi = prev
  for (let i = 0; i < 18; i++) {
    const m = (lo + hi) / 2
    if (humanoidSDF(cx * m, y, cz * m) < 0) lo = m
    else hi = m
  }
  return (lo + hi) / 2
}

export function buildHumanoidGeometry(opts?: { dy?: number; ds?: number }) {
  const dy = opts?.dy ?? 0.016
  const ds = opts?.ds ?? 0.0125
  const pos: number[] = []
  const nor: number[] = []
  const rnd: number[] = []
  const e = 0.003
  const SAMPLES = 256

  for (let y = 0.02; y < 2.12; y += dy) {
    if (humanoidSDF(0, y, 0) > 0 && humanoidSDF(0, y, 0.05) > 0) continue
    // profilo dell'anello
    const radii: number[] = []
    let hint = 1.3
    for (let i = 0; i < SAMPLES; i++) {
      const r = surfaceRadius(y, (i / SAMPLES) * Math.PI * 2, hint)
      radii.push(r)
      hint = r > 0 ? r : 1.3
    }
    if (radii.some((r) => r < 0)) continue
    // perimetro → punti equispaziati
    const pts: [number, number][] = radii.map((r, i) => {
      const a = (i / SAMPLES) * Math.PI * 2
      return [Math.cos(a) * r, Math.sin(a) * r]
    })
    const seg: number[] = [0]
    for (let i = 1; i <= SAMPLES; i++) {
      const [x0, z0] = pts[i - 1], [x1, z1] = pts[i % SAMPLES]
      seg.push(seg[i - 1] + Math.hypot(x1 - x0, z1 - z0))
    }
    const per = seg[SAMPLES]
    const n = Math.max(6, Math.floor(per / ds))
    const offset = Math.random()
    let j = 0
    for (let k = 0; k < n; k++) {
      const s = ((k + offset) / n) * per
      while (seg[j + 1] < s) j++
      const t = (s - seg[j]) / (seg[j + 1] - seg[j] || 1)
      const [x0, z0] = pts[j], [x1, z1] = pts[(j + 1) % SAMPLES]
      const x = x0 + (x1 - x0) * t, z = z0 + (z1 - z0) * t
      pos.push(x, y, z)
      const nx = humanoidSDF(x + e, y, z) - humanoidSDF(x - e, y, z)
      const ny = humanoidSDF(x, y + e, z) - humanoidSDF(x, y - e, z)
      const nz = humanoidSDF(x, y, z + e) - humanoidSDF(x, y, z - e)
      const l = Math.hypot(nx, ny, nz) || 1
      nor.push(nx / l, ny / l, nz / l)
      rnd.push(Math.random())
    }
  }

  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  g.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3))
  g.setAttribute('aRand', new THREE.Float32BufferAttribute(rnd, 1))
  g.computeBoundingSphere()
  return g
}

/**
 * Superficie solida: griglia (anelli × angoli) costruita dalla stessa SDF.
 * Ogni anello usa gli stessi angoli, quindi i vertici si collegano a quad.
 */
export function buildHumanoidMesh(opts?: { dy?: number; cols?: number }) {
  const dy = opts?.dy ?? 0.009
  const COLS = opts?.cols ?? 288
  const rings: number[][] = []
  const ys: number[] = []
  let started = false
  for (let y = 0.0; y < 2.15; y += dy) {
    const inside = humanoidSDF(0, y, 0) < 0 || humanoidSDF(0, y, 0.05) < 0
    if (!inside) {
      if (started) break // sopra la testa
      continue
    }
    const radii: number[] = []
    let hint = 1.3
    for (let i = 0; i < COLS; i++) {
      const r = surfaceRadius(y, (i / COLS) * Math.PI * 2, hint)
      radii.push(r)
      hint = r > 0 ? r : 1.3
    }
    if (radii.some((r) => r < 0)) {
      if (started) break
      continue
    }
    started = true
    rings.push(radii)
    ys.push(y)
  }

  const pos: number[] = []
  const nor: number[] = []
  const idx: number[] = []
  const e = 0.0025
  const pushV = (x: number, y: number, z: number) => {
    pos.push(x, y, z)
    const nx = humanoidSDF(x + e, y, z) - humanoidSDF(x - e, y, z)
    const ny = humanoidSDF(x, y + e, z) - humanoidSDF(x, y - e, z)
    const nz = humanoidSDF(x, y, z + e) - humanoidSDF(x, y, z - e)
    const l = Math.hypot(nx, ny, nz) || 1
    nor.push(nx / l, ny / l, nz / l)
  }
  rings.forEach((radii, r) => {
    for (let i = 0; i < COLS; i++) {
      const a = (i / COLS) * Math.PI * 2
      pushV(Math.cos(a) * radii[i], ys[r], Math.sin(a) * radii[i])
    }
  })
  for (let r = 0; r < rings.length - 1; r++) {
    for (let i = 0; i < COLS; i++) {
      const a = r * COLS + i
      const b = r * COLS + ((i + 1) % COLS)
      const c = (r + 1) * COLS + i
      const d = (r + 1) * COLS + ((i + 1) % COLS)
      idx.push(a, c, b, b, c, d)
    }
  }
  // calotta superiore
  const last = rings.length - 1
  let cx = 0, cz = 0
  for (let i = 0; i < COLS; i++) {
    cx += pos[(last * COLS + i) * 3]
    cz += pos[(last * COLS + i) * 3 + 2]
  }
  const apex = pos.length / 3
  pos.push(cx / COLS, ys[last] + dy * 0.6, cz / COLS)
  nor.push(0, 1, 0)
  for (let i = 0; i < COLS; i++) idx.push(last * COLS + i, apex, last * COLS + ((i + 1) % COLS))

  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  g.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3))
  g.setIndex(idx)
  g.computeBoundingSphere()
  return g
}

/** Punti di riferimento nello spazio locale del busto. */
export const ANCHORS = {
  neckPivot: new THREE.Vector3(0, 1.1, -0.02),
  eyeL: new THREE.Vector3(-0.115, 1.575, 0.365),
  eyeR: new THREE.Vector3(0.115, 1.575, 0.365),
  mouth: new THREE.Vector3(0, 1.32, 0.4),
  heart: new THREE.Vector3(0.0, 0.62, 0.05),
}

/** Curva della fascia luminosa: segue il fondo del recesso, sul davanti del volto. */
export function visorCurve(): THREE.CatmullRomCurve3 {
  const pts: THREE.Vector3[] = []
  const y = 1.567
  for (let i = 0; i <= 40; i++) {
    const a = Math.PI * (0.2 + 0.6 * (i / 40)) // da destra a sinistra, davanti (+z)
    const r = surfaceRadius(y, a) + 0.004
    pts.push(new THREE.Vector3(Math.cos(a) * r, y, Math.sin(a) * r))
  }
  return new THREE.CatmullRomCurve3(pts)
}
