import { useFrame } from '@react-three/fiber'
import { useMemo, useRef } from 'react'
import * as THREE from 'three'
import { live, useStore } from '../store'
import { SNOISE } from './glsl'

/**
 * Città olografica: terreno a griglia con colline wireframe ai lati, grattacieli a reticolo
 * e un lento volo in avanti. Quando AXEL elabora la città accelera (effetto "warp").
 * Tutto procedurale e additivo: si fonde con lo sfondo senza texture.
 */

const FLOOR_Y = -0.65

/* ---------------- terreno: pianura centrale + colline ---------------- */

const terrainVert = /* glsl */ `
${SNOISE}
uniform float uScroll;
uniform float uTime;
uniform float uHills;
varying vec3 vW;
varying float vH;
float height(vec2 p){
  // valle centrale che si allarga con la distanza: le colline restano ai lati, mai su AXEL
  // valle stretta: le colline basse attraversano l'orizzonte; vicino restano ai lati e piccole
  float dist = 5.2 - p.y;
  float vw = max(3.2, dist * 0.11);
  float side = smoothstep(vw, vw * 1.9, abs(p.x));
  float amp = mix(0.0, 4.0, smoothstep(20.0, 70.0, dist)) * uHills; // solo creste lontane sull'orizzonte
  float z = p.y - uScroll;
  float n = snoise(vec3(p.x * 0.09, z * 0.08, uTime * 0.04)) * 0.5 + 0.5;
  float n2 = snoise(vec3(p.x * 0.25, z * 0.22, 4.1 + uTime * 0.07)) * 0.5 + 0.5;
  // onda lenta che attraversa le colline
  float wave = sin(z * 0.35 - uTime * 0.9 + p.x * 0.1);
  return side * amp * (n * 0.8 + n2 * 0.25 + wave * 0.2 + 0.15);
}
void main(){
  vec3 p = position;
  float h = height(p.xz);
  p.y += h;
  vH = h;
  vec4 w = modelMatrix * vec4(p, 1.0);
  vW = w.xyz;
  gl_Position = projectionMatrix * viewMatrix * w;
}
`
const terrainFrag = /* glsl */ `
uniform float uScroll;
uniform vec3 uColA;
uniform vec3 uColB;
uniform vec3 uCam;
uniform float uEnergy;
uniform float uTime;
varying vec3 vW;
varying float vH;
void main(){
  vec2 p = vec2(vW.x, vW.z - uScroll);
  vec2 cell = vec2(1.0, 1.0);
  vec2 g = abs(fract(p / cell - 0.5) - 0.5) / fwidth(p / cell);
  float line = 1.0 - min(min(g.x, g.y), 1.0);
  // diagonali sulle colline: effetto mesh triangolata
  float dgl = abs(fract((p.x + p.y) / cell.x - 0.5) - 0.5) / fwidth((p.x + p.y) / cell.x);
  float diag = (1.0 - min(dgl, 1.0)) * smoothstep(0.2, 1.2, vH) * 0.6;
  float l = max(line, diag);

  float d = length(vW.xz - uCam.xz);
  float fade = exp(-d * 0.021) * smoothstep(5.0, 16.0, d) * smoothstep(88.0, 70.0, d);
  vec3 col = mix(uColA, uColB, smoothstep(0.0, 6.0, vH));
  // riflesso violaceo vicino, come nel riferimento synthwave
  col = mix(col, vec3(0.55, 0.25, 1.0), smoothstep(12.0, 3.0, d) * (1.0 - smoothstep(0.5, 2.0, vH)) * 0.55);
  float hill = smoothstep(0.2, 1.6, vH);
  // scansione luminosa che scorre sulle colline verso l'orizzonte
  float scan = exp(-pow(fract((vW.z - uTime * 6.0) / 40.0) * 40.0 - 20.0, 2.0) * 0.08) * hill;
  float glow = 0.13 + uEnergy * 0.25 + hill * 0.5 + scan * 0.8;
  // bagliore lungo il viale centrale
  float lane = exp(-pow(vW.x * 0.35, 2.0)) * 0.08;
  vec3 c = col * (l * glow + lane) * fade;
  gl_FragColor = vec4(c, 1.0);
}
`

