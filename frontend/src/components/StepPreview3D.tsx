import { Suspense, useEffect, useRef, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { Bounds, Grid, OrbitControls, useBounds, useGLTF } from "@react-three/drei";
import * as THREE from "three";
import { API_BASE } from "../config";
import { buildCumulativePreview } from "../utils/cqPreview";
import type { BuildStep } from "./BuildPlanPanel";

// ---------------------------------------------------------------------------
// Inner: GLB model (executed step → cumulative checkpoint from backend)
// ---------------------------------------------------------------------------
function GlbScene({ url }: { url: string }) {
  const gltf = useGLTF(url);
  const bounds = useBounds();
  useEffect(() => {
    bounds.refresh(gltf.scene).fit();
  }, [bounds, gltf.scene]);
  return <primitive object={gltf.scene} />;
}

// ---------------------------------------------------------------------------
// Inner: CSG-computed cumulative geometry (pre-execution)
// ---------------------------------------------------------------------------
function CsgScene({ geometry }: { geometry: THREE.BufferGeometry }) {
  const meshRef = useRef<THREE.Mesh>(null);
  const bounds = useBounds();
  useEffect(() => {
    if (meshRef.current) bounds.refresh(meshRef.current).fit();
  }, [bounds, geometry]);

  return (
    <mesh ref={meshRef} geometry={geometry}>
      <meshStandardMaterial color="#6EA9D7" roughness={0.22} metalness={0.6} />
    </mesh>
  );
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------
interface Props {
  step: BuildStep | null;
  allSteps: BuildStep[];
  planId: string;
  idToken: string;
}

type Mode = "empty" | "loading" | "glb" | "csg";

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export function StepPreview3D({ step, allSteps, planId, idToken }: Props) {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [isFetchingGlb, setIsFetchingGlb] = useState(false);
  const [csgGeo, setCsgGeo] = useState<THREE.BufferGeometry | null>(null);
  const [csgNotes, setCsgNotes] = useState<string[]>([]);
  const [isComputingCsg, setIsComputingCsg] = useState(false);

  // --- Fetch presigned URL when step has a saved checkpoint ---
  useEffect(() => {
    if (!step?.checkpoint_glb_key) {
      setPreviewUrl(null);
      return;
    }
    let cancelled = false;
    setIsFetchingGlb(true);
    fetch(`${API_BASE}/build-plans/${planId}/preview/${step.step_seq}`, {
      headers: { Authorization: `Bearer ${idToken}` },
    })
      .then((r) => r.json())
      .then((data) => {
        if (!cancelled) {
          setPreviewUrl((data as { preview_url?: string }).preview_url ?? null);
          setIsFetchingGlb(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setPreviewUrl(null);
          setIsFetchingGlb(false);
        }
      });
    return () => { cancelled = true; };
  }, [step?.step_seq, step?.checkpoint_glb_key, planId, idToken]);

  // --- Compute CSG cumulative preview for unexecuted steps ---
  useEffect(() => {
    if (!step || step.checkpoint_glb_key) {
      setCsgGeo(null);
      setCsgNotes([]);
      return;
    }
    let cancelled = false;
    setIsComputingCsg(true);
    setCsgGeo(null);

    // Yield to let spinner render, then compute
    const timer = setTimeout(() => {
      if (cancelled) return;
      try {
        const result = buildCumulativePreview(allSteps, step.step_seq);
        if (!cancelled) {
          setCsgGeo(result.geometry);
          setCsgNotes(result.notes);
        }
      } catch (e) {
        console.warn("[StepPreview3D] CSG error:", e);
      } finally {
        if (!cancelled) setIsComputingCsg(false);
      }
    }, 20);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  // allSteps の内容変化にも反応させるためキー化
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step?.step_seq, step?.checkpoint_glb_key,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    allSteps.map((s) => s.step_seq + s.status + s.cq_code).join("|"),
  ]);

  // --- Cleanup geometry on unmount ---
  useEffect(() => () => { csgGeo?.dispose(); }, [csgGeo]);

  // --- Display mode ---
  const mode: Mode = (() => {
    if (!step) return "empty";
    if (isFetchingGlb || isComputingCsg) return "loading";
    if (previewUrl) return "glb";
    return "csg";
  })();

  // --- Status badge ---
  const badge = (() => {
    if (!step) return null;
    if (step.status === "completed")
      return <span className="ml-auto shrink-0 text-[10px] text-green-400">✓ 実行済み</span>;
    if (step.status === "modified")
      return <span className="ml-auto shrink-0 text-[10px] text-amber-400">✎ 修正済み</span>;
    if (mode === "csg")
      return <span className="ml-auto shrink-0 text-[10px] text-blue-400">ブラウザ CSG プレビュー</span>;
    return null;
  })();

  return (
    <div className="flex h-full flex-col bg-gray-950">
      {/* Label bar */}
      {step && (
        <div className="flex shrink-0 items-center gap-2 border-b border-gray-800 bg-gray-900 px-3 py-1.5">
          <span className="font-mono text-[10px] text-gray-500">{step.step_seq}</span>
          <span className="truncate text-[10px] text-gray-300">{step.step_name}</span>
          {badge}
        </div>
      )}

      {/* 3D viewport */}
      <div className="relative min-h-0 flex-1">
        {mode === "empty" && (
          <div className="flex h-full items-center justify-center">
            <p className="text-[11px] text-gray-600">ステップを選択すると 3D プレビューが表示されます</p>
          </div>
        )}

        {mode === "loading" && (
          <div className="flex h-full flex-col items-center justify-center gap-2">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-gray-700 border-t-indigo-400" />
            <p className="text-[10px] text-gray-600">
              {isComputingCsg ? "CSG 演算中..." : "プレビュー読み込み中..."}
            </p>
          </div>
        )}

        {(mode === "glb" || mode === "csg") && (
          <Canvas
            style={{ position: "absolute", inset: 0 }}
            camera={{ position: [120, 100, 150], fov: 45 }}
            gl={{ antialias: true }}
          >
            <color attach="background" args={["#0f172a"]} />
            <ambientLight intensity={0.5} />
            <directionalLight position={[80, 120, 60]} intensity={1.3} />
            <directionalLight position={[-50, 40, -80]} intensity={0.3} />
            <Grid
              infiniteGrid
              fadeDistance={500}
              cellSize={5}
              sectionSize={25}
              sectionColor="#1e3a5f"
              cellColor="#1a2332"
            />
            <Bounds fit clip observe margin={1.5}>
              <Suspense fallback={null}>
                {mode === "glb" && <GlbScene url={previewUrl!} />}
                {mode === "csg" && csgGeo && <CsgScene geometry={csgGeo} />}
              </Suspense>
            </Bounds>
            <OrbitControls makeDefault />
          </Canvas>
        )}
      </div>

      {/* Approximation notes */}
      {csgNotes.length > 0 && (
        <div className="shrink-0 border-t border-gray-800 bg-gray-900 px-3 py-1.5">
          {csgNotes.map((n, i) => (
            <p key={i} className="text-[9px] text-gray-500">
              ⚠ {n}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}
