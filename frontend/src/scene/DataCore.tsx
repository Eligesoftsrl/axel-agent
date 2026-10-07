import { Billboard } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import { useMemo, useRef } from 'react'
import * as THREE from 'three'
import { live, useStore } from '../store'
import { SNOISE, SOFT_POINT_FRAG } from './glsl'

/** Il "cuore dati": sfera di punti a righe di latitudine, deformata da rumore. */

const vertex = /* glsl */ `
${SNOISE}
uniform float uTime;
uniform float uEnergy;
uniform float uPixelRatio;
uniform vec3 uColorA;
uniform vec3 uColorB;
attribute float aRand;
varying vec3 vColor;
varying float vAlpha;
void main(){
  vec3 n = normalize(position);
  float t = uTime;
  float d = snoise(n * 1.4 + vec3(t * 0.25, t * 0.18, 0.0)) * (0.16 + uEnergy * 0.22)
          + snoise(n * 3.2 - vec3(0.0, t * 0.5, t * 0.3)) * (0.04 + uEnergy * 0.08);
  vec3 p = n * (1.0 + d);
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  gl_Position = projectionMatrix * mv;

  vec3 vn = normalize(normalMatrix * n);
  float facing = dot(vn, normalize(-mv.xyz));
  float fres = 1.0 - abs(facing);
  vec3 col = mix(uColorA, uColorB, smoothstep(-0.05, 0.22, d) * 0.85 + fres * 0.15);
  float b = 0.4 + smoothstep(-0.1, 0.25, d) * 1.1 + pow(fres, 3.0) * 0.7 + uEnergy * 0.4;
  b *= facing < 0.0 ? 0.35 : 1.0;
  vColor = col * b;
  vAlpha = 0.85;
  gl_PointSize = (14.0 + aRand * 4.0) * (0.75 + d) * uPixelRatio / -mv.z;
}
`

const glowFrag = /* glsl */ `
uniform vec3 uColor;
uniform float uEnergy;
varying vec2 vUv;
void main(){
  float d = length(vUv - 0.5) * 2.0;
  float a = pow(max(0.0, 1.0 - d), 3.0) * (0.25 + uEnergy * 0.35);
  gl_FragColor = vec4(uColor * a, a);
}
`
const glowVert = /* glsl */ `
varying vec2 vUv;
void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }
`

function buildSphere(rows = 88) {
  const pos: number[] = []
  const rnd: number[] = []
  for (let i = 1; i < rows; i++) {
    const lat = (i / rows) * Math.PI
    const ring = Math.sin(lat)
    const count = Math.max(4, Math.round(ring * rows * 2))
    const off = Math.random() * Math.PI * 2
    for (let j = 0; j < count; j++) {
      const lon = (j / count) * Math.PI * 2 + off
      pos.push(Math.cos(lon) * ring, Math.cos(lat), Math.sin(lon) * ring)
      rnd.push(Math.random())
    }
  }
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  g.setAttribute('aRand', new THREE.Float32BufferAttribute(rnd, 1))
  return g
}

export function DataCore({ position = [0, 0, 0] as [number, number, number], radius = 0.6 }) {
  const geometry = useMemo(() => buildSphere(), [])
  const agent = useStore((s) => s.current())
  const group = useRef<THREE.Group>(null)
  const energy = useRef(0)

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
          uEnergy: { value: 0 },
          uPixelRatio: { value: Math.min(window.devicePixelRatio, 2) },
          uColorA: { value: new THREE.Color('#3ff0f7') },
          uColorB: { value: new THREE.Color('#1e7fe0') },
        },
      }),
    [],
  )
  const glow = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: glowVert,
        fragmentShader: glowFrag,
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        uniforms: { uColor: { value: new THREE.Color('#2a6bff') }, uEnergy: { value: 0 } },
      }),
    [],
  )

  useFrame(({ clock }, dt) => {
    const st = useStore.getState().state
    const target =
      st === 'thinking' ? 1 : st === 'speaking' ? 0.45 + live.level * 0.5 : st === 'listening' ? 0.2 + live.mic : 0
    energy.current += (target + live.pulse * 0.3 - energy.current) * (1 - Math.exp(-dt * 4))
    // il tempo accelera quando il nucleo lavora
    mat.uniforms.uTime.value += dt * (0.6 + energy.current * 1.6)
    mat.uniforms.uEnergy.value = energy.current
    mat.uniforms.uColorA.value.lerp(new THREE.Color(agent?.accent ?? '#3ff0f7'), 0.05)
    mat.uniforms.uColorB.value.lerp(new THREE.Color(agent?.accent2 ?? '#1e7fe0'), 0.05)
    glow.uniforms.uEnergy.value = energy.current
    glow.uniforms.uColor.value.copy(mat.uniforms.uColorA.value).lerp(mat.uniforms.uColorB.value, 0.5)
    if (group.current) {
      group.current.rotation.y += dt * (0.12 + energy.current * 0.5)
      group.current.position.y = Math.sin(clock.elapsedTime * 0.8) * 0.06
    }
  })

  return (
    <group position={position}>
      <Billboard>
        <mesh material={glow} scale={radius * 4.2}>
          <planeGeometry />
        </mesh>
      </Billboard>
      <group ref={group} scale={radius}>
        <points geometry={geometry} material={mat} frustumCulled={false} />
      </group>
    </group>
  )
}
