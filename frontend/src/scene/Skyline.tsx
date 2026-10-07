import { useFrame } from '@react-three/fiber'
import { useMemo } from 'react'
import * as THREE from 'three'
import { live, useStore } from '../store'

/**
 * Scenario "skyline vettoriale": grattacieli disegnati a linee sottili ai lati, colline a linea
 * sull'orizzonte con nodi luminosi, archi e nebulosa di punti nel cielo, raggio di luce verticale
 * al centro che attraversa il "pensiero" di AXEL. Tutto a basso contrasto: AXEL resta protagonista.
 */

const FLOOR_Y = -0.65
const CAM_Z = 6

function rng(seed: number) {
  return () => ((seed = (seed * 16807) % 2147483647) / 2147483647)
}

const lineMat = () =>
  new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending })

const pointsMat = (size: number) =>
  new THREE.PointsMaterial({
    size, vertexColors: true, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true,
  })

/* ---------------- grattacieli vettoriali ---------------- */

function useTowers() {
  return useMemo(() => {
    const rand = rng(23)
    const lp: number[] = []
    const lc: number[] = []
    const fp: number[] = []
    const fa: number[] = []
    const tips: number[] = []
    const seg = (a: number[], b: number[], i1: number, i2 = i1) => {
      lp.push(...a, ...b)
      lc.push(i1, i1, i1, i2, i2, i2)
    }
    for (const side of [-1, 1]) {
      for (let i = 0; i < 9; i++) {
        const z = -9 - i * 2.8 - rand() * 1.5
        const halfW = (CAM_Z - z) * 0.55
        const xc = side * halfW * (0.6 + rand() * 0.38)
        const w = 0.7 + rand() * 1.0
        const h = 2.2 + rand() * 3.2 + i * 0.45
        const cut = w * (0.5 + rand() * 0.5) // taglio curvo in cima
        const x0 = xc - w / 2
        const x1 = xc + w / 2
        const yb = FLOOR_Y
        // il lato verso il centro è il più alto
        const inner = side < 0 ? x1 : x0
        const outer = side < 0 ? x0 : x1
        const k = 0.34 / (1 + i * 0.1) // più lontano = più tenue
        seg([inner, yb, z], [inner, yb + h, z], k)
        seg([outer, yb, z], [outer, yb + h - cut, z], k)
        // curva superiore (quadratica)
        let prev = [inner, yb + h, z]
        for (let s = 1; s <= 10; s++) {
          const t = s / 10
          const cx = inner + (outer - inner) * 0.15
          const cy = yb + h + cut * 0.1
          const x = (1 - t) ** 2 * inner + 2 * (1 - t) * t * cx + t * t * outer
          const y = (1 - t) ** 2 * (yb + h) + 2 * (1 - t) * t * cy + t * t * (yb + h - cut)
          const p = [x, y, z]
          seg(prev, p, k)
          prev = p
        }
        // linee verticali interne + finestre a punti
        for (const f of [0.33, 0.66]) {
          const x = x0 + w * f
          seg([x, yb, z], [x, yb + h - cut * 1.1, z], k * 0.35, k * 0.1)
        }
        // vetro: quad con gradiente
        const top = yb + h - cut
        fp.push(x0, yb, z, x1, yb, z, x1, top, z, x0, yb, z, x1, top, z, x0, top, z)
        fa.push(0, 0, 1, 0, 1, 1)
        // antenna
        if (rand() < 0.45) {
          const ah = 1.5 + rand() * 4
          seg([inner, yb + h, z], [inner, yb + h + ah, z], k * 0.9, k * 0.1)
          tips.push(inner, yb + h + ah * (0.5 + rand() * 0.5), z)
        }
      }
      // piattaforma circolare (anello) a metà altezza, come nel riferimento
      const pz = -9 - rand() * 4
      const px = side * (CAM_Z - pz) * 0.55 * 0.82
      const py = FLOOR_Y + 1.1 + rand() * 0.8
      let prev: number[] | null = null
      for (let s = 0; s <= 64; s++) {
        const a = (s / 64) * Math.PI * 2
        const p = [px + Math.cos(a) * 2.2, py, pz + Math.sin(a) * 0.9]
        if (prev) seg(prev, p, 0.32)
        prev = p
      }
    }
    const lines = new THREE.BufferGeometry()
    lines.setAttribute('position', new THREE.Float32BufferAttribute(lp, 3))
    const col = new Float32Array(lc.length)
    lines.setAttribute('color', new THREE.BufferAttribute(col, 3))
    const fill = new THREE.BufferGeometry()
    fill.setAttribute('position', new THREE.Float32BufferAttribute(fp, 3))
    fill.setAttribute('aV', new THREE.Float32BufferAttribute(fa, 1))
    const tip = new THREE.BufferGeometry()
    tip.setAttribute('position', new THREE.Float32BufferAttribute(tips, 3))
    tip.setAttribute('color', new THREE.BufferAttribute(new Float32Array(tips.length), 3))
    return { lines, intensity: lc, fill, tip }
  }, [])
}

