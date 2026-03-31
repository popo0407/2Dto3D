import { Canvas, type ThreeEvent } from "@react-three/fiber";
import { OrbitControls, Grid, useGLTF, Center, Html, Line, Bounds, useBounds } from "@react-three/drei";
import { Suspense, useState, useMemo, useRef, useCallback, useEffect } from "react";
import * as THREE from "three";

/* ---------- Shared types ---------- */

export type SelectionType = "face" | "edge" | "cylinder" | "mesh";

export interface SelectionInfo {
  type: SelectionType;
  meshName: string;
  featureId?: string;
  position: { x: number; y: number; z: number };
  normal?: { x: number; y: number; z: number };
  dimensions: { width: number; height: number; depth: number };
  faceIndex?: number;
  faceDimensions?: { width: number; height: number; area: number };
  cylinderInfo?: { diameter: number; depth: number; axis: string };
}

export interface MeasureResult {
  point1: { x: number; y: number; z: number };
  point2: { x: number; y: number; z: number };
  distance: number;
}

interface Viewer3DProps {
  gltfUrl: string;
  onDownloadStep?: () => void;
  onSelectionChange?: (selection: SelectionInfo | null) => void;
}

type DimensionMode = "off" | "selected" | "all";

/* ---------- Selectable GLTF Model ---------- */

