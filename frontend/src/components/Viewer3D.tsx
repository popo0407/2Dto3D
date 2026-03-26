import { Canvas } from "@react-three/fiber";
import { OrbitControls, Stage, Grid, useGLTF } from "@react-three/drei";
import { Suspense } from "react";

interface ConfidenceEntry {
  featureId: string;
  score: number;
}

interface Viewer3DProps {
  gltfUrl: string;
  confidenceMap?: Record<string, number>;
}

function GltfModel({ url }: { url: string }) {
  const { scene } = useGLTF(url);
  return <primitive object={scene} />;
}

function ModelPlaceholder() {
  return (
    <mesh>
      <boxGeometry args={[2, 2, 2]} />
      <meshStandardMaterial color="#94a3b8" wireframe />
    </mesh>
  );
}

/** Feature単位の確度スコアをまとめてバッジ表示する */
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
      <p className="mt-1 text-gray-500 text-[10px]">
        緑≥90% / 黄70-90% / 橙&lt;70%
      </p>
    </div>
  );
}

export function Viewer3D({ gltfUrl, confidenceMap = {} }: Viewer3DProps) {
  const confidenceEntries: ConfidenceEntry[] = Object.entries(confidenceMap).map(
    ([featureId, score]) => ({ featureId, score }),
  );

  return (
    <div className="relative h-full w-full bg-gray-900" role="img" aria-label="3Dモデルビューア">
      <Canvas
        camera={{ position: [5, 5, 5], fov: 50 }}
        gl={{ antialias: true }}
      >
        <Suspense fallback={null}>
          <Stage environment="city" intensity={0.5}>
            {gltfUrl ? <GltfModel url={gltfUrl} /> : <ModelPlaceholder />}
          </Stage>
        </Suspense>
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
      </Canvas>
      <div className="absolute bottom-4 left-4 rounded bg-gray-800/80 px-3 py-1.5 text-xs text-gray-300">
        マウスドラッグ: 回転 / スクロール: ズーム / 右クリック: パン
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