const fillMat = () =>
  new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    uniforms: { uCol: { value: new THREE.Color() } },
    vertexShader: `attribute float aV; varying float vV; void main(){ vV = aV; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`,
    fragmentShader: `uniform vec3 uCol; varying float vV; void main(){ float a = 0.006 + vV * 0.028; gl_FragColor = vec4(uCol * a, 1.0); }`,
  })

function Towers() {
  const { lines, intensity, fill, tip } = useTowers()
  const lm = useMemo(lineMat, [])
  const fm = useMemo(fillMat, [])
  const tm = useMemo(() => pointsMat(0.09), [])
  const c = useMemo(() => new THREE.Color(), [])
  useFrame(({ clock }) => {
    const a = useStore.getState().current()
    c.set(a?.accent ?? '#3ff0f7').lerp(new THREE.Color('#9fd0ff'), 0.45)
    const col = lines.attributes.color.array as Float32Array
    for (let i = 0; i < intensity.length; i++) {
      col[i * 3] = c.r * intensity[i]
      col[i * 3 + 1] = c.g * intensity[i]
      col[i * 3 + 2] = c.b * intensity[i]
    }
    lines.attributes.color.needsUpdate = true
    fm.uniforms.uCol.value.copy(c)
    const tc = tip.attributes.color.array as Float32Array
    for (let i = 0; i < tc.length / 3; i++) {
      const p = 0.5 + 0.5 * Math.sin(clock.elapsedTime * 1.5 + i * 1.7)
      tc[i * 3] = c.r * (0.4 + p)
      tc[i * 3 + 1] = c.g * (0.4 + p)
      tc[i * 3 + 2] = c.b * (0.4 + p)
    }
    tip.attributes.color.needsUpdate = true
  })
  return (
    <group>
      <mesh geometry={fill} material={fm} renderOrder={-1} />
      <lineSegments geometry={lines} material={lm} renderOrder={-1} frustumCulled={false} />
      <points geometry={tip} material={tm} renderOrder={-1} />
    </group>
  )
}

/* ---------------- colline a linea sull'orizzonte ---------------- */

const LAYERS = [
  { z: -24, amp: 1.4, k: 0.34, f: 0.16, ph: 0.3 },
  { z: -34, amp: 2.4, k: 0.26, f: 0.11, ph: 1.9 },
  { z: -48, amp: 3.8, k: 0.18, f: 0.08, ph: 4.2 },
]
const HILL_PTS = 260

function hillY(x: number, L: (typeof LAYERS)[number], t: number) {
  const center = Math.min(1, Math.abs(x) / 12) // più basse al centro
  const n = Math.sin(x * L.f + L.ph + t * 0.05) * 0.5 + Math.sin(x * L.f * 2.3 + L.ph * 2 - t * 0.07) * 0.3 +
    Math.sin(x * L.f * 4.1 + L.ph * 3) * 0.15
  return FLOOR_Y + (0.35 + 0.65 * center) * L.amp * (0.55 + 0.45 * n)
}

