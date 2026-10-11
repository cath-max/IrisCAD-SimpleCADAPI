// Renders a flat-shaded render mesh (see simplecadapi.mesh_export.RenderMesh /
// webharness.render_mesh) from N named camera angles using Three.js, inside
// an OffscreenCanvas.
//
// Architecture note:
// This repo's Worker is self-contained and DOM-free (it serves both a page
// UI in playground.html and fully headless puppeteer-driven tests), so
// there's no "must be page-visible" constraint here - rendering stays
// Worker-side via OffscreenCanvas + WebGL2, avoiding a new main-thread
// round trip for every render request. 
//
// Coordinate convention: SimpleCADAPI (and OCCT) are Z-up. The camera's up vector is set to Z
// so the exported mesh buffers can be used completely unrotated.

import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.185.1/build/three.module.js";

// Mirrors operations.py's view-preset naming convention (the same named
// views used throughout this codebase: iso/top/bottom/front/back/left/
// right/front_right/...), reimplemented as direction vectors here since
// Three.js's camera is parameterized by a direction vector rather than an
// elevation/azimuth pair. "auto" is intentionally not included: a repo-wide
// grep found no caller ever passes views=["auto"].
const VIEW_ANGLES_DEG = {
  iso: [25, 35],
  isometric: [25, 35],
  top: [90, 0],
  bottom: [-90, 0],
  front: [0, -90],
  back: [0, 90],
  left: [0, 180],
  right: [0, 0],
  front_right: [20, -45],
  front_left: [20, 135],
  rear_right: [20, 45],
  rear_left: [20, -135],
};

function resolveViewDirection(view) {
  const angles = VIEW_ANGLES_DEG[view];
  if (!angles) {
    throw new Error(`Unsupported view preset: ${view}`);
  }
  const [elevDeg, azimDeg] = angles;
  const elev = (elevDeg * Math.PI) / 180;
  const azim = (azimDeg * Math.PI) / 180;
  return new THREE.Vector3(
    Math.cos(elev) * Math.cos(azim),
    Math.cos(elev) * Math.sin(azim),
    Math.sin(elev),
  );
}

// Axis colors mirror this codebase's established axis convention
// (X/Y/Z ~ red/green/blue-ish).
const AXIS_SPECS = [
  { dir: new THREE.Vector3(1, 0, 0), color: 0xff5959 },
  { dir: new THREE.Vector3(0, 1, 0), color: 0x59ff8c },
  { dir: new THREE.Vector3(0, 0, 1), color: 0x73a6ff },
];

// Real edges, drawn cheaply and correctly thanks to a real z-buffer:
// THREE.EdgesGeometry finds edges where the angle between two adjacent
// triangles' face normals exceeds this threshold, and the resulting
// LineSegments render in the same WebGL scene/depth buffer as the shaded
// fill, so hidden edges are just... hidden, automatically, with no manual
// occlusion/silhouette-detection logic required. Verified against a
// bracket-with-hole-and-boss model (flat top face with cutouts, previously
// a source of dense phantom diagonal lines under a hand-rolled matplotlib
// edge detector) - EdgesGeometry does not reproduce that artifact.
const EDGE_ANGLE_THRESHOLD_DEG = 15;
const EDGE_COLOR = 0x1a1d24;

function buildGeometry(meshBuffers) {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(meshBuffers.positions, 3));
  geometry.setAttribute("normal", new THREE.BufferAttribute(meshBuffers.normals, 3));
  geometry.setAttribute("color", new THREE.BufferAttribute(meshBuffers.colors, 3));
  return geometry;
}

function buildScene(meshBuffers, { showAxes = true, showEdges = true } = {}) {
  const scene = new THREE.Scene();

  const geometry = buildGeometry(meshBuffers);
  const material = new THREE.MeshStandardMaterial({
    vertexColors: true,
    metalness: 0.1,
    roughness: 0.8,
  });
  scene.add(new THREE.Mesh(geometry, material));

  if (showEdges) {
    const edgesGeometry = new THREE.EdgesGeometry(geometry, EDGE_ANGLE_THRESHOLD_DEG);
    const edgeMaterial = new THREE.LineBasicMaterial({ color: EDGE_COLOR });
    scene.add(new THREE.LineSegments(edgesGeometry, edgeMaterial));
  }

  scene.add(new THREE.AmbientLight(0xffffff, 0.6));
  const dirLight = new THREE.DirectionalLight(0xffffff, 1.0);
  scene.add(dirLight);

  const min = new THREE.Vector3(...meshBuffers.bounds.min);
  const max = new THREE.Vector3(...meshBuffers.bounds.max);
  const center = min.clone().add(max).multiplyScalar(0.5);
  const size = max.clone().sub(min);
  const diagonal = Math.max(size.length(), 1e-6);
  const halfExtent = (diagonal / 2) * 1.1; // 10% padding, matches CADAM's framing

  if (showAxes) {
    const axisLength = diagonal * 0.55;
    for (const { dir, color } of AXIS_SPECS) {
      const origin = new THREE.Vector3(
        Math.min(0, min.x),
        Math.min(0, min.y),
        Math.min(0, min.z),
      );
      scene.add(new THREE.ArrowHelper(dir, origin, axisLength, color, axisLength * 0.2, axisLength * 0.1));
    }
  }

  return { scene, dirLight, center, diagonal, halfExtent };
}

/**
 * @param {Object} meshBuffers - result of PyodideEngine#renderMeshBuffers
 *   (must have .positions/.normals/.colors Float32Array views and .bounds)
 * @param {string[]} views - named view presets, e.g. ["iso","front","right","top"]
 * @param {Object} [opts]
 * @param {number} [opts.imageSize] - square render size in px, default 512
 * @param {boolean} [opts.showAxes] - draw XYZ axis arrows, default true
 * @param {boolean} [opts.showEdges] - overlay real (depth-tested) hard-edge
 *   lines via THREE.EdgesGeometry, default true
 * @returns {Promise<{view: string, bytes: Uint8Array}[]>} matches
 *   compositeGrid's existing input contract
 */
export async function renderViews(meshBuffers, views, opts = {}) {
  const imageSize = opts.imageSize ?? 512;
  const { scene, dirLight, center, diagonal, halfExtent } = buildScene(meshBuffers, opts);

  const camera = new THREE.OrthographicCamera(
    -halfExtent,
    halfExtent,
    halfExtent,
    -halfExtent,
    0.1,
    diagonal * 10,
  );
  camera.up.set(0, 0, 1); // SimpleCADAPI/OCCT are Z-up; see module-level note

  const canvas = new OffscreenCanvas(imageSize, imageSize);
  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: true,
    alpha: true,
    preserveDrawingBuffer: true, // required to read pixels back after render
  });
  renderer.setPixelRatio(1);
  renderer.setSize(imageSize, imageSize, false);

  const results = [];
  try {
    for (const view of views) {
      const dir = resolveViewDirection(view);
      camera.position.copy(center).addScaledVector(dir, diagonal * 2);
      camera.lookAt(center);
      dirLight.position.copy(camera.position);
      camera.updateProjectionMatrix();

      renderer.render(scene, camera);
      const blob = await canvas.convertToBlob({ type: "image/png" });
      const bytes = new Uint8Array(await blob.arrayBuffer());
      results.push({ view, bytes });
    }
  } finally {
    renderer.dispose();
    scene.traverse((obj) => {
      if (obj.geometry) obj.geometry.dispose();
      if (obj.material) obj.material.dispose();
    });
  }

  return results;
}
