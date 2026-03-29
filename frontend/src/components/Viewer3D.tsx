import { Canvas, type ThreeEvent } from "@react-three/fiber";
import { OrbitControls, Grid, useGLTF, Center, Html, Line, Bounds, useBounds } from "@react-three/drei";
import { Suspense, useState, useMemo, useRef, useCallback, useEffect } from "react";
import * as THREE from "three";

/* ---------- Shared types ---------- */

export interface SelectionInfo {
  meshName: string;
  position: { x: number; y: number; z: number };
  dimensions: { width: number; height: number; depth: number };
  faceIndex?: number;
}

interface ConfidenceEntry {
  featureId: string;
  score: number;
}

interface Viewer3DProps {
  gltfUrl: string;
  confidenceMap?: Record<string, number>;
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
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const materialsMap = useRef(new Map<number, THREE.Material | THREE.Material[]>());

  const clonedScene = useMemo(() => {
    const clone = scene.clone(true);
    clone.traverse((child) => {
      if ((child as THREE.Mesh).isMesh) {
        const mesh = child as THREE.Mesh;
        // Compute normals if missing (trimesh GLB often lacks them)
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

  const restoreSelection = useCallback(() => {
    if (selectedId != null) {
      const prev = clonedScene.getObjectById(selectedId) as THREE.Mesh | undefined;
      const saved = materialsMap.current.get(selectedId);
      if (prev && saved) {
        prev.material = saved as THREE.Material;
      }
      materialsMap.current.delete(selectedId);
    }
  }, [selectedId, clonedScene]);

  const handleClick = useCallback(
    (e: ThreeEvent<MouseEvent>) => {
      e.stopPropagation();
      const mesh = e.object as THREE.Mesh;
      if (!mesh.isMesh) return;

      restoreSelection();

      // Toggle off if clicking same mesh
      if (mesh.id === selectedId) {
        setSelectedId(null);
        onMeshSelect(null, null);
        return;
      }

      // Save original & apply highlight
      materialsMap.current.set(mesh.id, mesh.material);
      const hlMat = (mesh.material as THREE.Material).clone();
      if ("color" in hlMat) (hlMat as THREE.MeshStandardMaterial).color.set(0xff6600);
      if ("emissive" in hlMat) (hlMat as THREE.MeshStandardMaterial).emissive.set(0x331100);
      hlMat.transparent = true;
      hlMat.opacity = 0.85;
      mesh.material = hlMat;
      setSelectedId(mesh.id);

      const box = new THREE.Box3().setFromObject(mesh);
      const sz = box.getSize(new THREE.Vector3());
      onMeshSelect(
        {
          meshName: mesh.name || `mesh_${mesh.id}`,
          position: {
            x: +e.point.x.toFixed(2),
            y: +e.point.y.toFixed(2),
            z: +e.point.z.toFixed(2),
          },
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
    [selectedId, restoreSelection, onMeshSelect],
  );

  const handleMiss = useCallback(() => {
    restoreSelection();
    setSelectedId(null);
    onMeshSelect(null, null);
  }, [restoreSelection, onMeshSelect]);

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

/* ---------- Selection Info Panel ---------- */

function SelectionPanel({ selection }: { selection: SelectionInfo | null }) {
  if (!selection) return null;
  return (
    <div className="absolute top-4 left-4 rounded bg-gray-900/80 p-3 text-xs text-gray-200 max-w-56">
      <p className="font-semibold text-orange-400 mb-1">選択中: {selection.meshName}</p>
      <p>
        位置: ({selection.position.x}, {selection.position.y}, {selection.position.z})
      </p>
      <p>
        寸法: W{selection.dimensions.width} × H{selection.dimensions.height} × D
        {selection.dimensions.depth}
      </p>
      {selection.faceIndex != null && <p>面 #{selection.faceIndex}</p>}
    </div>
  );
}

/* ---------- Confidence Legend ---------- */

function ConfidenceLegend({ entries }: { entries: ConfidenceEntry[] }) {
  if (entries.length === 0) return null;

  const avg = entries.reduce((s, e) => s + e.score, 0) / entries.length;
  const overallColor =
    avg >= 0.9 ? "bg-green-500" : avg >= 0.7 ? "bg-yellow-400" : "bg-orange-500";

  return (
    <div
      className="absolute top-4 right-4 flex flex-col gap-1 rounded bg-gray-900/80 p-2 text-xs"
      aria-label="確度スコア一覧"
    >
      <p className="font-semibold text-gray-200">
        確度:{" "}
        <span className={`rounded px-1 py-0.5 text-white ${overallColor}`}>
          {(avg * 100).toFixed(0)}%
        </span>
      </p>
      <ul className="mt-1 space-y-0.5">
        {entries.map((e) => {
          const color =
            e.score >= 0.9
              ? "bg-green-500"
              : e.score >= 0.7
                ? "bg-yellow-400"
                : "bg-orange-500";
          return (
            <li key={e.featureId} className="flex items-center gap-2">
              <span className={`h-2 w-2 rounded-full ${color}`} aria-hidden="true" />
              <span className="text-gray-300">{e.featureId}</span>
              <span className="ml-auto text-gray-400">{(e.score * 100).toFixed(0)}%</span>
            </li>
          );
        })}
      </ul>
      <p className="mt-1 text-gray-500 text-[10px]">緑≥90% / 黄70-90% / 橙&lt;70%</p>
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
  confidenceMap = {},
  onDownloadStep,
  onSelectionChange,
}: Viewer3DProps) {
  const [dimensionMode, setDimensionMode] = useState<DimensionMode>("off");
  const [selection, setSelection] = useState<SelectionInfo | null>(null);

  const confidenceEntries: ConfidenceEntry[] = Object.entries(confidenceMap).map(
    ([featureId, score]) => ({ featureId, score }),
  );

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
          クリック: 要素選択 / ドラッグ: 回転 / スクロール: ズーム
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
      <ConfidenceLegend entries={confidenceEntries} />
    </div>
  );
}