function Hills() {
  const { geo, nodes } = useMemo(() => {
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(LAYERS.length * HILL_PTS * 2 * 3), 3))
    geo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(LAYERS.length * HILL_PTS * 2 * 3), 3))
    const nodes = new THREE.BufferGeometry()
    const n = LAYERS.length * Math.floor(HILL_PTS / 13)
    nodes.setAttribute('position', new THREE.BufferAttribute(new Float32Array(n * 3), 3))
    nodes.setAttribute('color', new THREE.BufferAttribute(new Float32Array(n * 3), 3))
    return { geo, nodes }
  }, [])
  const lm = useMemo(lineMat, [])
  const nm = useMemo(() => pointsMat(0.16), [])
  const c = useMemo(() => new THREE.Color(), [])
  useFrame(({ clock }) => {
    const t = clock.elapsedTime
    const a = useStore.getState().current()
    c.set(a?.accent ?? '#3ff0f7').lerp(new THREE.Color('#9fd0ff'), 0.35)
    const p = geo.attributes.position.array as Float32Array
    const col = geo.attributes.color.array as Float32Array
    const np = nodes.attributes.position.array as Float32Array
    const nc = nodes.attributes.color.array as Float32Array
    let v = 0
    let nn = 0
    LAYERS.forEach((L) => {
      const span = (CAM_Z - L.z) * 0.62
      let px = -span
      let py = hillY(px, L, t)
      for (let i = 1; i <= HILL_PTS; i++) {
        const x = -span + (i / HILL_PTS) * span * 2
        const y = hillY(x, L, t)
        const fadeEdge = Math.min(1, (span - Math.abs(x)) / (span * 0.15))
        const k = L.k * fadeEdge
        p.set([px, py, L.z, x, y, L.z], v * 3)
        col.set([c.r * k, c.g * k, c.b * k, c.r * k, c.g * k, c.b * k], v * 3)
        v += 2
        if (i % 13 === 0 && nn < np.length / 3) {
          const tw = 0.5 + 0.5 * Math.sin(t * 1.3 + i * 0.7 + L.z)
          np.set([x, y, L.z], nn * 3)
          const kk = (0.3 + tw * 0.9) * fadeEdge
          nc.set([c.r * kk, c.g * kk, c.b * kk], nn * 3)
          nn++
        }
        px = x
        py = y
      }
    })
    geo.attributes.position.needsUpdate = true
    geo.attributes.color.needsUpdate = true
    nodes.attributes.position.needsUpdate = true
    nodes.attributes.color.needsUpdate = true
  })
  return (
    <group>
      <lineSegments geometry={geo} material={lm} renderOrder={-1} frustumCulled={false} />
      <points geometry={nodes} material={nm} renderOrder={-1} frustumCulled={false} />
    </group>
  )
}

/* ---------------- cielo: archi a cupola + nebulosa di punti ---------------- */

