import { useFrame } from '@react-three/fiber'
import { useMemo } from 'react'
import * as THREE from 'three'
import { useStore } from '../store'

/** Rete poligonale luminosa sullo sfondo (nodi + linee + triangoli traslucidi). */

const N = 90
const MAX_DIST = 3.4
const HUB_LINKS = 6

export function Plexus({ hub }: { hub?: [number, number, number] }) {
  const energy = useMemo(() => ({ v: 0 }), [])
  const data = useMemo(() => {
    const home = new Float32Array(N * 3)
    const phase = new Float32Array(N * 3)
    for (let i = 0; i < N; i++) {
      // più denso a destra/in basso, come nel riferimento
      // rete nel cielo, simmetrica, sopra lo skyline
      home[i * 3] = (Math.random() * 2 - 1) * 17
      home[i * 3 + 1] = 5.2 + Math.random() * 6.5
      home[i * 3 + 2] = -11 - Math.random() * 9
      phase[i * 3] = Math.random() * 6.28
      phase[i * 3 + 1] = Math.random() * 6.28
      phase[i * 3 + 2] = 0.15 + Math.random() * 0.35
    }
    const pos = new Float32Array(N * 3)
    // triangoli: per alcuni nodi, i due vicini più prossimi
    const tris: number[] = []
    for (let i = 0; i < N; i += 5) {
      const d = [...Array(N).keys()]
        .filter((j) => j !== i)
        .map((j) => [j, Math.hypot(home[i * 3] - home[j * 3], home[i * 3 + 1] - home[j * 3 + 1], home[i * 3 + 2] - home[j * 3 + 2])])
        .sort((a, b) => a[1] - b[1])
      if (d[1][1] < MAX_DIST * 1.1) tris.push(i, d[0][0], d[1][0])
    }
    const lineGeo = new THREE.BufferGeometry()
    lineGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(N * N * 3), 3))
    lineGeo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(N * N * 3), 3))
    const nodeGeo = new THREE.BufferGeometry()
    nodeGeo.setAttribute('position', new THREE.BufferAttribute(pos, 3))
    const triGeo = new THREE.BufferGeometry()
    triGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(tris.length * 3), 3))
    triGeo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(tris.length * 3), 3))
    return { home, phase, pos, tris, lineGeo, nodeGeo, triGeo }
  }, [])

  const colA = useMemo(() => new THREE.Color(), [])
  const colB = useMemo(() => new THREE.Color(), [])
  const tmp = useMemo(() => new THREE.Color(), [])

  useFrame(({ clock }) => {
    const t = clock.elapsedTime
    const agent = useStore.getState().current()
    colA.set(agent?.accent ?? '#3ff0f7')
    colB.set(agent?.accent2 ?? '#1e7fe0')
    const { home, phase, pos, lineGeo, nodeGeo, triGeo, tris } = data
    for (let i = 0; i < N; i++) {
      const a = phase[i * 3 + 2]
      pos[i * 3] = home[i * 3] + Math.sin(t * a + phase[i * 3]) * 0.9
      pos[i * 3 + 1] = home[i * 3 + 1] + Math.cos(t * a * 0.8 + phase[i * 3 + 1]) * 0.6
      pos[i * 3 + 2] = home[i * 3 + 2]
    }
    nodeGeo.attributes.position.needsUpdate = true

    const lp = lineGeo.attributes.position.array as Float32Array
    const lc = lineGeo.attributes.color.array as Float32Array
    let v = 0
    for (let i = 0; i < N; i++) {
      for (let j = i + 1; j < N; j++) {
        const dx = pos[i * 3] - pos[j * 3], dy = pos[i * 3 + 1] - pos[j * 3 + 1], dz = pos[i * 3 + 2] - pos[j * 3 + 2]
        const d = Math.sqrt(dx * dx + dy * dy + dz * dz)
        if (d > MAX_DIST) continue
        const f = (1 - d / MAX_DIST) * 0.2
        for (const k of [i, j]) {
          tmp.copy(colA).lerp(colB, Math.min(1, Math.max(0, (pos[k * 3] + 6) / 14)))
          lp[v * 3] = pos[k * 3]; lp[v * 3 + 1] = pos[k * 3 + 1]; lp[v * 3 + 2] = pos[k * 3 + 2]
          lc[v * 3] = tmp.r * f; lc[v * 3 + 1] = tmp.g * f; lc[v * 3 + 2] = tmp.b * f
          v++
        }
      }
    }
    // connessioni tra il pensiero di AXEL e i nodi più vicini: si accendono quando elabora
    if (hub) {
      const st = useStore.getState().state
      energy.v += ((st === 'thinking' ? 1 : st === 'speaking' ? 0.45 : 0.08) - energy.v) * 0.04
      const near = [...Array(N).keys()]
        .map((i) => [i, Math.hypot(pos[i * 3] - hub[0], pos[i * 3 + 1] - hub[1])] as const)
        .sort((a, b) => a[1] - b[1])
        .slice(0, HUB_LINKS)
      near.forEach(([i], n) => {
        const flick = 0.6 + 0.4 * Math.sin(t * 3 + n * 1.9)
        const f = energy.v * 0.45 * flick
        lp.set([hub[0], hub[1], hub[2], pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]], v * 3)
        lc.set([colA.r * f, colA.g * f, colA.b * f, colA.r * f * 0.5, colA.g * f * 0.5, colA.b * f * 0.5], v * 3)
        v += 2
      })
    }
    lineGeo.setDrawRange(0, v)
    lineGeo.attributes.position.needsUpdate = true
    lineGeo.attributes.color.needsUpdate = true

    const tp = triGeo.attributes.position.array as Float32Array
    const tc = triGeo.attributes.color.array as Float32Array
    tris.forEach((idx, n) => {
      tp[n * 3] = pos[idx * 3]; tp[n * 3 + 1] = pos[idx * 3 + 1]; tp[n * 3 + 2] = pos[idx * 3 + 2]
      tmp.copy(colB).lerp(colA, (n % 3) / 3)
      tc[n * 3] = tmp.r * 0.018; tc[n * 3 + 1] = tmp.g * 0.018; tc[n * 3 + 2] = tmp.b * 0.018
    })
    triGeo.attributes.position.needsUpdate = true
    triGeo.attributes.color.needsUpdate = true
  })

  return (
    <group>
      <lineSegments geometry={data.lineGeo} frustumCulled={false}>
        <lineBasicMaterial vertexColors transparent blending={THREE.AdditiveBlending} depthWrite={false} />
      </lineSegments>
      <mesh geometry={data.triGeo} frustumCulled={false}>
        <meshBasicMaterial vertexColors transparent side={THREE.DoubleSide} blending={THREE.AdditiveBlending} depthWrite={false} />
      </mesh>
      <points geometry={data.nodeGeo} frustumCulled={false}>
        <pointsMaterial size={0.09} color="#cfe8ff" transparent opacity={0.8} blending={THREE.AdditiveBlending} depthWrite={false} />
      </points>
    </group>
  )
}

