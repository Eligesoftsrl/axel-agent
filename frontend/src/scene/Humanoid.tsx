import { useFrame } from '@react-three/fiber'
import { useMemo, useRef } from 'react'
import * as THREE from 'three'
import { live, useStore } from '../store'
import { SNOISE, SOFT_POINT_FRAG } from './glsl'
import { ANCHORS, buildHumanoidGeometry, buildHumanoidMesh, HEAD_STYLE } from './humanoidGeometry'
import { makeOccluder } from './occluder'
import { Visor } from './Visor'

const vertex = /* glsl */ `
${SNOISE}
uniform float uTime;
uniform float uLevel;   // apertura bocca 0..1
uniform float uJaw;     // ampiezza mandibola (0 con la fascia)
uniform float uThink;   // 0..1 elaborazione
uniform float uListen;  // 0..1 ascolto
uniform float uYaw;
uniform float uPitch;
uniform float uPixelRatio;
uniform float uReveal;  // 0..1 materializzazione iniziale
uniform vec3 uColorA;
uniform vec3 uColorB;
uniform vec3 uPivot;
attribute float aRand;
varying vec3 vColor;
varying float vAlpha;

vec3 rotHead(vec3 p, float w){
  vec3 q = p - uPivot;
  float cp = cos(uPitch*w), sp = sin(uPitch*w);
  q = vec3(q.x, cp*q.y - sp*q.z, sp*q.y + cp*q.z);
  float cy = cos(uYaw*w), sy = sin(uYaw*w);
  q = vec3(cy*q.x + sy*q.z, q.y, -sy*q.x + cy*q.z);
  return q + uPivot;
}

void main(){
  vec3 p = position;
  vec3 n = normal;

  // --- mandibola: i punti sotto la bocca scendono con la voce
  float jaw = smoothstep(1.325, 1.295, p.y) * smoothstep(1.0, 1.12, p.y)
            * smoothstep(-0.05, 0.2, p.z) * (1.0 - smoothstep(0.2, 0.34, abs(p.x)));
  p.y -= uLevel * uJaw * jaw;
  p.z -= uLevel * 0.012 * jaw;

  // --- respiro
  float body = 1.0 - smoothstep(0.9, 1.15, p.y);
  p += n * sin(uTime * 1.3) * 0.006 * body;

  // --- rumore superficiale (più forte quando "pensa")
  float nz = snoise(p * 3.2 + vec3(0.0, uTime * 0.35, 0.0));
  p += n * nz * (0.004 + uThink * 0.028 + uListen * 0.01);

  // --- onda di scansione verticale
  float scanY = mod(uTime * 0.55, 3.0) - 0.3;
  float scan = exp(-pow((p.y - scanY) * 14.0, 2.0));
  p += n * scan * 0.015;

  // --- materializzazione: i punti arrivano dal basso/disperso
  float rv = smoothstep(aRand * 0.6, aRand * 0.6 + 0.4, uReveal);
  p += n * (1.0 - rv) * (0.6 + aRand);

  // --- rotazione testa (peso progressivo sul collo)
  float hw = smoothstep(0.95, 1.22, position.y);
  p = rotHead(p, hw);
  n = rotHead(n + uPivot, hw) - uPivot;

  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  gl_Position = projectionMatrix * mv;

  vec3 vn = normalize(normalMatrix * n);
  vec3 vd = normalize(-mv.xyz);
  float facing = dot(vn, vd);
  float fres = 1.0 - abs(facing);

  float grad = clamp(position.y / 2.1 + nz * 0.15, 0.0, 1.0);
  vec3 col = mix(uColorB, uColorA, smoothstep(0.15, 0.85, grad));
  col = mix(col, uColorB, smoothstep(0.55, 1.0, fres) * 0.6);

  vec3 L = normalize(vec3(-0.45, 0.6, 0.75));
  float diff = max(dot(normalize(n), L), 0.0);
  float b = 0.12 + diff * 0.75 + pow(fres, 2.5) * 0.9 + scan * 1.4;
  b *= facing < 0.0 ? 0.28 : 1.0;                     // lato posteriore attenuato
  b += jaw * uLevel * 0.8;                            // bocca illuminata quando parla
  b += uThink * 0.25 * (0.5 + 0.5 * sin(uTime * 6.0 + position.y * 18.0));
  vColor = col * b;

  float bottom = smoothstep(0.02, 0.5, position.y);
  vAlpha = bottom * rv * (0.75 + 0.25 * aRand);

  gl_PointSize = (10.0 + aRand * 5.0 + scan * 8.0) * uPixelRatio / -mv.z;
}
`