function Terrain({ hills = true }: { hills?: boolean }) {
  const mat = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: terrainVert,
        fragmentShader: terrainFrag,
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        uniforms: {
          uScroll: { value: 0 },
          uColA: { value: new THREE.Color() },
          uColB: { value: new THREE.Color() },
          uCam: { value: new THREE.Vector3() },
          uEnergy: { value: 0 },
          uTime: { value: 0 },
          uHills: { value: 1 },
        },
      }),
    [],
  )
  const geo = useMemo(() => {
    const g = new THREE.PlaneGeometry(110, 90, 220, 180)
    g.rotateX(-Math.PI / 2)
    g.translate(0, 0, -38)
    return g
  }, [])
  useFrame(({ camera, clock }) => {
    mat.uniforms.uTime.value = clock.elapsedTime
    mat.uniforms.uHills.value = hills ? 1 : 0
    mat.uniforms.uScroll.value = scroll.z
    mat.uniforms.uEnergy.value = scroll.energy
    mat.uniforms.uCam.value.copy(camera.position)
    const a = useStore.getState().current()
    mat.uniforms.uColA.value.set(a?.accent ?? '#3ff0f7')
    mat.uniforms.uColB.value.set(a?.accent2 ?? '#1e7fe0')
  })
  return <mesh geometry={geo} material={mat} position={[0, FLOOR_Y, 0]} frustumCulled={false} renderOrder={-1} />
}

/* ---------------- grattacieli a reticolo (instanced) ---------------- */

const bVert = /* glsl */ `
attribute vec4 aSeed; // x: random, y: altezza, z,w: riservati
varying vec3 vW;
varying vec3 vL;
varying vec3 vN;
varying vec4 vSeed;
void main(){
  vec4 w = modelMatrix * instanceMatrix * vec4(position, 1.0);
  vW = w.xyz;
  vL = position;                 // -0.5..0.5 locale
  vN = normal;
  vSeed = aSeed;
  gl_Position = projectionMatrix * viewMatrix * w;
}
`
const bFrag = /* glsl */ `
uniform float uTime;
uniform vec3 uColA;
uniform vec3 uColB;
uniform vec3 uCam;
uniform float uEnergy;
varying vec3 vW;
varying vec3 vL;
varying vec3 vN;
varying vec4 vSeed;
float gridLine(vec2 p){
  vec2 g = abs(fract(p - 0.5) - 0.5) / fwidth(p);
  return 1.0 - min(min(g.x, g.y), 1.0);
}
void main(){
  vec3 n = abs(vN);
  // coordinate sulla faccia in unità del mondo (spaziatura costante qualunque sia la dimensione)
  vec2 uv = n.x > 0.5 ? vW.zy : (n.z > 0.5 ? vW.xy : vW.xz);
  vec2 q = uv * vec2(2.2, 2.6);
  float grid = gridLine(q);
  float diag = abs(fract(q.x + q.y - 0.5) - 0.5) / fwidth(q.x + q.y);
  float tri = (1.0 - min(diag, 1.0)) * 0.55;
  // spigoli dell'edificio
  vec3 e = 0.5 - abs(vL);
  vec3 fw = fwidth(vL) * 1.5;
  float edges = 0.0;
  if (n.x < 0.5) edges = max(edges, 1.0 - smoothstep(0.0, fw.x, e.x));
  if (n.y < 0.5) edges = max(edges, 1.0 - smoothstep(0.0, fw.y, e.y));
  if (n.z < 0.5) edges = max(edges, 1.0 - smoothstep(0.0, fw.z, e.z));

  // finestre che si accendono a caso
  vec2 cell = floor(q);
  float rnd = fract(sin(dot(cell + vSeed.x * 37.0, vec2(12.9898, 78.233))) * 43758.5453);
  float win = step(0.93, rnd) * (0.5 + 0.5 * sin(uTime * (0.5 + rnd * 2.0) + rnd * 40.0));
  // impulso dati che sale lungo la torre
  float h01 = vL.y + 0.5;
  float pulse = smoothstep(0.92, 1.0, fract(h01 * 1.2 - uTime * (0.15 + vSeed.x * 0.2) - vSeed.x));

  float d = length(vW.xz - uCam.xz);
  float fade = exp(-d * 0.022) * smoothstep(12.0, 20.0, d);
  float topFade = 0.55 + 0.45 * h01; // più luminose verso l'alto
  vec3 col = mix(uColB, uColA, h01 * 0.8 + edges * 0.3);
  float l = grid * 0.32 + tri * 0.22 + edges * 1.1 + win * 0.7 + pulse * (0.6 + uEnergy);
  vec3 c = col * (l * topFade + 0.012) * fade * 0.32 * (1.0 + uEnergy * 0.6);
  if (n.y > 0.5 && vN.y < 0.0) c *= 0.0; // niente base
  gl_FragColor = vec4(c, 1.0);
}
`

