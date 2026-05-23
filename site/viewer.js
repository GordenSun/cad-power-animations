/**
 * Minimal three.js viewer that re-implements just enough of the CAD Explorer
 * STEP module runtime to drive the .step.js sidecars statically.
 *
 * Loads:
 *   - the colocated `.<name>.step.glb` (STEP_topology extension preserves the
 *     `o1.N` occurrence hierarchy as named scene nodes);
 *   - the colocated `.<name>.step.js` sidecar (ES module exporting
 *     `{ manifest, update(ctx) }`);
 *
 * Then per-frame:
 *   - resets every occurrence-group transform to identity;
 *   - calls `sidecar.update({ params, effects, time })`;
 *   - applies the accumulated effect matrix / color on each occurrence group.
 */

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";

// ---------------------------------------------------------------------------
// Model registry
// ---------------------------------------------------------------------------
const MODELS = {
  planetary_gearbox: {
    title: "Planetary gearbox",
    glb: "models/planetary_gearbox/.planetary_gearbox.step.glb",
    sidecar: "models/planetary_gearbox/.planetary_gearbox.step.js",
    explainer:
      "Sun (yellow, input) drives three planet gears (orange, green, pink). The planets mesh with the fixed ring (cyan), so they roll along the ring while the carrier (violet, output) revolves slowly around the sun — a 5:1 reduction with Zs=12, Zp=18, Zr=48.",
    cameraStart: { distance: 850, azimuth: -55, elevation: 18 },
    cameraTarget: [0, 0, 0],
    animationDurationSec: 6,
    primaryParam: "drive",
    primaryRange: [0, 1080]
  },
  drone: {
    title: "Quadcopter — hover + spin",
    glb: "models/drone/.drone.step.glb",
    sidecar: "models/drone/.drone.step.js",
    explainer:
      "Four propellers spin at high rpm (FL & RR clockwise, FR & RL counter-clockwise, so the yaw torques cancel). The body bobs up and down in hover and gently pitches fore/aft as if the rider is nudging the stick — classic quadcopter X-configuration.",
    cameraStart: { distance: 1900, azimuth: 35, elevation: 22 },
    cameraTarget: [0, 0, 220],
    animationDurationSec: 5,
    primaryParam: "drive",
    primaryRange: [0, 360]
  },
  geneva: {
    title: "Geneva drive — intermittent motion",
    glb: "models/geneva/.geneva.step.glb",
    sidecar: "models/geneva/.geneva.step.js",
    explainer:
      "Driver (orange disc + yellow pin + red lock plate) rotates continuously. Every revolution the pin engages one slot of the cyan Maltese cross and pushes it through exactly 90°; the lock plate holds the cross still in between. Classic film-projector / index-table mechanism.",
    cameraStart: { distance: 800, azimuth: -50, elevation: 22 },
    cameraTarget: [80, 0, 0],
    animationDurationSec: 8,
    primaryParam: "drive",
    primaryRange: [0, 1440]
  },
  bicycle: {
    title: "Bicycle — forward motion",
    glb: "models/bicycle/.bicycle.step.glb",
    sidecar: "models/bicycle/.bicycle.step.js",
    explainer:
      "Pedal pushes crank → chainring rotates → chain pulls the rear cog → cog spins the rear wheel → rolling friction translates the bike forward, and the front wheel rolls along. Toggle 'Roll forward' on to see the bike actually slide along +X (camera follows the frame).",
    cameraStart: { distance: 3200, azimuth: 55, elevation: 18 },
    cameraTarget: [0, 0, 500],
    animationDurationSec: 4,
    primaryParam: "cadence",
    primaryRange: [0, 720],
    chaseX: "o1.1"  // frame - only kicks in when Roll forward is on
  },
  robot_arm: {
    title: "Robotic arm — 5-DOF forward kinematics",
    glb: "models/robot_arm/.robot_arm.step.glb",
    sidecar: "models/robot_arm/.robot_arm.step.js",
    explainer:
      "Five revolute joints — base yaw, shoulder, elbow, wrist pitch, tool roll — plus a parallel-jaw gripper that opens and closes. The trajectory parameter sweeps every axis through a smooth choreography; flip 'Manual joint control' to drive each joint individually.",
    cameraStart: { distance: 1700, azimuth: 40, elevation: 18 },
    cameraTarget: [250, 0, 250],
    animationDurationSec: 8,
    primaryParam: "drive",
    primaryRange: [0, 360]
  },
  solar_system: {
    title: "Solar system — 8 planets, moons and a tilted Saturn",
    glb: "models/solar_system/.solar_system.step.glb",
    sidecar: "models/solar_system/.solar_system.step.js",
    explainer:
      "All eight planets orbit the Sun at Keplerian speed ratios (gently log-compressed for the outer giants). Earth's Moon and Jupiter's four Galilean moons — Io, Europa, Ganymede, Callisto — ride their parent planet's orbital frame. Saturn keeps its real 26.7° axial tilt; a thin asteroid belt sits between Mars and Jupiter; the Sun gets a corona pulse picked up by the bloom pass.",
    cameraStart: { distance: 3200, azimuth: 55, elevation: 35 },
    cameraTarget: [0, 0, 0],
    animationDurationSec: 16,
    primaryParam: "time",
    primaryRange: [0, 360],
    starfield: true,
    // Bloom only the truly bright pixels (the Sun's high emissive); the
    // starfield and reflected planet faces stay crisp.
    bloom: { strength: 0.55, radius: 0.4, threshold: 0.92 },
    // Default fit multiplier is 1.4 × bbox-diagonal; the solar system
    // shrinks it to ~0.93 (= 1.4 / 1.5) so the whole system shows up
    // about 50% bigger on first load.
    cameraFitMultiplier: 0.93
  }
};