function SelectableModel({
  url,
  onMeshSelect,
  measureMode,
  onMeasureClick,
}: {
  url: string;
  onMeshSelect: (info: SelectionInfo | null, mesh: THREE.Object3D | null) => void;
  measureMode: boolean;
  onMeasureClick?: (point: THREE.Vector3, normal: THREE.Vector3) => void;
}) {
  const { scene } = useGLTF(url);
  const highlightRef = useRef<THREE.Mesh | null>(null);
  const edgeRef = useRef<THREE.LineSegments | null>(null);

  const clonedScene = useMemo(() => {
    const clone = scene.clone(true);
    clone.traverse((child) => {
      if ((child as THREE.Mesh).isMesh) {
        const mesh = child as THREE.Mesh;
        if (mesh.geometry && !mesh.geometry.attributes.normal) {
          mesh.geometry.computeVertexNormals();
        }
        if (Array.isArray(mesh.material)) {
          mesh.material = mesh.material.map((m) => m.clone());
        } else {
          mesh.material = mesh.material.clone();
        }
      }
    });
    return clone;
  }, [scene]);

  const clearHighlight = useCallback(() => {
    if (highlightRef.current) {
      highlightRef.current.parent?.remove(highlightRef.current);
      highlightRef.current.geometry.dispose();
      (highlightRef.current.material as THREE.Material).dispose();
      highlightRef.current = null;
    }
    if (edgeRef.current) {
      edgeRef.current.parent?.remove(edgeRef.current);
      edgeRef.current.geometry.dispose();
      (edgeRef.current.material as THREE.Material).dispose();
      edgeRef.current = null;
    }
  }, []);

  const handleClick = useCallback(
    (e: ThreeEvent<MouseEvent>) => {
      e.stopPropagation();
      const mesh = e.object as THREE.Mesh;
      if (!mesh.isMesh || e.faceIndex == null || !e.face) return;

      // Distance measurement mode
      if (measureMode && onMeasureClick) {
        const n = e.face.normal.clone();
        n.transformDirection(mesh.matrixWorld);
        onMeasureClick(e.point.clone(), n.normalize());
        return;
      }

      clearHighlight();

      // Try cylinder detection (holes / curved surfaces)
      const cylResult = _detectCylinder(mesh.geometry, e.faceIndex);

      let hlGeo: THREE.BufferGeometry;
      let selType: SelectionType = "face";
      let faceDims: { width: number; height: number; area: number } | undefined;
      let cylInfo: { diameter: number; depth: number; axis: string } | undefined;
      let hlColor = 0xff6600;

      if (cylResult) {
        hlGeo = cylResult.highlightGeo;
        selType = "cylinder";
        cylInfo = { diameter: cylResult.diameter, depth: cylResult.depth, axis: cylResult.axis };
        hlColor = 0x00ccff;
      } else {
        hlGeo = _buildCoplanarHighlight(mesh.geometry, e.faceIndex, e.face.normal);
        faceDims = _computeFaceGroupInfo(hlGeo, e.face.normal);
      }

      const hlMat = new THREE.MeshBasicMaterial({
        color: hlColor,
        transparent: true,
        opacity: 0.45,
        side: THREE.DoubleSide,
        depthTest: true,
        polygonOffset: true,
        polygonOffsetFactor: -1,
      });
      const hlMesh = new THREE.Mesh(hlGeo, hlMat);
      mesh.add(hlMesh);
      highlightRef.current = hlMesh;

      // Add edge outline for the selected faces
      const edgeGeo = new THREE.EdgesGeometry(hlGeo, 1);
      const edgeMat = new THREE.LineBasicMaterial({ color: cylResult ? 0x00aaff : 0xffaa00, linewidth: 2 });
      const edgeLine = new THREE.LineSegments(edgeGeo, edgeMat);
      mesh.add(edgeLine);
      edgeRef.current = edgeLine;

      const box = new THREE.Box3().setFromObject(mesh);
      const sz = box.getSize(new THREE.Vector3());

      let faceNormal: { x: number; y: number; z: number } | undefined;
      const n = e.face.normal.clone();
      n.transformDirection(mesh.matrixWorld);
      faceNormal = { x: +n.x.toFixed(4), y: +n.y.toFixed(4), z: +n.z.toFixed(4) };

      onMeshSelect(
        {
          type: selType,
          meshName: mesh.name || `mesh_${mesh.id}`,
          featureId: _extractFeatureId(mesh.name),
          position: {
            x: +e.point.x.toFixed(2),
            y: +e.point.y.toFixed(2),
            z: +e.point.z.toFixed(2),
          },
          normal: faceNormal,
          dimensions: {
            width: +sz.x.toFixed(2),
            height: +sz.y.toFixed(2),
            depth: +sz.z.toFixed(2),
          },
          faceIndex: e.faceIndex ?? undefined,
          faceDimensions: faceDims,
          cylinderInfo: cylInfo,
        },
        mesh,
      );
    },
    [clearHighlight, onMeshSelect, measureMode, onMeasureClick],
  );

  const handleMiss = useCallback(() => {
    clearHighlight();
    onMeshSelect(null, null);
  }, [clearHighlight, onMeshSelect]);

  // Auto-fit camera to model bounds on first load
  const bounds = useBounds();
  useEffect(() => {
    bounds.refresh().clip().fit();
  }, [clonedScene, bounds]);

  return (
    <group onClick={handleClick} onPointerMissed={handleMiss}>
      <primitive object={clonedScene} />
    </group>
  );
}

/* ---------- Dimension Lines ---------- */

function DimensionLines({ target }: { target: THREE.Object3D }) {
  const { min, max, size } = useMemo(() => {
    const box = new THREE.Box3().setFromObject(target);
    return { min: box.min, max: box.max, size: box.getSize(new THREE.Vector3()) };
  }, [target]);

  const offset = Math.max(size.x, size.y, size.z) * 0.15 + 0.2;

  return (
    <group>
      {/* X axis — Width (red) */}
      {size.x > 0.01 && (
        <>
          <Line
            points={[
              [min.x, min.y - offset, max.z],
              [max.x, min.y - offset, max.z],
            ]}
            color="#ef4444"
            lineWidth={2}
          />
          <Html
            position={[(min.x + max.x) / 2, min.y - offset, max.z]}
            center
            style={{ pointerEvents: "none" }}
          >
            <span className="rounded bg-red-600/90 px-1.5 py-0.5 text-[10px] font-bold text-white whitespace-nowrap shadow">
              W {size.x.toFixed(1)}
            </span>
          </Html>
        </>
      )}
      {/* Y axis — Height (green) */}
      {size.y > 0.01 && (
        <>
          <Line
            points={[
              [max.x + offset, min.y, max.z],
              [max.x + offset, max.y, max.z],
            ]}
            color="#22c55e"
            lineWidth={2}
          />
          <Html
            position={[max.x + offset, (min.y + max.y) / 2, max.z]}
            center
            style={{ pointerEvents: "none" }}
          >
            <span className="rounded bg-green-600/90 px-1.5 py-0.5 text-[10px] font-bold text-white whitespace-nowrap shadow">
              H {size.y.toFixed(1)}
            </span>
          </Html>
        </>
      )}
      {/* Z axis — Depth (blue) */}
      {size.z > 0.01 && (
        <>
          <Line
            points={[
              [max.x, min.y - offset, min.z],
              [max.x, min.y - offset, max.z],
            ]}
            color="#3b82f6"
            lineWidth={2}
          />
          <Html
            position={[max.x, min.y - offset, (min.z + max.z) / 2]}
            center
            style={{ pointerEvents: "none" }}
          >
            <span className="rounded bg-blue-600/90 px-1.5 py-0.5 text-[10px] font-bold text-white whitespace-nowrap shadow">
              D {size.z.toFixed(1)}
            </span>
          </Html>
        </>
      )}
    </group>
  );
}