interface Tower {
  x: number
  z: number
  w: number
  d: number
  h: number
}

function makeTowers(): Tower[] {
  const out: Tower[] = []
  let seed = 11
  const rand = () => ((seed = (seed * 16807) % 2147483647) / 2147483647)
  const CAM_Z = 5.2
  for (const side of [-1, 1]) {
    for (let i = 0; i < 6; i++) {
      const z = -22 - i * 5 - rand() * 3
      const halfW = (CAM_Z - z) * 0.55 // metà larghezza visibile a quella distanza (16:10)
            // a sinistra possono stare dietro AXEL (la sagoma li copre); a destra lasciano libero il cuore dati
      const x = side * halfW * (0.8 + rand() * 0.2) // solo ai bordi
      out.push({ x, z, w: 1.2 + rand() * 1.8, d: 1.2 + rand() * 1.8, h: 5 + rand() * 11 + i * 0.5 })
    }
  }
  return out
}

function Towers() {
  const towers = useMemo(makeTowers, [])
  const ref = useRef<THREE.InstancedMesh>(null)
  const geo = useMemo(() => {
    const g = new THREE.BoxGeometry(1, 1, 1)
    const seeds = new Float32Array(towers.length * 4)
    towers.forEach((t, i) => {
      seeds[i * 4] = Math.random()
      seeds[i * 4 + 1] = t.h
    })
    g.setAttribute('aSeed', new THREE.InstancedBufferAttribute(seeds, 4))
    return g
  }, [towers])
  const mat = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: bVert,
        fragmentShader: bFrag,
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        side: THREE.DoubleSide,
        uniforms: {
          uTime: { value: 0 },
          uColA: { value: new THREE.Color() },
          uColB: { value: new THREE.Color() },
          uCam: { value: new THREE.Vector3() },
          uEnergy: { value: 0 },
        },
      }),
    [],
  )
  const m = useMemo(() => new THREE.Matrix4(), [])
  const pos = useMemo(() => new THREE.Vector3(), [])
  const quat = useMemo(() => new THREE.Quaternion(), [])
  const scl = useMemo(() => new THREE.Vector3(), [])

  useFrame(({ camera, clock }) => {
    const mesh = ref.current
    if (!mesh) return
    towers.forEach((t, i) => {
      pos.set(t.x, FLOOR_Y + t.h / 2, t.z)
      scl.set(t.w, t.h, t.d)
      m.compose(pos, quat, scl)
      mesh.setMatrixAt(i, m)
    })
    mesh.instanceMatrix.needsUpdate = true
    const u = mat.uniforms
    u.uTime.value = clock.elapsedTime
    u.uCam.value.copy(camera.position)
    u.uEnergy.value = scroll.energy
    const a = useStore.getState().current()
    u.uColA.value.set(a?.accent ?? '#3ff0f7')
    u.uColB.value.set(a?.accent2 ?? '#1e7fe0')
  })

  return <instancedMesh ref={ref} args={[geo, mat, towers.length]} frustumCulled={false} renderOrder={-1} />
}

/* ---------------- volo condiviso ---------------- */

const scroll = { z: 0, speed: 0.55, energy: 0 }

function Flight() {
  useFrame((_, dt) => {
    const st = useStore.getState().state
    const target = st === 'thinking' ? 3.2 : st === 'speaking' ? 0.9 + live.level * 0.6 : 0.55
    scroll.speed += (target - scroll.speed) * (1 - Math.exp(-dt * 1.2))
    scroll.energy += ((st === 'thinking' ? 1 : 0) - scroll.energy) * (1 - Math.exp(-dt * 2))
    scroll.z += scroll.speed * Math.min(dt, 0.1)
  })
  return null
}

export function City({ hills = true, towers = true }: { hills?: boolean; towers?: boolean }) {
  return (
    <group>
      <Flight />
      <Terrain hills={hills} />
      {towers && <Towers />}
    </group>
  )
}
