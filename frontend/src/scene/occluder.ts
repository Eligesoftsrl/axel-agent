import * as THREE from 'three'

/**
 * Sagoma scura che scrive la profondità: la città (additiva) passa DIETRO ad AXEL e al
 * cuore dati invece di sommarsi sopra. Va disegnata prima della città (renderOrder -1.5).
 * Con `head` ruota la testa come lo shader a particelle.
 */
export function makeOccluder(opts: { head?: boolean; fadeBottom?: boolean } = {}) {
  return new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: true,
    uniforms: {
      uYaw: { value: 0 },
      uPitch: { value: 0 },
      uPivot: { value: new THREE.Vector3(0, 1.1, -0.02) },
      uColor: { value: new THREE.Color('#03204a') },
    },
    vertexShader: /* glsl */ `
      uniform float uYaw; uniform float uPitch; uniform vec3 uPivot;
      varying float vY;
      vec3 rotHead(vec3 p, float w){
        vec3 q = p - uPivot;
        float cp = cos(uPitch*w), sp = sin(uPitch*w);
        q = vec3(q.x, cp*q.y - sp*q.z, sp*q.y + cp*q.z);
        float cy = cos(uYaw*w), sy = sin(uYaw*w);
        q = vec3(cy*q.x + sy*q.z, q.y, -sy*q.x + cy*q.z);
        return q + uPivot;
      }
      void main(){
        vec3 p = position - normal * 0.045;   // leggermente dentro la nuvola di punti
        ${opts.head ? 'p = rotHead(p, smoothstep(0.95, 1.22, position.y));' : ''}
        vY = position.y;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
      }`,
    fragmentShader: /* glsl */ `
      uniform vec3 uColor;
      varying float vY;
      void main(){
        float a = ${opts.fadeBottom ? 'smoothstep(0.2, 0.6, vY) * 0.62' : '0.6'};
        if (a < 0.02) discard;
        gl_FragColor = vec4(uColor, a);
      }`,
  })
}