const urlParams = new URLSearchParams(location.search);
const modelKey = MODELS[urlParams.get("model")] ? urlParams.get("model") : "planetary_gearbox";
const model = MODELS[modelKey];

document.getElementById("model-title").textContent = model.title;
document.title = model.title;
document.getElementById("explainer").textContent = model.explainer;

const statusEl = document.getElementById("status");
function setStatus(text) { statusEl.textContent = text; }

// ---------------------------------------------------------------------------
// three.js scene
// ---------------------------------------------------------------------------
const canvas = document.getElementById("render");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;

const scene = new THREE.Scene();
// Solar system gets a deep-space black so the starfield + bloom pop. Every
// other model keeps the brighter navy so coloured parts have contrast.
scene.background = new THREE.Color(model.starfield ? 0x05060a : 0x1e3a8a);

const camera = new THREE.PerspectiveCamera(40, 1, 1, 60000);
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
controls.dampingFactor = 0.08;

// Lighting
scene.add(new THREE.AmbientLight(0xffffff, 0.55));
const key = new THREE.DirectionalLight(0xffffff, 0.9);
key.position.set(2500, 4000, 6000);
scene.add(key);
const fill = new THREE.DirectionalLight(0x60a5fa, 0.35);
fill.position.set(-3000, -2000, 2500);
scene.add(fill);

// Floor / shadow plate (CAD coord: Z is up, XY is ground). Created up-front
// but only added to the scene later when the model registry opts in via
// `showGround: true`. Free-floating models (gears, drone, planets) get a
// clean background instead of a misleading ground plane that they would
// otherwise visually clip through.
const ground = new THREE.Group();
{
  const r = 16000;
  const geo = new THREE.PlaneGeometry(r, r, 1, 1);
  const mat = new THREE.MeshStandardMaterial({
    color: 0x312e81,         // indigo, contrasts with bright parts
    roughness: 0.85,
    metalness: 0.1
  });
  const floor = new THREE.Mesh(geo, mat);
  floor.position.set(0, 0, -1);
  ground.add(floor);

  const grid = new THREE.GridHelper(r, 40, 0x60a5fa, 0x4338ca);
  grid.rotation.x = Math.PI / 2;
  grid.position.z = 0;
  ground.add(grid);
}
if (model.showGround) {
  scene.add(ground);
}

