import { Suspense, useEffect, useMemo, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { Bounds, Grid, OrbitControls, useBounds, useGLTF } from "@react-three/drei";
import { API_BASE } from "../config";
import type { BuildStep } from "./BuildPlanPanel";

// ---------------------------------------------------------------------------
// Inner: GLB model (executed step checkpoint)
// ---------------------------------------------------------------------------
function GlbScene({ url }: { url: string }) {
  const gltf = useGLTF(url);
  const scene = useMemo(() => gltf.scene.clone(true), [gltf.scene]);
  const bounds = useBounds();
  useEffect(() => {
    bounds.refresh(scene).fit();
  }, [bounds, scene]);
  return <primitive object={scene} />;
}

// ---------------------------------------------------------------------------
// Inner: parametric geometry for base_body (pre-execution)
// ---------------------------------------------------------------------------
function BaseBodyScene({ step }: { step: BuildStep }) {
  const bounds = useBounds();
  useEffect(() => {
    bounds.refresh().fit();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bounds, step.step_seq]);

  const p = step.parameters;
  const v = (k: string): number => {
    const e = p[k] as { value: number } | undefined;
    return e ? Number(e.value) : 0;
  };

  const diameter = v("diameter") || v("outer_diameter");
  if (diameter > 0) {
    const r = diameter / 2;
    const h = v("height") || 10;
    return (
      <mesh>
        <cylinderGeometry args={[r, r, h, 48]} />
        <meshStandardMaterial color="#6EA9D7" roughness={0.25} metalness={0.55} />
      </mesh>
    );
  }

  // Box: CQ box(length, width, height) → length=X, width=Y, height=Z
  // Three.js Y-up → BoxGeometry(length, height_Z, width_Y)
  const length = v("width") || v("length") || 50;
  const width = v("height") || v("depth") || 30; // CQ Y
  const height = v("depth") || v("thickness") || 10; // CQ Z (up)

  return (
    <mesh>
      <boxGeometry args={[length, height, width]} />
      <meshStandardMaterial color="#6EA9D7" roughness={0.25} metalness={0.55} />
    </mesh>
  );
}

// ---------------------------------------------------------------------------
// Notes per step type
// ---------------------------------------------------------------------------
const STEP_TYPE_NOTE: Record<string, string> = {
  hole_through: "穴あけは形状演算が必要なため、実行後にプレビューが表示されます",
  hole_blind: "止め穴は形状演算が必要なため、実行後にプレビューが表示されます",
  tapped_hole: "ネジ穴は形状演算が必要なため、実行後にプレビューが表示されます",
  fillet: "R 面取りは形状演算が必要なため、実行後にプレビューが表示されます",
  chamfer: "C 面取りは形状演算が必要なため、実行後にプレビューが表示されます",
  slot: "長穴は形状演算が必要なため、実行後にプレビューが表示されます",
  pocket: "ポケット加工は形状演算が必要なため、実行後にプレビューが表示されます",
};

// ---------------------------------------------------------------------------
// Exported component
// ---------------------------------------------------------------------------
interface Props {
  step: BuildStep | null;
  planId: string;
  idToken: string;
}

type Mode = "empty" | "loading" | "glb" | "parametric" | "note";

export function StepPreview3D({ step, planId, idToken }: Props) {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [isFetching, setIsFetching] = useState(false);

  // Fetch presigned URL when step has a saved checkpoint GLB
  useEffect(() => {
    if (!step?.checkpoint_glb_key) {
      setPreviewUrl(null);
      return;
    }
    let cancelled = false;
    setIsFetching(true);
    fetch(`${API_BASE}/build-plans/${planId}/preview/${step.step_seq}`, {
      headers: { Authorization: `Bearer ${idToken}` },
    })
      .then((r) => r.json())
      .then((data) => {
        if (!cancelled) {
          setPreviewUrl((data as { preview_url?: string }).preview_url ?? null);
          setIsFetching(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setPreviewUrl(null);
          setIsFetching(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [step?.step_seq, step?.checkpoint_glb_key, planId, idToken]);

  const mode: Mode = (() => {
    if (!step) return "empty";
    if (isFetching) return "loading";
    if (previewUrl) return "glb";
    if (step.step_type === "base_body") return "parametric";
    return "note";
  })();

  return (
    <div className="flex h-full flex-col bg-gray-950">
      {/* Label bar */}
      {step && (
        <div className="flex shrink-0 items-center gap-2 border-b border-gray-800 bg-gray-900 px-3 py-1.5">
          <span className="font-mono text-[10px] text-gray-500">{step.step_seq}</span>
          <span className="truncate text-[10px] text-gray-300">{step.step_name}</span>
          {step.status === "completed" && (
            <span className="ml-auto shrink-0 text-[10px] text-green-400">✓ 実行済み</span>
          )}
          {step.status === "modified" && (
            <span className="ml-auto shrink-0 text-[10px] text-amber-400">✎ 修正済み（未実行）</span>
          )}
          {mode === "note" && step.status === "planned" && (
            <span className="ml-auto shrink-0 text-[10px] text-gray-500">実行後に表示</span>
          )}
          {mode === "parametric" && (
            <span className="ml-auto shrink-0 text-[10px] text-blue-400">パラメトリック表示</span>
          )}
        </div>
      )}

      {/* Content */}
      <div className="relative flex-1 min-h-0">
        {mode === "empty" && (
          <div className="flex h-full items-center justify-center">
            <p className="text-[11px] text-gray-600">ステップを選択すると 3D プレビューが表示されます</p>
          </div>
        )}

        {mode === "loading" && (
          <div className="flex h-full items-center justify-center">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-gray-700 border-t-indigo-400" />
          </div>
        )}

        {mode === "note" && (
          <div className="flex h-full items-center justify-center p-6 text-center">
            <div>
              <p className="text-xs text-gray-400">
                {STEP_TYPE_NOTE[step!.step_type] ?? "実行後にプレビューが表示されます"}
              </p>
              <p className="mt-2 text-[10px] text-gray-600">
                「Step {step!.step_seq} から実行」でプレビューを生成できます
              </p>
            </div>
          </div>
        )}

        {(mode === "glb" || mode === "parametric") && (
          <Canvas
            style={{ position: "absolute", inset: 0 }}
            camera={{ position: [120, 100, 150], fov: 45 }}
            gl={{ antialias: true }}
          >
            <color attach="background" args={["#0f172a"]} />
            <ambientLight intensity={0.55} />
            <directionalLight position={[80, 120, 60]} intensity={1.2} />
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
                {mode === "parametric" && <BaseBodyScene step={step!} />}
              </Suspense>
            </Bounds>
            <OrbitControls makeDefault />
          </Canvas>
        )}
      </div>
    </div>
  );
}