/* ---------- Scene Content (inside Canvas) ---------- */

function SceneContent({
  gltfUrl,
  dimensionMode,
  measureMode,
  onSelectionChange,
  onMeasureResult,
}: {
  gltfUrl: string;
  dimensionMode: DimensionMode;
  measureMode: boolean;
  onSelectionChange: (info: SelectionInfo | null) => void;
  onMeasureResult: (result: MeasureResult | null) => void;
}) {
  const [selectedMesh, setSelectedMesh] = useState<THREE.Object3D | null>(null);
  const sceneRootRef = useRef<THREE.Group>(null);
  const measureRef = useRef<{ point: THREE.Vector3; normal: THREE.Vector3 } | null>(null);
  const [measureLine, setMeasureLine] = useState<{
    p1: [number, number, number];
    p2: [number, number, number];
    distance: number;
  } | null>(null);

  const handleMeshSelect = useCallback(
    (info: SelectionInfo | null, mesh: THREE.Object3D | null) => {
      setSelectedMesh(mesh);
      onSelectionChange(info);
    },
    [onSelectionChange],
  );

  const handleMeasureClick = useCallback(
    (point: THREE.Vector3, normal: THREE.Vector3) => {
      if (!measureRef.current) {
        // First point
        measureRef.current = { point, normal };
        setMeasureLine(null);
        onMeasureResult(null);
      } else {
        // Second point — compute distance
        const first = measureRef.current;
        const dot = first.normal.dot(normal);
        let distance: number;
        if (Math.abs(dot) > 0.9) {
          // Parallel faces → perpendicular distance between planes
          const diff = first.point.clone().sub(point);
          distance = Math.abs(first.normal.dot(diff));
        } else {
          // Non-parallel → point-to-point distance
          distance = first.point.distanceTo(point);
        }
        const p1: [number, number, number] = [first.point.x, first.point.y, first.point.z];
        const p2: [number, number, number] = [point.x, point.y, point.z];
        setMeasureLine({ p1, p2, distance });
        onMeasureResult({
          point1: { x: +p1[0].toFixed(2), y: +p1[1].toFixed(2), z: +p1[2].toFixed(2) },
          point2: { x: +p2[0].toFixed(2), y: +p2[1].toFixed(2), z: +p2[2].toFixed(2) },
          distance: +distance.toFixed(2),
        });
        measureRef.current = null;
      }
    },
    [onMeasureResult],
  );

  // Clear measure state when leaving measure mode
  useEffect(() => {
    if (!measureMode) {
      measureRef.current = null;
      setMeasureLine(null);
      onMeasureResult(null);
    }
  }, [measureMode, onMeasureResult]);

  const dimensionTarget =
    dimensionMode === "all"
      ? sceneRootRef.current
      : dimensionMode === "selected"
        ? selectedMesh
        : null;

  return (
    <>
      <ambientLight intensity={0.6} />
      <directionalLight position={[10, 10, 5]} intensity={1.2} />
      <directionalLight position={[-5, -5, -5]} intensity={0.4} />
      <Bounds fit clip observe margin={1.5}>
        <Center>
          <group ref={sceneRootRef}>
            <SelectableModel
              url={gltfUrl}
              onMeshSelect={handleMeshSelect}
              measureMode={measureMode}
              onMeasureClick={handleMeasureClick}
            />
          </group>
        </Center>
      </Bounds>
      {dimensionTarget && <DimensionLines target={dimensionTarget} />}
      {measureLine && (
        <MeasureDistanceLine p1={measureLine.p1} p2={measureLine.p2} distance={measureLine.distance} />
      )}
      <OrbitControls makeDefault />
      <Grid
        args={[20, 20]}
        cellSize={1}
        cellThickness={0.5}
        cellColor="#4a5568"
        sectionSize={5}
        sectionThickness={1}
        sectionColor="#718096"
        fadeDistance={25}
        infiniteGrid
      />
    </>
  );
}

