import { Canvas } from "@react-three/fiber";
import { OrbitControls, Stage, Grid, useGLTF } from "@react-three/drei";
import { Suspense } from "react";

interface Viewer3DProps {
  gltfUrl: string;
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

export function Viewer3D({ gltfUrl }: Viewer3DProps) {
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
    </div>
  );
}
