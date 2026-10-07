import { Sparkles } from '@react-three/drei'
import { Canvas, useFrame } from '@react-three/fiber'
import { Bloom, EffectComposer, Noise, Vignette } from '@react-three/postprocessing'
import { useMemo } from 'react'
import * as THREE from 'three'
import { DataCore } from './DataCore'
import { DataStream } from './DataStream'
import { ParticleHumanoid } from './Humanoid'
import { live } from '../store'
import { Backdrop, Plexus } from './Plexus'
import { Skyline } from './Skyline'
import { City } from './City'

function Rig() {
  const look = useMemo(() => new THREE.Vector3(0, 2.12, 0), [])
  const close = typeof location !== 'undefined' && location.search.includes('view=close')
  useFrame(({ camera, pointer, size }, dt) => {
    if (close) {
      // anteprima ravvicinata del volto (?view=close)
      const side = location.search.includes('side')
      camera.position.set((side ? 1.35 : 0.0) + pointer.x * 0.3, 1.58, side ? 1.35 : 1.8)
      camera.lookAt(0, 1.45, 0)
      return
    }
    const k = 1 - Math.exp(-dt * 1.5)
    const aspect = size.width / size.height
    // su schermi verticali allontana la camera per far stare busto e nucleo
    const z = aspect > 1.1 ? 6 : 6 + (1.1 - aspect) * 6
    camera.position.x += (pointer.x * 0.35 - camera.position.x) * k
    camera.position.y += (1.15 + pointer.y * 0.15 - camera.position.y) * k
    camera.position.z += (z - camera.position.z) * k
    camera.lookAt(look)
  })
  return null
}

/** Inviluppo voce, decadimento impulsi e posizione del cuore sullo schermo (per le bolle email). */
function LiveDriver() {
  const v = useMemo(() => new THREE.Vector3(), [])
  useFrame(({ camera, size }, dt) => {
    live.level += (live.levelTarget - live.level) * (live.levelTarget > live.level ? 0.5 : 0.18)
    live.pulse *= 0.9
    live.mailFlash = Math.max(0, live.mailFlash - dt * 0.45)
    v.set(0, 0.38 + 0.62, 0.05).project(camera) // humanPos.y (LIFT) + ANCHORS.heart.y
    live.heartScreen.x = ((v.x + 1) / 2) * size.width
    live.heartScreen.y = ((1 - v.y) / 2) * size.height
  })
  return null
}

function World() {
  // composizione centrata: AXEL al centro, il suo "pensiero" (cuore dati) sospeso sopra la testa
  const LIFT = 0.38
  const humanPos: [number, number, number] = [0, LIFT, 0]
  const corePos: [number, number, number] = [0, 2.78 + LIFT, -0.7]
  const coreR = 0.4

  const from = useMemo(() => new THREE.Vector3(0, 2.02 + LIFT, 0.02), [])
  const to = useMemo(() => new THREE.Vector3(...corePos).add(new THREE.Vector3(0, -coreR * 0.9, 0)), []) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <Backdrop />
      <City hills={false} towers={false} />
      <Skyline core={corePos} coreRadius={coreR} />
      <Plexus hub={corePos} />
      <Sparkles count={22} scale={[14, 6, 6]} position={[0, 2, -4]} size={2.5} speed={0.2} color="#cfe6ff" opacity={0.5} />
      <ParticleHumanoid position={humanPos} />
      <DataCore position={corePos} radius={coreR} />
      <DataStream from={from} to={to} />
    </>
  )
}

export function Scene() {
  return (
    <Canvas
      dpr={[1, 2]}
      camera={{ position: [0, 1.15, 6], fov: 38, near: 0.1, far: 140 }}
      gl={{ antialias: false, powerPreference: 'high-performance' }}
    >
      <color attach="background" args={['#00102a']} />
      <LiveDriver />
      <World />
      <Rig />
      <EffectComposer multisampling={0}>
        <Bloom mipmapBlur intensity={1.15} luminanceThreshold={0.22} luminanceSmoothing={0.3} radius={0.75} />
        <Noise opacity={0.035} />
        <Vignette eskil={false} offset={0.2} darkness={0.75} />
      </EffectComposer>
    </Canvas>
  )
}