function Sky() {
  const { arcs, arcCount, dust, dustBase, pulses } = useMemo(() => {
    const rand = rng(91)
    const ap: number[] = []
    const ac: number[] = []
    const arcCount = 5
    const arcDefs: { r: number; tilt: number; y: number }[] = []
    for (let i = 0; i < arcCount; i++) {
      const r = 26 + i * 6
      const tilt = -0.25 + i * 0.12
      const y = FLOOR_Y + 2 + i * 0.6
      arcDefs.push({ r, tilt, y })
      let prev: number[] | null = null
      for (let s = 0; s <= 120; s++) {
        const a = Math.PI * (0.06 + 0.88 * (s / 120))
        const p = [Math.cos(a) * r, y + Math.sin(a) * r * 0.42, -38 + Math.sin(a) * r * tilt]
        const k = 0.1 * Math.sin((s / 120) * Math.PI)
        if (prev) {
          ap.push(...prev, ...p)
          ac.push(k, k, k, k, k, k)
        }
        prev = p
      }
    }
    const arcs = new THREE.BufferGeometry()
    arcs.setAttribute('position', new THREE.Float32BufferAttribute(ap, 3))
    arcs.setAttribute('color', new THREE.BufferAttribute(new Float32Array(ac), 3))
    // nebulosa: punti su una griglia mascherata da "continenti" astratti
    const dp: number[] = []
    const db: number[] = []
    for (let gx = -60; gx <= 60; gx++) {
      for (let gy = 0; gy <= 26; gy++) {
        const x = gx * 0.42
        const y = 5.5 + gy * 0.42
        const m = Math.sin(x * 0.21 + 1.3) * Math.cos(y * 0.33 - 0.4) + Math.sin(x * 0.07 - y * 0.12 + 2.1) * 0.8 +
          Math.sin(x * 0.5 + y * 0.6) * 0.18
        const edge = 1 - Math.abs(gx) / 60
        if (m > 0.45 && rand() < 0.85) {
          dp.push(x, y + Math.cos(x * 0.06) * -1.4, -44)
          db.push((0.12 + rand() * 0.22) * Math.min(1, edge * 2.2))
        }
      }
    }
    const dust = new THREE.BufferGeometry()
    dust.setAttribute('position', new THREE.Float32BufferAttribute(dp, 3))
    dust.setAttribute('color', new THREE.BufferAttribute(new Float32Array(dp.length), 3))
    const pulses = new THREE.BufferGeometry()
    pulses.setAttribute('position', new THREE.BufferAttribute(new Float32Array(arcCount * 3), 3))
    pulses.setAttribute('color', new THREE.BufferAttribute(new Float32Array(arcCount * 3), 3))
    ;(pulses as unknown as { userData: unknown }).userData = arcDefs
    return { arcs, arcCount, dust, dustBase: db, pulses }
  }, [])
  const lm = useMemo(lineMat, [])
  const dm = useMemo(() => pointsMat(0.11), [])
  const pm = useMemo(() => pointsMat(0.35), [])
  const c = useMemo(() => new THREE.Color(), [])
  useFrame(({ clock }) => {
    const t = clock.elapsedTime
    const a = useStore.getState().current()
    c.set(a?.accent ?? '#3ff0f7').lerp(new THREE.Color('#bfe0ff'), 0.4)
    const ac = arcs.attributes.color.array as Float32Array
    // gli archi hanno intensità base salvata nel canale stesso: ricoloriamo mantenendo il rapporto
    for (let i = 0; i < ac.length; i += 3) {
      const k = Math.max(ac[i], ac[i + 1], ac[i + 2]) || 0
      const kk = k / (Math.max(c.r, c.g, c.b) || 1)
      ac[i] = c.r * kk
      ac[i + 1] = c.g * kk
      ac[i + 2] = c.b * kk
    }
    arcs.attributes.color.needsUpdate = true
    const dc = dust.attributes.color.array as Float32Array
    for (let i = 0; i < dustBase.length; i++) {
      const tw = 0.7 + 0.3 * Math.sin(t * 0.8 + i * 12.9898)
      const k = dustBase[i] * tw
      dc[i * 3] = c.r * k
      dc[i * 3 + 1] = c.g * k
      dc[i * 3 + 2] = c.b * k
    }
    dust.attributes.color.needsUpdate = true
    // impulsi luminosi che percorrono gli archi
    const defs = (pulses as unknown as { userData: { r: number; tilt: number; y: number }[] }).userData
    const pp = pulses.attributes.position.array as Float32Array
    const pc = pulses.attributes.color.array as Float32Array
    defs.forEach((d, i) => {
      const s = (t * (0.025 + i * 0.006) + i * 0.37) % 1
      const ang = Math.PI * (0.06 + 0.88 * (i % 2 ? 1 - s : s))
      pp.set([Math.cos(ang) * d.r, d.y + Math.sin(ang) * d.r * 0.42, -38 + Math.sin(ang) * d.r * d.tilt], i * 3)
      const k = Math.sin(s * Math.PI) * 0.9
      pc.set([c.r * k, c.g * k, c.b * k], i * 3)
    })
    pulses.attributes.position.needsUpdate = true
    pulses.attributes.color.needsUpdate = true
    void arcCount
  })
  return (
    <group>
      <lineSegments geometry={arcs} material={lm} renderOrder={-1} frustumCulled={false} />
      <points geometry={dust} material={dm} renderOrder={-1} frustumCulled={false} />
      <points geometry={pulses} material={pm} renderOrder={-1} frustumCulled={false} />
    </group>
  )
}

/* ---------------- raggio centrale + anelli attorno al pensiero ---------------- */