/* ---------- Placeholder ---------- */

function ModelPlaceholder() {
  return (
    <mesh>
      <boxGeometry args={[2, 2, 2]} />
      <meshStandardMaterial color="#94a3b8" wireframe />
    </mesh>
  );
}

/* ---------- Helpers ---------- */

function _extractFeatureId(name: string): string | undefined {
  const m = name.match(/Feature-\d+/i);
  return m ? m[0] : undefined;
}

function _normalToLabel(n: { x: number; y: number; z: number }): string {
  const abs = { x: Math.abs(n.x), y: Math.abs(n.y), z: Math.abs(n.z) };
  if (abs.x >= abs.y && abs.x >= abs.z) return n.x > 0 ? "+X面 (右)" : "-X面 (左)";
  if (abs.y >= abs.x && abs.y >= abs.z) return n.y > 0 ? "+Y面 (上)" : "-Y面 (下)";
  return n.z > 0 ? "+Z面 (前)" : "-Z面 (奥)";
}
/**
 * Build a BufferGeometry containing only the coplanar faces of the clicked triangle.
 * Coplanar = same normal direction AND same plane (within tolerances).
 */
function _buildCoplanarHighlight(
  geometry: THREE.BufferGeometry,
  faceIndex: number,
  faceNormal: THREE.Vector3,
): THREE.BufferGeometry {
  const pos = geometry.attributes.position as THREE.BufferAttribute;
  const idx = geometry.index;
  const totalFaces = idx ? idx.count / 3 : pos.count / 3;
  const normal = faceNormal.clone().normalize();

  // Reference vertex of the clicked face for plane constant
  const refI = idx ? idx.getX(faceIndex * 3) : faceIndex * 3;
  const refV = new THREE.Vector3(pos.getX(refI), pos.getY(refI), pos.getZ(refI));
  const d0 = normal.dot(refV);

  const selected: number[] = [];
  const e1 = new THREE.Vector3();
  const e2 = new THREE.Vector3();
  const fn = new THREE.Vector3();
  const fv0 = new THREE.Vector3();

  for (let f = 0; f < totalFaces; f++) {
    const i0 = idx ? idx.getX(f * 3) : f * 3;
    const i1 = idx ? idx.getX(f * 3 + 1) : f * 3 + 1;
    const i2 = idx ? idx.getX(f * 3 + 2) : f * 3 + 2;

    fv0.set(pos.getX(i0), pos.getY(i0), pos.getZ(i0));
    e1.set(pos.getX(i1) - fv0.x, pos.getY(i1) - fv0.y, pos.getZ(i1) - fv0.z);
    e2.set(pos.getX(i2) - fv0.x, pos.getY(i2) - fv0.y, pos.getZ(i2) - fv0.z);
    fn.crossVectors(e1, e2).normalize();

    // Same normal direction (dot > 0.99) AND same plane (d within tolerance)
    if (Math.abs(fn.dot(normal)) > 0.99) {
      const d = normal.dot(fv0);
      if (Math.abs(d - d0) < 0.5) {
        selected.push(f);
      }
    }
  }

  // Build geometry with slight offset to avoid z-fighting
  const offset = 0.02;
  const positions = new Float32Array(selected.length * 9);
  for (let s = 0; s < selected.length; s++) {
    const f = selected[s]!;
    for (let v = 0; v < 3; v++) {
      const vi = idx ? idx.getX(f * 3 + v) : f * 3 + v;
      positions[s * 9 + v * 3] = pos.getX(vi) + normal.x * offset;
      positions[s * 9 + v * 3 + 1] = pos.getY(vi) + normal.y * offset;
      positions[s * 9 + v * 3 + 2] = pos.getZ(vi) + normal.z * offset;
    }
  }

  const hlGeo = new THREE.BufferGeometry();
  hlGeo.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  hlGeo.computeVertexNormals();
  return hlGeo;
}
/**
 * Compute bounding dimensions and area of a highlighted face group.
 */
