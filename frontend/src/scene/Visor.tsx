import { useMemo } from 'react'
import * as THREE from 'three'
import { ANCHORS, visorCurve } from './humanoidGeometry'

/** Fascia luminosa al posto degli occhi. Va montata nel gruppo testa (origine = pivot del collo). */
export function Visor({ material }: { material: THREE.Material }) {
  const geometry = useMemo(() => {
    const g = new THREE.TubeGeometry(visorCurve(), 80, 0.0052, 8, false)
    g.translate(0, -1.567, 0).scale(1, 1.5, 1).translate(0, 1.567, 0) // più alta che spessa
    g.translate(-ANCHORS.neckPivot.x, -ANCHORS.neckPivot.y, -ANCHORS.neckPivot.z)
    return g
  }, [])
  return <mesh geometry={geometry} material={material} />
}
