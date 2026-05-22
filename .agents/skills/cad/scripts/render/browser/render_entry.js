import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { LineMaterial } from "three/examples/jsm/lines/LineMaterial.js";
import { LineSegments2 } from "three/examples/jsm/lines/LineSegments2.js";
import { LineSegmentsGeometry } from "three/examples/jsm/lines/LineSegmentsGeometry.js";

const DEFAULT_MODEL_COLOR = [0.8, 0.84, 0.9];
const INSPECTION_SURFACE_COLOR = [0.74, 0.77, 0.80];
const TECHNICAL_LINE_COLOR = [0x25 / 255, 0x2b / 255, 0x31 / 255];
const DEFAULT_RENDER_SCALE = 2;
const WORLD_UP = Object.freeze([0, 0, 1]);
const TOP_VIEW_UP = Object.freeze([0, 1, 0]);
const COMPONENT_COLORS = [
  [0.82, 0.84, 0.88],
  [0.68, 0.77, 0.91],
  [0.7, 0.86, 0.79],
  [0.93, 0.79, 0.62],
  [0.88, 0.72, 0.78],
  [0.76, 0.72, 0.9],
  [0.85, 0.83, 0.62],
  [0.68, 0.86, 0.87],
];

const VIEW_PRESETS = {
  front: { name: "front", direction: [0, -1, 0], up: WORLD_UP },
  back: { name: "back", direction: [0, 1, 0], up: WORLD_UP },
  right: { name: "right", direction: [1, 0, 0], up: WORLD_UP },
  left: { name: "left", direction: [-1, 0, 0], up: WORLD_UP },
  top: { name: "top", direction: [0, 0, 1], up: TOP_VIEW_UP },
  bottom: { name: "bottom", direction: [0, 0, -1], up: TOP_VIEW_UP },
  iso: { name: "iso", direction: [1, -1, 0.8], up: WORLD_UP },
  isometric: { name: "iso", direction: [1, -1, 0.8], up: WORLD_UP },
  side: { name: "side", direction: [1, 0, 0], up: WORLD_UP },
};

async function main() {
  let result;
  try {
    const job = await fetchJson("/job");
    result = await renderJob(job);
  } catch (error) {
    result = {
      ok: false,
      error: error instanceof Error ? error.message : String(error),
    };
  }
  await fetch("/result", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(result),
  });
}