// Optional starfield: a sparse sphere of points way outside the scene so
// distant stars stay put no matter where the user pans/zooms.
if (model.starfield) {
  // Lots of tiny, sub-1-pixel-ish stars with a realistic temperature mix.
  // Brightness is kept well below the bloom threshold so they stay crisp
  // points rather than fluffy blobs.
  const STAR_COUNT = 3500;
  const STAR_RADIUS = 32000;
  const positions = new Float32Array(STAR_COUNT * 3);
  const colors = new Float32Array(STAR_COUNT * 3);
  for (let i = 0; i < STAR_COUNT; i += 1) {
    const u = Math.random() * 2 - 1;
    const theta = Math.random() * Math.PI * 2;
    const s = Math.sqrt(1 - u * u);
    positions[i * 3]     = STAR_RADIUS * s * Math.cos(theta);
    positions[i * 3 + 1] = STAR_RADIUS * s * Math.sin(theta);
    positions[i * 3 + 2] = STAR_RADIUS * u;
    // Vary apparent brightness; most stars are dim, a few are noticeably bright.
    const base = 0.35 + 0.45 * Math.pow(Math.random(), 3);  // skew toward dim
    const tint = Math.random();
    let r = base, g = base, b = base;
    if (tint < 0.18) { b *= 1.15; g *= 1.05; }                    // blue-white
    else if (tint > 0.85) { r *= 1.15; g *= 0.95; b *= 0.7; }     // warm orange
    colors[i * 3] = Math.min(r, 0.85);
    colors[i * 3 + 1] = Math.min(g, 0.85);
    colors[i * 3 + 2] = Math.min(b, 0.85);
  }
  const starGeo = new THREE.BufferGeometry();
  starGeo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  starGeo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  const starMat = new THREE.PointsMaterial({
    size: 1.2,
    sizeAttenuation: false,
    vertexColors: true,
    transparent: true,
    opacity: 0.85,
    depthWrite: false
  });
  scene.add(new THREE.Points(starGeo, starMat));
}

// Set initial camera from spherical coords in CAD space (Z up)
function setCameraFromSpherical(distance, azimuthDeg, elevationDeg, target) {
  const az = azimuthDeg * Math.PI / 180;
  const el = elevationDeg * Math.PI / 180;
  const tx = target[0], ty = target[1], tz = target[2];
  const cx = tx + distance * Math.cos(el) * Math.cos(az);
  const cy = ty + distance * Math.cos(el) * Math.sin(az);
  const cz = tz + distance * Math.sin(el);
  camera.up.set(0, 0, 1);            // Z up
  camera.position.set(cx, cy, cz);
  controls.target.set(tx, ty, tz);
  controls.update();
}
setCameraFromSpherical(
  model.cameraStart.distance,
  model.cameraStart.azimuth,
  model.cameraStart.elevation,
  model.cameraTarget
);

// Optional bloom post-processing (for the solar system sun glow).
let composer = null;
let bloomPass = null;
if (model.bloom) {
  const b = model.bloom;
  composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));
  bloomPass = new UnrealBloomPass(
    new THREE.Vector2(1, 1),
    Number(b.strength)  ?? 1.2,
    Number(b.radius)    ?? 0.6,
    Number(b.threshold) ?? 0.5
  );
  composer.addPass(bloomPass);
  composer.addPass(new OutputPass());
}

function resize() {
  const host = canvas.parentElement;
  const w = host.clientWidth;
  const h = host.clientHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h || 1;
  camera.updateProjectionMatrix();
  if (composer) composer.setSize(w, h);
  if (bloomPass) bloomPass.setSize(w, h);
}
window.addEventListener("resize", resize);
resize();

// ---------------------------------------------------------------------------
// Load GLB + sidecar
// ---------------------------------------------------------------------------
setStatus("Loading model…");

// Captured after the auto-fit step below; the "Reset view" button restores
// this pose without recomputing through cameraStart math.
let initialCameraPose = null;