export function ParticleHumanoid({ position = [0, 0, 0] as [number, number, number] }) {
  const geometry = useMemo(() => buildHumanoidGeometry(), [])
  const occGeo = useMemo(() => buildHumanoidMesh({ dy: 0.018, cols: 128 }), [])
  const occMat = useMemo(() => makeOccluder({ head: true, fadeBottom: true }), [])
  const agent = useStore((s) => s.current())
  const headRef = useRef<THREE.Group>(null)
  const eyeMat = useMemo(() => new THREE.MeshBasicMaterial({ toneMapped: false }), [])
  const heartRef = useRef<THREE.Mesh>(null)
  const heartGlowRef = useRef<THREE.Mesh>(null)
  const smooth = useRef({ think: 0, listen: 0, level: 0, yaw: 0, pitch: 0, reveal: 0 })

  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: vertex,
        fragmentShader: SOFT_POINT_FRAG,
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        uniforms: {
          uTime: { value: 0 },
          uLevel: { value: 0 },
          uJaw: { value: HEAD_STYLE === 'visor' ? 0 : 0.055 },
          uThink: { value: 0 },
          uListen: { value: 0 },
          uYaw: { value: 0 },
          uPitch: { value: 0 },
          uReveal: { value: 0 },
          uPixelRatio: { value: Math.min(window.devicePixelRatio, 2) },
          uColorA: { value: new THREE.Color('#3ff0f7') },
          uColorB: { value: new THREE.Color('#1e7fe0') },
          uPivot: { value: ANCHORS.neckPivot.clone() },
        },
      }),
    [],
  )

  useFrame(({ clock, pointer }, dt) => {
    const st = useStore.getState().state
    const s = smooth.current
    const k = 1 - Math.exp(-dt * 6)
    s.think += ((st === 'thinking' ? 1 : 0) - s.think) * k
    s.listen += ((st === 'listening' ? 1 : 0) - s.listen) * k
    s.level = live.level
    s.reveal = Math.min(1, s.reveal + dt * 0.35)

    // sguardo: verso il cuore dati quando pensa, verso l'utente altrimenti
    const t = clock.elapsedTime
    const yawT = st === 'thinking' ? Math.sin(t * 0.6) * 0.08 : pointer.x * 0.35 + Math.sin(t * 0.4) * 0.05
    const pitchT = st === 'thinking' ? -0.32 : -pointer.y * 0.18 + Math.sin(t * 0.7) * 0.02
    s.yaw += (yawT - s.yaw) * (1 - Math.exp(-dt * 2.5))
    s.pitch += (pitchT - s.pitch) * (1 - Math.exp(-dt * 2.5))

    const u = material.uniforms
    u.uTime.value = t
    u.uLevel.value = s.level
    u.uThink.value = s.think
    u.uListen.value = s.listen
    u.uYaw.value = s.yaw
    u.uPitch.value = s.pitch
    occMat.uniforms.uYaw.value = s.yaw
    occMat.uniforms.uPitch.value = s.pitch
    u.uReveal.value = s.reveal
    u.uColorA.value.lerp(new THREE.Color(agent?.accent ?? '#3ff0f7'), 0.05)
    u.uColorB.value.lerp(new THREE.Color(agent?.accent2 ?? '#1e7fe0'), 0.05)

    if (headRef.current) {
      headRef.current.rotation.set(s.pitch, s.yaw, 0, 'YXZ')
    }
    {
      const blink = Math.sin(t * 0.9) > 0.995 ? 0.1 : 1
      const glow = (HEAD_STYLE === 'visor' ? 1.6 : 1.1) * (1 + s.level * 1.6 + s.think * 1.0 + live.pulse * 0.4) * blink * s.reveal
      eyeMat.color.copy(u.uColorA.value).multiplyScalar(glow)
    }
    if (heartRef.current) {
      const beat = Math.pow(Math.max(0, Math.sin(t * (st === 'thinking' ? 7 : 3.2))), 8)
      heartRef.current.scale.setScalar(0.07 + beat * 0.025 + s.level * 0.03 + live.mailFlash * 0.06)
      heartRef.current.rotation.y += dt * 0.8
      heartRef.current.rotation.x += dt * 0.5
      ;(heartRef.current.material as THREE.MeshBasicMaterial).color
        .copy(u.uColorB.value)
        .multiplyScalar(1.2 + beat * 2 + s.think + live.mailFlash * 5)
      if (heartGlowRef.current) {
        heartGlowRef.current.scale.setScalar(0.05 + beat * 0.035 + s.level * 0.03 + live.mailFlash * 0.22)
        ;(heartGlowRef.current.material as THREE.MeshBasicMaterial).color
          .copy(u.uColorA.value)
          .multiplyScalar(0.6 + beat * 1.4 + s.think * 0.6 + live.mailFlash * 3)
      }
    }
  })

  const pv = ANCHORS.neckPivot
  return (
    <group position={position}>
      <mesh geometry={occGeo} material={occMat} renderOrder={-1.5} />
      <points geometry={geometry} material={material} frustumCulled={false} />
      {/* occhi: seguono la stessa rotazione della testa */}
      <group position={pv} ref={headRef}>
        {HEAD_STYLE === 'visor' ? (
          <Visor material={eyeMat} />
        ) : (
          [ANCHORS.eyeL, ANCHORS.eyeR].map((e, i) => (
            <mesh key={i} position={[e.x - pv.x, e.y - pv.y, e.z - pv.z]} material={eyeMat}>
              <sphereGeometry args={[0.015, 16, 16]} />
            </mesh>
          ))
        )}
      </group>
      {/* nucleo nel petto */}
      {/* cuore: visibile attraverso la sagoma (depthTest off), alone + nucleo a reticolo */}
      <mesh ref={heartRef} position={ANCHORS.heart} renderOrder={3}>
        <icosahedronGeometry args={[1, 1]} />
        <meshBasicMaterial wireframe toneMapped={false} transparent opacity={0.95} depthTest={false} depthWrite={false} />
      </mesh>
      <mesh ref={heartGlowRef} position={ANCHORS.heart} renderOrder={3}>
        <sphereGeometry args={[1, 24, 16]} />
        <meshBasicMaterial toneMapped={false} transparent opacity={0.35} depthTest={false} depthWrite={false} blending={THREE.AdditiveBlending} />
      </mesh>
    </group>
  )
}