/** Sfondo a gradiente indaco → viola → magenta (dal template allegato). */
export function Backdrop() {
  const mat = useMemo(
    () =>
      new THREE.ShaderMaterial({
        depthWrite: false,
        uniforms: { uTime: { value: 0 } },
        vertexShader: `varying vec2 vUv; void main(){ vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);} `,
        fragmentShader: /* glsl */ `
          varying vec2 vUv; uniform float uTime;
          void main(){
            vec3 a = vec3(0.002, 0.016, 0.060);
            vec3 b = vec3(0.004, 0.030, 0.105);
            vec3 c = vec3(0.006, 0.045, 0.140);
            float g = smoothstep(0.0, 1.0, vUv.x * 0.7 + (1.0 - vUv.y) * 0.3);
            vec3 col = mix(a, b, g);
            col = mix(col, c, smoothstep(0.55, 1.1, vUv.x * 0.6 + (1.0 - vUv.y) * 0.5) * 0.7);
            // orizzonte luminoso dietro la città
            float hz = vUv.y - 0.503;
            col += vec3(0.0, 0.09, 0.24) * exp(-pow(hz * 20.0, 2.0)) * (0.85 + 0.15 * sin(uTime * 0.4));
            col += vec3(0.0, 0.035, 0.09) * exp(-abs(hz) * 9.0);
            col *= mix(1.0, 0.55, smoothstep(0.52, 0.9, vUv.y)); // cielo più scuro in alto
            gl_FragColor = vec4(col, 1.0);
          }`,
      }),
    [],
  )
  useFrame((_, dt) => (mat.uniforms.uTime.value += dt))
  return (
    <mesh position={[0, 1, -82]} scale={[340, 160, 1]} material={mat} renderOrder={-2}>
      <planeGeometry />
    </mesh>
  )
}