const loader = new GLTFLoader();
const gltf = await new Promise((res, rej) => {
  loader.load(model.glb, res, undefined, rej);
});
setStatus("Loading sidecar…");
const sidecarUrl = new URL(model.sidecar, location.href).href;
const sidecarMod = await import(/* @vite-ignore */ sidecarUrl);
const sidecar = sidecarMod.default || sidecarMod;
const manifest = sidecar.manifest || {};
const features = manifest.features || {};
const paramDefs = manifest.parameters || {};

setStatus("Building scene…");

// STEP_topology GLB stores in CAD coords (Z up, mm). Scale to mm directly:
// gltf.scene root may be in meters (default GLB unit). Multiply by 1000 to
// convert to mm matching the sidecar coordinate convention.
const root = gltf.scene;
root.scale.setScalar(1000);
root.updateMatrixWorld(true);
scene.add(root);

// ---------------------------------------------------------------------------
// Collect occurrence wrappers.
// The viewer's STEP topology stores each `o1.N` occurrence as a named node
// (group or mesh). We treat each top-level `o1.N` (i.e. immediate children
// of `o1`) as the unit of motion - that is what the sidecar references.
// To safely set its world transform, we reparent it to a dedicated scene
// child whose matrix can be overwritten each frame without disturbing
// the GLB-baked local transforms underneath.
// ---------------------------------------------------------------------------
const occurrenceRegex = /^o\d+(?:\.\d+)*$/;

function getOccurrenceId(node) {
  const raw = String(node.userData?.cadOccurrenceId || node.name || "").trim();
  return occurrenceRegex.test(raw) ? raw : "";
}

// Build map: occurrenceId -> node
const occurrenceNodes = new Map();
root.traverse(node => {
  const occ = getOccurrenceId(node);
  if (!occ) return;
  if (!occurrenceNodes.has(occ)) {
    occurrenceNodes.set(occ, node);
  }
});

// Wrapper map: occurrenceId -> THREE.Group at scene root
const occurrenceWrappers = new Map();

// Top-level occurrence ids are the immediate children of o1 (i.e. depth 2).
for (const [occ, node] of occurrenceNodes) {
  const parts = occ.split(".");
  if (parts.length !== 2) continue; // only top-level, e.g. o1.5
  // Bake the world matrix of this node into the node itself, detach, and
  // reparent to a fresh wrapper at scene root.
  node.updateWorldMatrix(true, false);
  const worldMatrix = node.matrixWorld.clone();
  const wrapper = new THREE.Group();
  wrapper.name = `wrap_${occ}`;
  wrapper.userData.occurrenceId = occ;
  scene.add(wrapper);

  // Detach `node` from its old parent and reparent into wrapper.
  // After reparenting, set the node's local matrix to the baked world so it
  // appears at the same place in world space (since wrapper starts at I).
  const pos = new THREE.Vector3();
  const quat = new THREE.Quaternion();
  const scl = new THREE.Vector3();
  worldMatrix.decompose(pos, quat, scl);
  wrapper.add(node);
  node.position.copy(pos);
  node.quaternion.copy(quat);
  node.scale.copy(scl);

  // Clone every material so it is unique per wrapper (the GLB shares one
  // grey material across every part). Stash the base color so we can reset
  // it each frame before re-applying sidecar styles.
  node.traverse(child => {
    if (!child.isMesh || !child.material) return;
    if (Array.isArray(child.material)) {
      child.material = child.material.map(m => m.clone());
    } else {
      child.material = child.material.clone();
    }
    const mats = Array.isArray(child.material) ? child.material : [child.material];
    for (const m of mats) {
      m.userData._cad_baseColor = m.color ? m.color.getHex() : 0xc7d2fe;
      m.userData._cad_baseEmissive = m.emissive ? m.emissive.getHex() : 0x000000;
      m.userData._cad_baseEmissiveIntensity = m.emissiveIntensity ?? 0;
    }
  });

  occurrenceWrappers.set(occ, wrapper);
}

