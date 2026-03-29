import { Canvas, type ThreeEvent } from "@react-three/fiber";
import { OrbitControls, Grid, useGLTF, Center, Html, Line, Bounds, useBounds } from "@react-three/drei";
import { Suspense, useState, useMemo, useRef, useCallback, useEffect } from "react";
import * as THREE from "three";

/* ---------- Shared types ---------- */

export type SelectionType = "face" | "edge" | "mesh";

export interface SelectionInfo {
  type: SelectionType;
  meshName: string;
  featureId?: string;
  position: { x: number; y: number; z: number };
  normal?: { x: number; y: number; z: number };
  dimensions: { width: number; height: number; depth: number };
  faceIndex?: number;
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
}: {
  url: string;
  onMeshSelect: (info: SelectionInfo | null, mesh: THREE.Object3D | null) => void;
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

      clearHighlight();

      // Build coplanar face overlay
      const hlGeo = _buildCoplanarHighlight(mesh.geometry, e.faceIndex, e.face.normal);
      const hlMat = new THREE.MeshBasicMaterial({
        color: 0xff6600,
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
      const edgeMat = new THREE.LineBasicMaterial({ color: 0xffaa00, linewidth: 2 });
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
          type: "face",
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
        },
        mesh,
      );
    },
    [clearHighlight, onMeshSelect],
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
  onSelectionChange,
}: {
  gltfUrl: string;
  dimensionMode: DimensionMode;
  onSelectionChange: (info: SelectionInfo | null) => void;
}) {
  const [selectedMesh, setSelectedMesh] = useState<THREE.Object3D | null>(null);
  const sceneRootRef = useRef<THREE.Group>(null);

  const handleMeshSelect = useCallback(
    (info: SelectionInfo | null, mesh: THREE.Object3D | null) => {
      setSelectedMesh(mesh);
      onSelectionChange(info);
    },
    [onSelectionChange],
  );

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
            <SelectableModel url={gltfUrl} onMeshSelect={handleMeshSelect} />
          </group>
        </Center>
      </Bounds>
      {dimensionTarget && <DimensionLines target={dimensionTarget} />}
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
/* ---------- Selection Info Panel ---------- */

function SelectionPanel({ selection }: { selection: SelectionInfo | null }) {
  if (!selection) return null;
  return (
    <div className="absolute top-4 left-4 rounded bg-gray-900/80 p-3 text-xs text-gray-200 max-w-56">
      <p className="font-semibold text-orange-400 mb-1">選択中: {selection.meshName}</p>
      {selection.featureId && (
        <p className="text-cyan-400">Feature: {selection.featureId}</p>
      )}
      <p>
        位置: ({selection.position.x}, {selection.position.y}, {selection.position.z})
      </p>
      <p>
        寸法: W{selection.dimensions.width} × H{selection.dimensions.height} × D
        {selection.dimensions.depth}
      </p>
      {selection.normal && (
        <p className="text-cyan-300">面方向: {_normalToLabel(selection.normal)}</p>
      )}
      {selection.faceIndex != null && <p>面 #{selection.faceIndex}</p>}
    </div>
  );
}

/* ---------- Dimension Mode Labels ---------- */

const DIM_MODE_LABELS: Record<DimensionMode, string> = {
  off: "寸法: OFF",
  selected: "寸法: 選択",
  all: "寸法: 全体",
};

/* ---------- Main Viewer ---------- */

export function Viewer3D({
  gltfUrl,
  onDownloadStep,
  onSelectionChange,
}: Viewer3DProps) {
  const [dimensionMode, setDimensionMode] = useState<DimensionMode>("off");
  const [selection, setSelection] = useState<SelectionInfo | null>(null);

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

  return (
    <div className="relative h-full w-full bg-gray-900" role="img" aria-label="3Dモデルビューア">
      <Canvas camera={{ position: [5, 5, 5], fov: 50 }} gl={{ antialias: true }}>
        <Suspense fallback={null}>
          {gltfUrl ? (
            <SceneContent
              gltfUrl={gltfUrl}
              dimensionMode={dimensionMode}
              onSelectionChange={handleSelectionChange}
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

      <SelectionPanel selection={selection} />

      <div className="absolute bottom-4 left-4 flex items-center gap-3">
        <span className="rounded bg-gray-800/80 px-3 py-1.5 text-xs text-gray-300">
          クリック: 面選択 / ドラッグ: 回転 / スクロール: ズーム
        </span>
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