function _computeFaceGroupInfo(
  hlGeo: THREE.BufferGeometry,
  faceNormal: THREE.Vector3,
): { width: number; height: number; area: number } {
  const pos = hlGeo.attributes.position as THREE.BufferAttribute;
  const count = pos.count;
  if (count === 0) return { width: 0, height: 0, area: 0 };

  const n = faceNormal.clone().normalize();
  const up = Math.abs(n.y) < 0.9 ? new THREE.Vector3(0, 1, 0) : new THREE.Vector3(1, 0, 0);
  const u = new THREE.Vector3().crossVectors(n, up).normalize();
  const v = new THREE.Vector3().crossVectors(n, u).normalize();

  let minU = Infinity, maxU = -Infinity, minV = Infinity, maxV = -Infinity;
  const p = new THREE.Vector3();
  for (let i = 0; i < count; i++) {
    p.set(pos.getX(i), pos.getY(i), pos.getZ(i));
    const pu = p.dot(u), pv = p.dot(v);
    if (pu < minU) minU = pu;
    if (pu > maxU) maxU = pu;
    if (pv < minV) minV = pv;
    if (pv > maxV) maxV = pv;
  }

  let area = 0;
  const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
  const ab = new THREE.Vector3(), ac = new THREE.Vector3();
  for (let i = 0; i < count; i += 3) {
    a.set(pos.getX(i), pos.getY(i), pos.getZ(i));
    b.set(pos.getX(i + 1), pos.getY(i + 1), pos.getZ(i + 1));
    c.set(pos.getX(i + 2), pos.getY(i + 2), pos.getZ(i + 2));
    ab.subVectors(b, a);
    ac.subVectors(c, a);
    area += ab.cross(ac).length() / 2;
  }

  return {
    width: +(maxU - minU).toFixed(2),
    height: +(maxV - minV).toFixed(2),
    area: +area.toFixed(2),
  };
}

/**
 * Detect cylindrical surface (holes/bosses) by flood-filling from a non-planar face.
 */