// Center the model and fit the camera based ONLY on the loaded CAD parts
// (not the floor/grid helpers which are huge). Leave generous breathing
// room so parts that swing further during animation (robot arm, planets,
// piston etc) still stay inside the frame.
{
  const box = new THREE.Box3();
  for (const wrapper of occurrenceWrappers.values()) {
    box.expandByObject(wrapper);
  }
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  if (Number.isFinite(size.length()) && size.length() > 0) {
    controls.target.copy(center);
    const diag = size.length();
    const dir = new THREE.Vector3().subVectors(camera.position, controls.target).normalize();
    const fit = Number(model.cameraFitMultiplier) || 1.4;
    camera.position.copy(controls.target).addScaledVector(dir, diag * fit);
  }
  controls.update();
  // Remember the framed pose so the Reset View button restores it exactly.
  initialCameraPose = {
    position: camera.position.clone(),
    target: controls.target.clone()
  };
}

// ---------------------------------------------------------------------------
// Sidecar effects API
// ---------------------------------------------------------------------------
function parseSelectors(target) {
  if (Array.isArray(target)) {
    const out = [];
    for (const t of target) out.push(...parseSelectors(t));
    return out;
  }
  if (target && typeof target === "object") {
    if (Array.isArray(target.partIds)) return target.partIds.map(String);
    if (target.partId) return [String(target.partId)];
    if (typeof target.ref === "string") return parseSelectors(target.ref);
    if (target.feature) return parseSelectors(target.feature);
  }
  const str = String(target || "").trim();
  if (!str) return [];
  // Feature name lookup
  const feat = features[str];
  if (feat?.ref) return parseSelectors(feat.ref);
  // @cad[...#a,b] or #a,b or plain id
  const hashMatch = str.match(/#([^\]]+)/);
  if (hashMatch) return hashMatch[1].split(",").map(s => s.trim()).filter(Boolean);
  if (str === "*" || str === "all" || str === "__all__") {
    return [...occurrenceWrappers.keys()];
  }
  return [str];
}

function resolveWrappers(target) {
  const selectors = parseSelectors(target);
  const out = new Set();
  for (const sel of selectors) {
    // Exact occurrence id, or any wrapper id startsWith(sel + ".")
    for (const [occ, wrapper] of occurrenceWrappers) {
      if (occ === sel || occ.startsWith(sel + ".") || sel.startsWith(occ + ".")) {
        out.add(wrapper);
      }
    }
  }
  return out;
}

function vec3(v, fallback = [0, 0, 0]) {
  if (Array.isArray(v) || ArrayBuffer.isView(v)) {
    return [
      Number(v[0]) || 0,
      Number(v[1]) || 0,
      Number(v[2]) || 0
    ];
  }
  if (v && typeof v === "object") {
    return [
      Number(v.x) || 0,
      Number(v.y) || 0,
      Number(v.z) || 0
    ];
  }
  return [...fallback];
}

function buildRotationMatrix(spec = {}) {
  const axis = vec3(spec.axis, [0, 0, 1]);
  const v = new THREE.Vector3(axis[0], axis[1], axis[2]);
  if (v.lengthSq() < 1e-12) v.set(0, 0, 1);
  v.normalize();
  const angleRad = Number.isFinite(Number(spec.angleRad))
    ? Number(spec.angleRad)
    : (Number(spec.angleDeg) || 0) * Math.PI / 180;
  const origin = vec3(spec.origin, [0, 0, 0]);
  const m = new THREE.Matrix4()
    .makeTranslation(origin[0], origin[1], origin[2])
    .multiply(new THREE.Matrix4().makeRotationAxis(v, angleRad))
    .multiply(new THREE.Matrix4().makeTranslation(-origin[0], -origin[1], -origin[2]));
  return m;
}

function buildScaleMatrix(spec = {}) {
  const raw = spec.scale ?? spec;
  const scl = Array.isArray(raw) || ArrayBuffer.isView(raw)
    ? vec3(raw, [1, 1, 1])
    : [Number(raw) || 1, Number(raw) || 1, Number(raw) || 1];
  const origin = vec3(spec.origin, [0, 0, 0]);
  return new THREE.Matrix4()
    .makeTranslation(origin[0], origin[1], origin[2])
    .multiply(new THREE.Matrix4().makeScale(scl[0], scl[1], scl[2]))
    .multiply(new THREE.Matrix4().makeTranslation(-origin[0], -origin[1], -origin[2]));
}

function buildTranslationMatrix(v) {
  const t = vec3(v, [0, 0, 0]);
  return new THREE.Matrix4().makeTranslation(t[0], t[1], t[2]);
}

function buildSingleEffectMatrix(spec = {}) {
  if (!spec || typeof spec !== "object") return new THREE.Matrix4();
  if (Array.isArray(spec.matrix) && spec.matrix.length === 16) {
    return new THREE.Matrix4().fromArray(spec.matrix).transpose(); // matrix is row-major in our format
  }
  const m = new THREE.Matrix4();
  if (spec.scale !== undefined) {
    m.premultiply(buildScaleMatrix(spec));
  }
  if (spec.rotate && typeof spec.rotate === "object") {
    m.premultiply(buildRotationMatrix(spec.rotate));
  }
  if (spec.translate !== undefined) {
    m.premultiply(buildTranslationMatrix(spec.translate));
  }
  return m;
}

function buildEffectMatrix(spec = {}) {
  if (!spec || typeof spec !== "object") return new THREE.Matrix4();
  const steps = Array.isArray(spec.transforms) ? spec.transforms : [spec];
  const m = new THREE.Matrix4();
  for (const step of steps) {
    m.premultiply(buildSingleEffectMatrix(step));
  }
  return m;
}

function parseColor(value, fallback) {
  if (value === undefined || value === null) return null;
  try {
    return new THREE.Color(value);
  } catch (e) {
    return fallback ?? null;
  }
}

function applyStyle(wrapper, style) {
  if (!style || typeof style !== "object") return;
  const color = parseColor(style.color);
  const emissive = parseColor(style.emissive);
  const emissiveIntensity = Number.isFinite(Number(style.emissiveIntensity))
    ? Number(style.emissiveIntensity) : null;
  const visible = style.visible;
  wrapper.traverse(child => {
    if (!child.isMesh || !child.material) return;
    const mats = Array.isArray(child.material) ? child.material : [child.material];
    for (const m of mats) {
      if (color) m.color = color.clone();
      if (emissive && m.emissive) m.emissive = emissive.clone();
      if (emissiveIntensity !== null && "emissiveIntensity" in m) {
        m.emissiveIntensity = emissiveIntensity;
      }
    }
    if (visible !== undefined) child.visible = visible !== false;
  });
}

function resetWrapperBaseStyle(wrapper) {
  wrapper.traverse(child => {
    if (!child.isMesh || !child.material) return;
    const mats = Array.isArray(child.material) ? child.material : [child.material];
    for (const m of mats) {
      if (m.userData._cad_baseColor !== undefined && m.color) {
        m.color.setHex(m.userData._cad_baseColor);
      }
      if (m.userData._cad_baseEmissive !== undefined && m.emissive) {
        m.emissive.setHex(m.userData._cad_baseEmissive);
      }
      if (m.userData._cad_baseEmissiveIntensity !== undefined && "emissiveIntensity" in m) {
        m.emissiveIntensity = m.userData._cad_baseEmissiveIntensity;
      }
    }
    child.visible = true;
  });
}

function createEffectsApi() {
  return {
    transform(target, spec) {
      const wrappers = resolveWrappers(target);
      const m = buildEffectMatrix(spec);
      for (const w of wrappers) {
        w.matrixAutoUpdate = false;
        w.matrix.copy(m);
        w.matrixWorldNeedsUpdate = true;
      }
    },
    style(target, style) {
      const wrappers = resolveWrappers(target);
      for (const w of wrappers) applyStyle(w, style);
    },
    visible(target, visible) {
      const wrappers = resolveWrappers(target);
      for (const w of wrappers) {
        w.visible = visible !== false;
      }
    },
    highlight() {},  // no-op in this viewer
    clear(target) {
      const wrappers = resolveWrappers(target);
      for (const w of wrappers) {
        w.matrixAutoUpdate = true;
        w.matrix.identity();
        w.position.set(0, 0, 0);
        w.quaternion.identity();
        w.scale.set(1, 1, 1);
        resetWrapperBaseStyle(w);
        w.visible = true;
      }
    }
  };
}

const effects = createEffectsApi();

// Normalize parameter defaults
const paramValues = {};
for (const [id, def] of Object.entries(paramDefs)) {
  const t = (def.type || "number").toLowerCase();
  if (t === "boolean") paramValues[id] = def.default !== false;
  else if (t === "color") paramValues[id] = def.default || "#ffffff";
  else if (t === "enum" || t === "select") {
    paramValues[id] = def.default || (def.options?.[0]?.value || def.options?.[0] || "");
  } else if (t === "string") paramValues[id] = def.default || "";
  else paramValues[id] = Number.isFinite(Number(def.default)) ? Number(def.default) : 0;
}

// ---------------------------------------------------------------------------
// UI: parameter sliders / toggles
// ---------------------------------------------------------------------------
const paramListEl = document.getElementById("param-list");
const valueDisplays = {};

function makeParamControl(id, def) {
  const wrap = document.createElement("div");
  wrap.className = "param";

  const label = document.createElement("label");
  const name = document.createElement("span");
  name.className = "name";
  name.textContent = def.label || id;
  const val = document.createElement("span");
  val.className = "value";
  label.appendChild(name);
  label.appendChild(val);
  wrap.appendChild(label);
  valueDisplays[id] = val;

  const t = (def.type || "number").toLowerCase();
  if (t === "boolean") {
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = paramValues[id];
    cb.addEventListener("input", () => {
      paramValues[id] = cb.checked;
      val.textContent = cb.checked ? "on" : "off";
    });
    val.textContent = cb.checked ? "on" : "off";
    wrap.appendChild(cb);
  } else if (t === "enum" || t === "select") {
    const sel = document.createElement("select");
    for (const opt of def.options || []) {
      const o = document.createElement("option");
      o.value = typeof opt === "string" ? opt : opt.value;
      o.textContent = typeof opt === "string" ? opt : (opt.label || opt.value);
      sel.appendChild(o);
    }
    sel.value = paramValues[id];
    sel.addEventListener("input", () => {
      paramValues[id] = sel.value;
      val.textContent = sel.value;
    });
    val.textContent = sel.value;
    wrap.appendChild(sel);
  } else {
    const range = document.createElement("input");
    range.type = "range";
    range.min = String(def.min ?? 0);
    range.max = String(def.max ?? 1);
    range.step = String(def.step ?? 0.01);
    range.value = String(paramValues[id]);
    range.addEventListener("input", () => {
      paramValues[id] = Number(range.value);
      val.textContent = `${range.value}${def.unit ? " " + def.unit : ""}`;
      // Pause animation when user scrubs the primary param
      if (id === model.primaryParam && playState.playing) {
        setPlay(false);
      }
    });
    val.textContent = `${range.value}${def.unit ? " " + def.unit : ""}`;
    wrap.appendChild(range);
    valueDisplays[id]._range = range;
  }

  if (def.description) {
    const desc = document.createElement("div");
    desc.className = "param-desc";
    desc.textContent = def.description;
    wrap.appendChild(desc);
  }
  paramListEl.appendChild(wrap);
}

for (const [id, def] of Object.entries(paramDefs)) {
  makeParamControl(id, def);
}

// ---------------------------------------------------------------------------
// Play / pause + animation loop
// ---------------------------------------------------------------------------
const playState = { playing: true, lastFrameTime: 0, elapsedSec: 0 };
const playBtn = document.getElementById("play");
function setPlay(p) {
  playState.playing = p;
  playBtn.textContent = p ? "❚❚ Pause" : "▶ Play";
  playBtn.classList.toggle("active", p);
}
setPlay(true);
playBtn.addEventListener("click", () => setPlay(!playState.playing));

document.getElementById("reset").addEventListener("click", () => {
  if (initialCameraPose) {
    camera.position.copy(initialCameraPose.position);
    controls.target.copy(initialCameraPose.target);
    controls.update();
  } else {
    setCameraFromSpherical(
      model.cameraStart.distance,
      model.cameraStart.azimuth,
      model.cameraStart.elevation,
      model.cameraTarget
    );
  }
});

// Helper: reset all wrappers to identity matrix and base style
function resetWrappers() {
  for (const w of occurrenceWrappers.values()) {
    w.matrixAutoUpdate = false;
    w.matrix.identity();
    w.matrixWorldNeedsUpdate = true;
    resetWrapperBaseStyle(w);
  }
}

const animMeta = manifest.animations && Object.values(manifest.animations)[0];
const duration = (animMeta?.duration || model.animationDurationSec || 4);

// State for the opt-in chaseX camera follow.
let lastChaseX = 0;

function tick(now) {
  if (playState.lastFrameTime === 0) playState.lastFrameTime = now;
  const dtSec = (now - playState.lastFrameTime) / 1000;
  playState.lastFrameTime = now;
  if (playState.playing) {
    playState.elapsedSec = (playState.elapsedSec + dtSec) % duration;
    // Drive the primary param linearly from its range
    if (model.primaryParam && paramDefs[model.primaryParam]) {
      const p = paramDefs[model.primaryParam];
      const lo = Number(p.min ?? 0);
      const hi = Number(p.max ?? 1);
      const t = playState.elapsedSec / duration;
      paramValues[model.primaryParam] = lo + (hi - lo) * t;
      const range = valueDisplays[model.primaryParam]?._range;
      if (range) {
        range.value = String(paramValues[model.primaryParam]);
        valueDisplays[model.primaryParam].textContent = `${Math.round(paramValues[model.primaryParam])}${p.unit ? " " + p.unit : ""}`;
      }
    }
  }

  // Reset wrappers & styles, then call sidecar
  resetWrappers();
  if (typeof sidecar.update === "function") {
    try {
      sidecar.update({
        params: paramValues,
        effects,
        time: {
          elapsed: playState.elapsedSec,
          elapsedSec: playState.elapsedSec,
          duration,
          progress: playState.elapsedSec / duration,
          cycle: playState.elapsedSec / duration,
          playing: playState.playing,
          speed: 1
        },
        features: {},
        manifest
      });
    } catch (e) {
      console.error("sidecar.update failed", e);
      setStatus("sidecar error: " + e.message);
      setPlay(false);
    }
  }

  // Opt-in chase: only translate the camera along X when the model
  // registry names a `chaseX` occurrence whose wrapper is being
  // translated by the sidecar (e.g. bicycle frame when rolling forward).
  // For everything else we leave the camera alone, which prevents the
  // wobble caused by tracking a rotating model's bbox center.
  if (model.chaseX && !controls._userInteracting) {
    const wrapper = occurrenceWrappers.get(model.chaseX);
    if (wrapper) {
      const newX = wrapper.matrix.elements[12] || 0;
      const dx = newX - lastChaseX;
      if (Math.abs(dx) > 0.5) {
        controls.target.x += dx;
        camera.position.x += dx;
      }
      lastChaseX = newX;
    }
  }

  controls.update();
  if (composer) {
    composer.render();
  } else {
    renderer.render(scene, camera);
  }
  requestAnimationFrame(tick);
}

controls.addEventListener("start", () => { controls._userInteracting = true; });
controls.addEventListener("end",   () => {
  setTimeout(() => { controls._userInteracting = false; }, 800);
});

setStatus(`${occurrenceWrappers.size} parts · ${Object.keys(paramDefs).length} params`);

// Expose internals for ad-hoc debugging from the browser console.
window.__cad = { scene, camera, controls, occurrenceWrappers, paramValues, sidecar, effects };

requestAnimationFrame(tick);