function Beam({ core, radius }: { core: [number, number, number]; radius: number }) {
  const { line, rings, dots } = useMemo(() => {
    const lp: number[] = []
    const lc: number[] = []
    const N = 80
    for (let i = 0; i < N; i++) {
      const y0 = FLOOR_Y + (i / N) * 22
      const y1 = FLOOR_Y + ((i + 1) / N) * 22
      lp.push(0, y0, 0, 0, y1, 0)
      lc.push(0, 0, 0, 0, 0, 0)
    }
    const line = new THREE.BufferGeometry()
    line.setAttribute('position', new THREE.Float32BufferAttribute(lp, 3))
    line.setAttribute('color', new THREE.BufferAttribute(new Float32Array(lc), 3))
    const rp: number[] = []
    for (const r of [1.32, 1.7]) {
      for (let s = 0; s < 128; s++) {
        const a0 = (s / 128) * Math.PI * 2
        const a1 = ((s + 1) / 128) * Math.PI * 2
        rp.push(Math.cos(a0) * r, Math.sin(a0) * r, 0, Math.cos(a1) * r, Math.sin(a1) * r, 0)
      }
    }
    const rings = new THREE.BufferGeometry()
    rings.setAttribute('position', new THREE.Float32BufferAttribute(rp, 3))
    rings.setAttribute('color', new THREE.BufferAttribute(new Float32Array(rp.length), 3))
    const dots = new THREE.BufferGeometry()
    dots.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6 * 3), 3))
    dots.setAttribute('color', new THREE.BufferAttribute(new Float32Array(6 * 3), 3))
    return { line, rings, dots }
  }, [])
  const lm = useMemo(lineMat, [])
  const rm = useMemo(lineMat, [])
  const dm = useMemo(() => pointsMat(0.07), [])
  const c = useMemo(() => new THREE.Color(), [])
  const energy = useMemo(() => ({ v: 0 }), [])
  useFrame(({ clock }, dt) => {
    const t = clock.elapsedTime
    const st = useStore.getState().state
    energy.v += ((st === 'thinking' ? 1 : st === 'speaking' ? 0.5 + live.level * 0.5 : 0.15) - energy.v) * (1 - Math.exp(-dt * 3))
    const a = useStore.getState().current()
    c.set(a?.accent ?? '#3ff0f7')
    // raggio: più intenso vicino al pensiero, un impulso scorre verso l'alto
    const col = line.attributes.color.array as Float32Array
    const N = col.length / 6
    for (let i = 0; i < N; i++) {
      const y = FLOOR_Y + ((i + 0.5) / N) * 22
      const near = Math.exp(-Math.abs(y - core[1]) * 0.35)
      const pulse = Math.exp(-(((y - FLOOR_Y - ((t * 2.2) % 26)) * 0.9) ** 2))
      const k = (0.08 + near * 0.35 + pulse * 0.5) * (0.6 + energy.v * 0.8) * Math.min(1, (22 - (y - FLOOR_Y)) / 8)
      col.set([c.r * k, c.g * k, c.b * k, c.r * k, c.g * k, c.b * k], i * 6)
    }
    line.attributes.color.needsUpdate = true
    const rc = rings.attributes.color.array as Float32Array
    const half = rc.length / 2
    for (let i = 0; i < rc.length; i += 3) {
      const k = (i < half ? 0.32 : 0.18) * (0.7 + energy.v * 0.6)
      rc[i] = c.r * k
      rc[i + 1] = c.g * k
      rc[i + 2] = c.b * k
    }
    rings.attributes.color.needsUpdate = true
    // piccoli nodi che orbitano sugli anelli
    const dp = dots.attributes.position.array as Float32Array
    const dc = dots.attributes.color.array as Float32Array
    for (let i = 0; i < 6; i++) {
      const r = (i < 3 ? 1.32 : 1.7) * radius
      const ang = t * (i < 3 ? 0.35 : -0.22) * (1 + energy.v) + (i % 3) * 2.094
      dp.set([Math.cos(ang) * r, Math.sin(ang) * r, 0], i * 3)
      const k = 0.9 + energy.v
      dc.set([c.r * k, c.g * k, c.b * k], i * 3)
    }
    dots.attributes.position.needsUpdate = true
    dots.attributes.color.needsUpdate = true
  })
  return (
    <group>
      <lineSegments geometry={line} material={lm} position={[core[0], 0, core[2] - 0.6]} renderOrder={-1} frustumCulled={false} />
      <group position={core}>
        <lineSegments geometry={rings} material={rm} scale={radius} frustumCulled={false} />
        <points geometry={dots} material={dm} frustumCulled={false} />
      </group>
    </group>
  )
}

export function Skyline({ core, coreRadius }: { core: [number, number, number]; coreRadius: number }) {
  return (
    <group>
      <Sky />
      <Hills />
      <Towers />
      <Beam core={core} radius={coreRadius} />
    </group>
  )
}