function _detectCylinder(
  geometry: THREE.BufferGeometry,
  startFaceIndex: number,
): { diameter: number; depth: number; axis: string; center: THREE.Vector3; highlightGeo: THREE.BufferGeometry } | null {
  const pos = geometry.attributes.position as THREE.BufferAttribute;
  const idx = geometry.index;
  const totalFaces = idx ? idx.count / 3 : pos.count / 3;
  const getVI = (f: number, v: number) => idx ? idx.getX(f * 3 + v) : f * 3 + v;

  const _e1 = new THREE.Vector3(), _e2 = new THREE.Vector3();
  const faceNormalOf = (f: number): THREE.Vector3 => {
    const i0 = getVI(f, 0), i1 = getVI(f, 1), i2 = getVI(f, 2);
    _e1.set(pos.getX(i1) - pos.getX(i0), pos.getY(i1) - pos.getY(i0), pos.getZ(i1) - pos.getZ(i0));
    _e2.set(pos.getX(i2) - pos.getX(i0), pos.getY(i2) - pos.getY(i0), pos.getZ(i2) - pos.getZ(i0));
    return new THREE.Vector3().crossVectors(_e1, _e2).normalize();
  };

  // Only detect cylinders for non-axis-aligned faces
  const sn = faceNormalOf(startFaceIndex);
  if (Math.abs(sn.x) > 0.85 || Math.abs(sn.y) > 0.85 || Math.abs(sn.z) > 0.85) return null;

  // Build adjacency via position-based edge keys
  const R = 10000;
  const posKey = (vi: number) =>
    `${Math.round(pos.getX(vi) * R)}_${Math.round(pos.getY(vi) * R)}_${Math.round(pos.getZ(vi) * R)}`;
  const edgeKey = (vi1: number, vi2: number) => {
    const k1 = posKey(vi1), k2 = posKey(vi2);
    return k1 < k2 ? k1 + "|" + k2 : k2 + "|" + k1;
  };

  const edgeToFaces = new Map<string, number[]>();
  for (let f = 0; f < totalFaces; f++) {
    const i0 = getVI(f, 0), i1 = getVI(f, 1), i2 = getVI(f, 2);
    for (const [a, b] of [[i0, i1], [i1, i2], [i2, i0]] as [number, number][]) {
      const key = edgeKey(a, b);
      const arr = edgeToFaces.get(key);
      if (arr) arr.push(f);
      else edgeToFaces.set(key, [f]);
    }
  }

  const adj = new Map<number, Set<number>>();
  for (const faces of edgeToFaces.values()) {
    for (let i = 0; i < faces.length; i++)
      for (let j = i + 1; j < faces.length; j++) {
        if (!adj.has(faces[i]!)) adj.set(faces[i]!, new Set());
        if (!adj.has(faces[j]!)) adj.set(faces[j]!, new Set());
        adj.get(faces[i]!)!.add(faces[j]!);
        adj.get(faces[j]!)!.add(faces[i]!);
      }
  }

  // Flood fill connected curved faces
  const visited = new Set<number>([startFaceIndex]);
  const queue = [startFaceIndex];
  while (queue.length > 0 && visited.size < 800) {
    const f = queue.shift()!;
    const nb = adj.get(f);
    if (!nb) continue;
    for (const nf of nb) {
      if (visited.has(nf)) continue;
      const nn = faceNormalOf(nf);
      if (Math.abs(nn.x) > 0.85 || Math.abs(nn.y) > 0.85 || Math.abs(nn.z) > 0.85) continue;
      visited.add(nf);
      queue.push(nf);
    }
  }

  if (visited.size < 4) return null;

  // Determine cylinder axis from normal distribution
  const nSum = new THREE.Vector3();
  for (const f of visited) {
    const fn = faceNormalOf(f);
    nSum.x += Math.abs(fn.x);
    nSum.y += Math.abs(fn.y);
    nSum.z += Math.abs(fn.z);
  }
  nSum.divideScalar(visited.size);

  let axisLabel: string, axisIdx: number;
  if (nSum.x <= nSum.y && nSum.x <= nSum.z) { axisLabel = "X"; axisIdx = 0; }
  else if (nSum.y <= nSum.x && nSum.y <= nSum.z) { axisLabel = "Y"; axisIdx = 1; }
  else { axisLabel = "Z"; axisIdx = 2; }

  const bbox = new THREE.Box3();
  for (const f of visited) {
    for (let v = 0; v < 3; v++) {
      const vi = getVI(f, v);
      bbox.expandByPoint(new THREE.Vector3(pos.getX(vi), pos.getY(vi), pos.getZ(vi)));
    }
  }
  const size = bbox.getSize(new THREE.Vector3());
  const center = bbox.getCenter(new THREE.Vector3());
  const sArr = [size.x, size.y, size.z];
  const depth = sArr[axisIdx]!;
  const perp = sArr.filter((_, i) => i !== axisIdx);
  const diameter = Math.max(...perp);

  // Build highlight geometry (offset each face along its own normal)
  const positions = new Float32Array(visited.size * 9);
  let pIdx = 0;
  for (const f of visited) {
    const fn = faceNormalOf(f);
    const nx = fn.x * 0.03, ny = fn.y * 0.03, nz = fn.z * 0.03;
    for (let v = 0; v < 3; v++) {
      const vi = getVI(f, v);
      positions[pIdx++] = pos.getX(vi) + nx;
      positions[pIdx++] = pos.getY(vi) + ny;
      positions[pIdx++] = pos.getZ(vi) + nz;
    }
  }
  const hlGeo = new THREE.BufferGeometry();
  hlGeo.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  hlGeo.computeVertexNormals();

  return { diameter: +diameter.toFixed(2), depth: +depth.toFixed(2), axis: axisLabel, center, highlightGeo: hlGeo };
}

