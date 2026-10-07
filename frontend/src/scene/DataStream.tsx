import { useFrame } from '@react-three/fiber'
import { useMemo, useRef } from 'react'
import * as THREE from 'three'
import { live, useStore } from '../store'
import { SOFT_POINT_FRAG } from './glsl'

/**
 * Flusso di particelle lungo una curva tra la bocca dell'umanoide e il cuore dati.
 * Pensa → dati verso il nucleo.  Parla → dati dal nucleo verso l'umanoide.
 */

const vertex = /* glsl */ `
uniform float uTime;
uniform float uFlow;
uniform float uDir;
uniform float uPixelRatio;
uniform vec3 uP0;
uniform vec3 uP1;
uniform vec3 uP2;
uniform vec3 uColorA;
uniform vec3 uColorB;
attribute vec3 aSeed; // offset, spread, speed
varying vec3 vColor;
varying float vAlpha;
vec3 bez(float t){ float m = 1.0 - t; return m*m*uP0 + 2.0*m*t*uP1 + t*t*uP2; }
void main(){
  float s = fract(aSeed.x + uTime * (0.25 + aSeed.z * 0.35));
  float t = uDir > 0.0 ? s : 1.0 - s;
  vec3 p = bez(t);
  float taper = sin(t * 3.14159);
  float a = aSeed.y * 6.2831 + uTime * 2.0;
  p += vec3(0.0, sin(a), cos(a)) * taper * (0.05 + aSeed.y * 0.12);
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  gl_Position = projectionMatrix * mv;
  vColor = mix(uColorB, uColorA, t) * 1.6;
  vAlpha = uFlow * taper;
  gl_PointSize = (10.0 + aSeed.z * 10.0) * uPixelRatio / -mv.z;
}
`

export function DataStream({ from, to }: { from: THREE.Vector3; to: THREE.Vector3 }) {
  const geometry = useMemo(() => {
    const n = 700
    const seed = new Float32Array(n * 3)
    for (let i = 0; i < n * 3; i++) seed[i] = Math.random()
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(n * 3), 3))
    g.setAttribute('aSeed', new THREE.BufferAttribute(seed, 3))
    return g
  }, [])
  const flow = useRef(0)

  const mat = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: vertex,
        fragmentShader: SOFT_POINT_FRAG,
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        uniforms: {
          uTime: { value: 0 },
          uFlow: { value: 0 },
          uDir: { value: 1 },
          uPixelRatio: { value: Math.min(window.devicePixelRatio, 2) },
          uP0: { value: new THREE.Vector3() },
          uP1: { value: new THREE.Vector3() },
          uP2: { value: new THREE.Vector3() },
          uColorA: { value: new THREE.Color() },
          uColorB: { value: new THREE.Color() },
        },
      }),
    [],
  )

  useFrame((_, dt) => {
    const st = useStore.getState().state
    const agent = useStore.getState().current()
    const target = st === 'thinking' ? 1 : st === 'speaking' ? 0.35 + live.level * 0.5 : 0.04
    flow.current += (target - flow.current) * (1 - Math.exp(-dt * 3))
    const u = mat.uniforms
    u.uTime.value += dt
    u.uFlow.value = flow.current
    u.uDir.value = st === 'thinking' ? 1 : -1 // 1: umanoide → nucleo
    u.uP0.value.copy(from)
    u.uP2.value.copy(to)
    u.uP1.value.copy(from).lerp(to, 0.5).add(new THREE.Vector3(0.28, 0, 0.35))
    u.uColorA.value.set(agent?.accent ?? '#3ff0f7')
    u.uColorB.value.set(agent?.accent2 ?? '#1e7fe0')
  })

  return <points geometry={geometry} material={mat} frustumCulled={false} />
}