async function fetchJson(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to load ${path}: HTTP ${response.status}`);
  }
  return response.json();
}

async function renderJob(job) {
  validateJob(job);
  const width = positiveInteger(job.width, "width");
  const height = positiveInteger(job.height, "height");
  const transparent = Boolean(job.transparent);
  const background = colorFromArray(job.background, [0.98, 0.985, 0.99]);
  const scene = new THREE.Scene();
  const loadStarted = performance.now();
  const gltf = await new GLTFLoader().loadAsync(`/asset?path=${encodeURIComponent(job.glbPath)}`);
  const loadMs = performance.now() - loadStarted;
  const root = gltf.scene;
  scene.add(root);
  scene.add(new THREE.HemisphereLight(0xffffff, 0xd8dee7, 0.95));
  const keyLight = new THREE.DirectionalLight(0xffffff, 1.35);
  keyLight.position.set(2.2, -2.0, 3.2);
  scene.add(keyLight);
  const fillLight = new THREE.DirectionalLight(0xf5f8ff, 0.12);
  fillLight.position.set(-3, 1.2, 1.4);
  scene.add(fillLight);
  scene.updateMatrixWorld(true);

  const records = collectMeshRecords(root);
  const visibleIds = new Set(job.visibleOccurrenceIds.map((value) => String(value)));
  const visibleRecords = records.filter((record) => visibleIds.has(record.occurrenceId));
  const missing = [...visibleIds].filter((id) => !records.some((record) => record.occurrenceId === id));
  if (missing.length > 0) {
    throw new Error(`GLB is missing render meshes for occurrence id(s): ${missing.join(", ")}`);
  }
  if (visibleRecords.length === 0) {
    throw new Error("No visible GLB meshes remain after applying focus/hide filters");
  }
  for (const record of records) {
    record.mesh.visible = visibleIds.has(record.occurrenceId);
  }

  const modelColor = colorFromArray(job.modelColor, DEFAULT_MODEL_COLOR);
  const componentOrder = new Map(job.partOrder.map((id, index) => [String(id), index]));
  const renderMode = String(job.renderMode || "solid");
  const preset = String(job.preset || "solid");
  const colorBy = String(job.colorBy || "step");
  const edgeStyle = String(job.edgeStyle || "thin");
  const hiddenLines = String(job.hiddenLines || "off");
  applyMaterials(visibleRecords, {
    modelColor,
    componentOrder,
    renderMode,
    preset,
    colorBy,
    hiddenLines,
  });
  if (edgeStyle !== "off" || renderMode === "wireframe") {
    addEdgeObjects(visibleRecords, {
      renderMode,
      edgeStyle,
      hiddenLines,
    });
  }

  const bounds = boundsForRecords(visibleRecords);
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.001, 10);
  const renderScale = Math.max(1, Math.min(3, Number(job.renderScale || DEFAULT_RENDER_SCALE)));
  const renderer = new THREE.WebGLRenderer({
    alpha: true,
    antialias: true,
    preserveDrawingBuffer: true,
  });
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.setPixelRatio(renderScale);
  renderer.setSize(width, height, false);
  renderer.setClearColor(new THREE.Color(...background), transparent ? 0 : 1);
  document.body.appendChild(renderer.domElement);

  const renderStarted = performance.now();
  const outputs = [];
  const lockedHalfHeight = Boolean(job.lockFraming)
    ? lockedFrameHalfHeight(job.outputs, bounds, width, height)
    : null;
  for (const output of job.outputs) {
    const view = resolveView(String(output.camera || "iso"));
    fitOrthographicCamera(camera, view, bounds, width, height, lockedHalfHeight);
    syncLineMaterialResolutions(visibleRecords, renderer);
    renderer.clear(true, true, true);
    renderer.render(scene, camera);
    const dataUrl = captureDataUrl(
      renderer.domElement,
      camera,
      width,
      height,
      Boolean(job.axes),
    );
    outputs.push({
      camera: view.name,
      path: String(output.path),
      width,
      height,
      dataUrl,
    });
  }
  const renderMs = performance.now() - renderStarted;
  renderer.dispose();
  return {
    ok: true,
    outputs,
    timings: {
      loadMs,
      renderMs,
      loadCount: 1,
      meshCount: visibleRecords.length,
    },
  };
}

function validateJob(job) {
  if (!job || typeof job !== "object") {
    throw new Error("Render job must be a JSON object");
  }
  if (!job.glbPath || typeof job.glbPath !== "string") {
    throw new Error("Render job is missing glbPath");
  }
  if (!Array.isArray(job.visibleOccurrenceIds) || job.visibleOccurrenceIds.length === 0) {
    throw new Error("Render job is missing visibleOccurrenceIds");
  }
  if (!Array.isArray(job.outputs) || job.outputs.length === 0) {
    throw new Error("Render job is missing outputs");
  }
  if (!Array.isArray(job.partOrder)) {
    job.partOrder = job.visibleOccurrenceIds;
  }
}

function positiveInteger(value, label) {
  const integer = Number.parseInt(value, 10);
  if (!Number.isFinite(integer) || integer <= 0) {
    throw new Error(`Render job ${label} must be a positive integer`);
  }
  return integer;
}

function colorFromArray(value, fallback) {
  const source = Array.isArray(value) && value.length >= 3 ? value : fallback;
  return source.slice(0, 3).map((channel) => Math.max(0, Math.min(1, Number(channel))));
}

function collectMeshRecords(root) {
  const records = [];
  root.traverse((object) => {
    if (!object.isMesh || !object.geometry) {
      return;
    }
    const occurrenceId = occurrenceIdForObject(object);
    if (!occurrenceId) {
      return;
    }
    records.push({ mesh: object, occurrenceId });
  });
  return records;
}

function occurrenceIdForObject(object) {
  let cursor = object;
  while (cursor) {
    const userData = cursor.userData || {};
    const occurrenceId = userData.cadOccurrenceId || userData.occurrenceId || userData.cadId;
    if (occurrenceId) {
      return String(occurrenceId);
    }
    cursor = cursor.parent;
  }
  return "";
}

function applyMaterials(records, options) {
  for (const record of records) {
    const mesh = record.mesh;
    if (options.renderMode === "wireframe") {
      mesh.material = depthOnlyMaterial(options.hiddenLines !== "all");
      continue;
    }
    const material = materialForRecord(record, options);
    mesh.material = Array.isArray(mesh.material) ? mesh.material.map(() => material.clone()) : material;
  }
}

function materialForRecord(record, options) {
  if (options.preset === "normals") {
    return new THREE.MeshNormalMaterial({ side: THREE.DoubleSide });
  }
  if (options.preset === "depth") {
    return new THREE.MeshDepthMaterial({ side: THREE.DoubleSide });
  }
  const color = colorForRecord(record, options);
  const opacity = options.preset === "xray" ? 0.42 : 1;
  if (options.preset === "solid" || options.preset === "technical" || options.preset === "component" || options.preset === "clay") {
    return new THREE.MeshLambertMaterial({
      color: new THREE.Color(...color),
      side: THREE.DoubleSide,
      polygonOffset: true,
      polygonOffsetFactor: 1,
      polygonOffsetUnits: 1,
    });
  }
  return new THREE.MeshStandardMaterial({
    color: new THREE.Color(...color),
    emissive: new THREE.Color(...color),
    emissiveIntensity: 0.24,
    metalness: 0,
    roughness: 0.82,
    transparent: opacity < 1,
    opacity,
    depthWrite: opacity >= 1,
    side: THREE.DoubleSide,
  });
}

function depthOnlyMaterial(depthWrite) {
  const material = new THREE.MeshBasicMaterial({
    color: 0xffffff,
    depthWrite,
    depthTest: depthWrite,
    side: THREE.DoubleSide,
  });
  material.colorWrite = false;
  return material;
}

function colorForRecord(record, options) {
  if (options.colorBy === "none") {
    return readableSurfaceColor(options.modelColor, options.preset);
  }
  if (options.colorBy === "occurrence") {
    const index = options.componentOrder.get(record.occurrenceId) ?? 0;
    if (options.componentOrder.size <= 1) {
      return readableSurfaceColor(options.modelColor, options.preset);
    }
    return readableSurfaceColor(COMPONENT_COLORS[index % COMPONENT_COLORS.length], options.preset);
  }
  if (options.preset === "component") {
    const index = options.componentOrder.get(record.occurrenceId) ?? 0;
    return readableSurfaceColor(COMPONENT_COLORS[index % COMPONENT_COLORS.length], options.preset);
  }
  if (options.preset === "solid") {
    const materialColor = baseColorFromMaterial(record.mesh.material);
    return readableSurfaceColor(materialColor || INSPECTION_SURFACE_COLOR, options.preset);
  }
  if (options.preset === "clay") {
    return [0.74, 0.72, 0.68];
  }
  if (options.preset === "technical") {
    return [0.86, 0.88, 0.9];
  }
  if (options.preset === "xray") {
    return [0.62, 0.76, 0.92];
  }
  const materialColor = baseColorFromMaterial(record.mesh.material);
  return readableSurfaceColor(materialColor || options.modelColor, options.preset);
}

function readableSurfaceColor(color, preset) {
  if (preset === "normals" || preset === "depth" || preset === "xray") {
    return color;
  }
  const rgb = color.map((channel) => Math.max(0, Math.min(1, Number(channel))));
  const luminance = (0.2126 * rgb[0]) + (0.7152 * rgb[1]) + (0.0722 * rgb[2]);
  const target = preset === "solid"
    ? Math.max(0.58, Math.min(0.76, 0.68 + ((luminance - 0.68) * 0.12)))
    : Math.max(0.44, Math.min(0.58, 0.51 + ((luminance - 0.51) * 0.18)));
  const scale = luminance > 1e-6 ? target / luminance : 1;
  return rgb.map((channel) => Math.max(0.30, Math.min(0.78, channel * scale)));
}

function baseColorFromMaterial(material) {
  const first = Array.isArray(material) ? material[0] : material;
  if (!first) {
    return null;
  }
  if (first.color) {
    return [first.color.r, first.color.g, first.color.b];
  }
  return null;
}

function addEdgeObjects(records, options) {
  const lineColor = new THREE.Color(...TECHNICAL_LINE_COLOR).getHex();
  const lineWidth = options.edgeStyle === "bold" ? 2.4 : 1.65;
  for (const record of records) {
    const edgeGeometry = new THREE.EdgesGeometry(record.mesh.geometry, options.renderMode === "wireframe" ? 1 : 18);
    const geometry = lineSegmentsGeometryFromEdges(edgeGeometry);
    edgeGeometry.dispose();
    record.edgeMaterials = [];
    if (options.renderMode === "wireframe" && options.hiddenLines === "faint") {
      const faintMaterial = new LineMaterial({
        color: lineColor,
        linewidth: lineWidth,
        transparent: true,
        opacity: 0.18,
        depthTest: false,
        depthWrite: false,
      });
      const faint = new LineSegments2(geometry, faintMaterial);
      record.edgeMaterials.push(faintMaterial);
      record.mesh.add(faint);
    }
    const depthTest = options.renderMode !== "wireframe" || options.hiddenLines !== "all";
    const material = new LineMaterial({
      color: lineColor,
      linewidth: lineWidth,
      transparent: false,
      opacity: 1,
      depthTest,
      depthWrite: false,
    });
    const edges = new LineSegments2(geometry, material);
    record.edgeMaterials.push(material);
    record.mesh.add(edges);
  }
}

function lineSegmentsGeometryFromEdges(edgeGeometry) {
  const source = edgeGeometry.getAttribute("position");
  const positions = new Float32Array(source.count * 3);
  for (let index = 0; index < source.count; index += 1) {
    positions[(index * 3)] = source.getX(index);
    positions[(index * 3) + 1] = source.getY(index);
    positions[(index * 3) + 2] = source.getZ(index);
  }
  const geometry = new LineSegmentsGeometry();
  geometry.setPositions(positions);
  return geometry;
}

function syncLineMaterialResolutions(records, renderer) {
  const width = renderer.domElement.width;
  const height = renderer.domElement.height;
  for (const record of records) {
    for (const material of record.edgeMaterials || []) {
      material.resolution.set(width, height);
    }
  }
}

function boundsForRecords(records) {
  const bounds = new THREE.Box3();
  const meshBox = new THREE.Box3();
  for (const record of records) {
    record.mesh.updateWorldMatrix(true, false);
    if (!record.mesh.geometry.boundingBox) {
      record.mesh.geometry.computeBoundingBox();
    }
    meshBox.copy(record.mesh.geometry.boundingBox).applyMatrix4(record.mesh.matrixWorld);
    bounds.union(meshBox);
  }
  if (bounds.isEmpty()) {
    bounds.set(new THREE.Vector3(-1, -1, -1), new THREE.Vector3(1, 1, 1));
  }
  return bounds;
}

function resolveView(rawView) {
  const key = rawView.trim().toLowerCase();
  if (VIEW_PRESETS[key]) {
    return VIEW_PRESETS[key];
  }
  const parts = key.split(":");
  if (parts.length === 2 || parts.length === 3) {
    const azimuth = Number(parts[0]) * Math.PI / 180;
    const elevation = Number(parts[1]) * Math.PI / 180;
    if (!Number.isFinite(azimuth) || !Number.isFinite(elevation)) {
      throw new Error(`Invalid camera: ${rawView}`);
    }
    return {
      name: key.replaceAll(":", "_"),
      direction: [
        Math.cos(elevation) * Math.cos(azimuth),
        Math.cos(elevation) * Math.sin(azimuth),
        Math.sin(elevation),
      ],
      up: WORLD_UP,
    };
  }
  throw new Error(`Unknown camera: ${rawView}`);
}

function lockedFrameHalfHeight(outputs, bounds, width, height) {
  const probeCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.001, 10);
  let halfHeight = 0;
  for (const output of outputs) {
    const view = resolveView(String(output.camera || "iso"));
    fitOrthographicCamera(probeCamera, view, bounds, width, height);
    halfHeight = Math.max(halfHeight, Math.abs(probeCamera.top), Math.abs(probeCamera.bottom));
  }
  return Number.isFinite(halfHeight) && halfHeight > 0 ? halfHeight : null;
}

function fitOrthographicCamera(camera, view, bounds, width, height, lockedHalfHeight = null) {
  const center = new THREE.Vector3();
  const size = new THREE.Vector3();
  bounds.getCenter(center);
  bounds.getSize(size);
  const diagonal = Math.max(size.length(), 1e-6);
  const direction = new THREE.Vector3(...view.direction).normalize();
  const up = projectedUp(direction, new THREE.Vector3(...view.up));
  camera.up.copy(up);
  camera.position.copy(center).addScaledVector(direction, diagonal * 2.2);
  camera.lookAt(center);
  camera.updateMatrixWorld(true);

  const corners = boxCorners(bounds);
  const projected = corners.map((corner) => corner.clone().applyMatrix4(camera.matrixWorldInverse));
  const xs = projected.map((corner) => corner.x);
  const ys = projected.map((corner) => corner.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const aspect = width / height;
  const spanX = Math.max(maxX - minX, 1e-9);
  const spanY = Math.max(maxY - minY, 1e-9);
  const fittedHalfHeight = Math.max(spanY * 0.5, (spanX / aspect) * 0.5) * 1.03;
  let halfHeight = Number.isFinite(lockedHalfHeight)
    ? Math.max(fittedHalfHeight, Number(lockedHalfHeight))
    : fittedHalfHeight;
  let halfWidth = halfHeight * aspect;
  if (!Number.isFinite(halfWidth) || !Number.isFinite(halfHeight)) {
    halfWidth = 1;
    halfHeight = 1;
  }
  camera.left = -halfWidth;
  camera.right = halfWidth;
  camera.top = halfHeight;
  camera.bottom = -halfHeight;
  camera.near = 0.001;
  camera.far = diagonal * 6;
  camera.updateProjectionMatrix();
}

function projectedUp(direction, up) {
  const projected = up.clone().sub(direction.clone().multiplyScalar(up.dot(direction)));
  if (projected.lengthSq() > 1e-9) {
    return projected.normalize();
  }
  const fallback = Math.abs(direction.z) < 0.9 ? new THREE.Vector3(...WORLD_UP) : new THREE.Vector3(...TOP_VIEW_UP);
  return fallback.sub(direction.clone().multiplyScalar(fallback.dot(direction))).normalize();
}

function boxCorners(box) {
  const min = box.min;
  const max = box.max;
  return [
    new THREE.Vector3(min.x, min.y, min.z),
    new THREE.Vector3(max.x, min.y, min.z),
    new THREE.Vector3(min.x, max.y, min.z),
    new THREE.Vector3(max.x, max.y, min.z),
    new THREE.Vector3(min.x, min.y, max.z),
    new THREE.Vector3(max.x, min.y, max.z),
    new THREE.Vector3(min.x, max.y, max.z),
    new THREE.Vector3(max.x, max.y, max.z),
  ];
}

function captureDataUrl(sourceCanvas, camera, width, height, axes) {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = "high";
  context.drawImage(sourceCanvas, 0, 0, width, height);
  if (axes) {
    drawAxes(context, camera, canvas.width, canvas.height);
  }
  return canvas.toDataURL("image/png");
}

function drawAxes(context, camera, width, height) {
  const origin = { x: Math.max(30, Math.min(54, width * 0.12)), y: height - Math.max(30, Math.min(54, height * 0.12)) };
  const length = Math.max(18, Math.min(32, Math.min(width, height) * 0.08));
  const cameraRight = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 0).normalize();
  const cameraUp = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 1).normalize();
  const axes = [
    { vector: new THREE.Vector3(1, 0, 0), color: "#d84a3a", label: "X" },
    { vector: new THREE.Vector3(0, 1, 0), color: "#42a05a", label: "Y" },
    { vector: new THREE.Vector3(0, 0, 1), color: "#3e73d8", label: "Z" },
  ];
  context.save();
  context.lineWidth = 2;
  context.font = "10px sans-serif";
  context.textAlign = "center";
  context.textBaseline = "middle";
  for (const axis of axes) {
    const x = origin.x + axis.vector.dot(cameraRight) * length;
    const y = origin.y - axis.vector.dot(cameraUp) * length;
    context.strokeStyle = axis.color;
    context.fillStyle = axis.color;
    context.beginPath();
    context.moveTo(origin.x, origin.y);
    context.lineTo(x, y);
    context.stroke();
    context.fillText(axis.label, x + Math.sign(x - origin.x || 1) * 8, y + Math.sign(y - origin.y || 1) * 8);
  }
  context.restore();
}

main();