/* ---------- Selection Info Panel ---------- */

function SelectionPanel({ selection, measureResult }: { selection: SelectionInfo | null; measureResult: MeasureResult | null }) {
  if (!selection && !measureResult) return null;
  return (
    <div className="absolute top-4 left-4 rounded bg-gray-900/80 p-3 text-xs text-gray-200 max-w-64 space-y-1">
      {selection && (
        <>
          <p className="font-semibold text-orange-400 mb-1">
            {selection.type === "cylinder" ? "🕳️ 穴/円柱面" : "📐 面"}: {selection.meshName}
          </p>
          {selection.featureId && (
            <p className="text-cyan-400">Feature: {selection.featureId}</p>
          )}
          {selection.cylinderInfo && (
            <div className="border-l-2 border-cyan-500 pl-2 my-1">
              <p className="text-cyan-300 font-semibold">穴の情報</p>
              <p>直径: Φ{selection.cylinderInfo.diameter} mm</p>
              <p>深さ: {selection.cylinderInfo.depth} mm</p>
              <p>軸方向: {selection.cylinderInfo.axis}軸</p>
            </div>
          )}
          {selection.faceDimensions && (
            <div className="border-l-2 border-orange-500 pl-2 my-1">
              <p className="text-orange-300 font-semibold">面の寸法</p>
              <p>{selection.faceDimensions.width} × {selection.faceDimensions.height} mm</p>
              <p>面積: {selection.faceDimensions.area} mm²</p>
            </div>
          )}
          <p>
            位置: ({selection.position.x}, {selection.position.y}, {selection.position.z})
          </p>
          <p className="text-gray-400">
            全体: W{selection.dimensions.width} × H{selection.dimensions.height} × D{selection.dimensions.depth}
          </p>
          {selection.normal && (
            <p className="text-cyan-300">面方向: {_normalToLabel(selection.normal)}</p>
          )}
        </>
      )}
      {measureResult && (
        <div className="border-t border-gray-600 pt-1 mt-1">
          <p className="font-semibold text-amber-400">📏 距離計測</p>
          <p className="text-lg font-bold text-amber-300">{measureResult.distance.toFixed(2)} mm</p>
        </div>
      )}
    </div>
  );
}

/* ---------- Dimension Mode Labels ---------- */

const DIM_MODE_LABELS: Record<DimensionMode, string> = {
  off: "寸法: OFF",
  selected: "寸法: 選択",
  all: "寸法: 全体",
};

/* ---------- Measure Distance Line ---------- */

function MeasureDistanceLine({
  p1,
  p2,
  distance,
}: {
  p1: [number, number, number];
  p2: [number, number, number];
  distance: number;
}) {
  const mid: [number, number, number] = [
    (p1[0] + p2[0]) / 2,
    (p1[1] + p2[1]) / 2,
    (p1[2] + p2[2]) / 2,
  ];
  return (
    <group>
      <Line points={[p1, p2]} color="#f59e0b" lineWidth={2} dashed dashScale={20} />
      <mesh position={p1}>
        <sphereGeometry args={[0.4]} />
        <meshBasicMaterial color="#f59e0b" />
      </mesh>
      <mesh position={p2}>
        <sphereGeometry args={[0.4]} />
        <meshBasicMaterial color="#f59e0b" />
      </mesh>
      <Html position={mid} center style={{ pointerEvents: "none" }}>
        <span className="rounded bg-amber-600/90 px-2 py-1 text-xs font-bold text-white whitespace-nowrap shadow">
          {distance.toFixed(2)} mm
        </span>
      </Html>
    </group>
  );
}

/* ---------- Main Viewer ---------- */

export function Viewer3D({
  gltfUrl,
  onDownloadStep,
  onSelectionChange,
}: Viewer3DProps) {
  const [dimensionMode, setDimensionMode] = useState<DimensionMode>("off");
  const [selection, setSelection] = useState<SelectionInfo | null>(null);
  const [measureMode, setMeasureMode] = useState(false);
  const [measureResult, setMeasureResult] = useState<MeasureResult | null>(null);

  const handleSelectionChange = useCallback(
    (info: SelectionInfo | null) => {
      setSelection(info);
      onSelectionChange?.(info);
    },
    [onSelectionChange],
  );

  const cycleDimensionMode = useCallback(() => {
    setDimensionMode((prev) => {
      const modes: DimensionMode[] = ["off", "selected", "all"];
      return modes[(modes.indexOf(prev) + 1) % modes.length] ?? "off";
    });
  }, []);

  const toggleMeasureMode = useCallback(() => {
    setMeasureMode((prev) => !prev);
  }, []);

  return (
    <div className="relative h-full w-full bg-gray-900" role="img" aria-label="3Dモデルビューア">
      <Canvas camera={{ position: [5, 5, 5], fov: 50 }} gl={{ antialias: true }}>
        <Suspense fallback={null}>
          {gltfUrl ? (
            <SceneContent
              gltfUrl={gltfUrl}
              dimensionMode={dimensionMode}
              measureMode={measureMode}
              onSelectionChange={handleSelectionChange}
              onMeasureResult={setMeasureResult}
            />
          ) : (
            <>
              <ambientLight intensity={0.6} />
              <directionalLight position={[10, 10, 5]} intensity={1.2} />
              <directionalLight position={[-5, -5, -5]} intensity={0.4} />
              <Center>
                <ModelPlaceholder />
              </Center>
              <OrbitControls makeDefault />
              <Grid
                args={[20, 20]}
                cellSize={1}
                cellThickness={0.5}
                cellColor="#4a5568"
                sectionSize={5}
                sectionThickness={1}
                sectionColor="#718096"
                fadeDistance={25}
                infiniteGrid
              />
            </>
          )}
        </Suspense>
      </Canvas>

      <SelectionPanel selection={selection} measureResult={measureResult} />

      <div className="absolute bottom-4 left-4 flex items-center gap-3">
        <span className="rounded bg-gray-800/80 px-3 py-1.5 text-xs text-gray-300">
          {measureMode ? "面を2つクリックして距離を計測" : "クリック: 面選択 / ドラッグ: 回転 / スクロール: ズーム"}
        </span>
        {gltfUrl && (
          <button
            type="button"
            onClick={toggleMeasureMode}
            className={`rounded px-3 py-1.5 text-xs font-medium ${
              measureMode
                ? "bg-amber-600 text-white ring-2 ring-amber-400"
                : "bg-gray-700 text-gray-200 hover:bg-gray-600"
            }`}
          >
            📐 距離計測{measureMode ? " ON" : ""}
          </button>
        )}
        {gltfUrl && (
          <button
            type="button"
            onClick={cycleDimensionMode}
            className="rounded bg-gray-700 px-3 py-1.5 text-xs font-medium text-gray-200 hover:bg-gray-600"
          >
            📏 {DIM_MODE_LABELS[dimensionMode]}
          </button>
        )}
        {gltfUrl && onDownloadStep && (
          <button
            type="button"
            onClick={onDownloadStep}
            className="rounded bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700"
          >
            ⬇ STEP ダウンロード
          </button>
        )}
      </div>
      {!gltfUrl && (
        <div className="absolute inset-0 flex items-center justify-center">
          <p className="text-sm text-gray-400">3Dモデルを生成すると表示されます</p>
        </div>
      )}
    </div>
  );
}
