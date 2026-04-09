import { useState, useRef, useMemo } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import { Brush, Evaluator, SUBTRACTION } from "three-bvh-csg";

/* ---------- Types ---------- */

export interface VerificationElement {
  element_seq: string;
  element_type: string;
  feature_label: string;
  dimensions: Record<string, number | null>;
  position: Record<string, number>;
  orientation: string;
  confidence: number;
  is_verified: boolean;
}

interface VerificationIteration {
  iteration: number;
  elements: VerificationElement[];
  timestamp: number;
}

interface VerificationPanelProps {
  sessionId: string;
  elements: VerificationElement[];
  iterations: VerificationIteration[];
  isVerifying: boolean;
  currentIteration: number;
  maxIterations: number;
  /** Whether the final 3D model is being generated after verification */
  isBuildingFinal?: boolean;
  /** Currently highlighted element seq */
  highlightedElement?: string | null;
  /** Callback when an element is clicked in the list */
  onElementClick?: (elementSeq: string | null) => void;
  /** Callback when an element is double-clicked in the list (insert into comment) */
  onElementDoubleClick?: (elementLabel: string) => void;
}

/* ---------- Confidence helpers ---------- */

function confidenceColor(c: number): string {
  if (c >= 0.85) return "bg-green-500";
  if (c >= 0.6) return "bg-yellow-500";
  return "bg-red-500";
}

function confidenceTextColor(c: number): string {
  if (c >= 0.85) return "text-green-700";
  if (c >= 0.6) return "text-yellow-700";
  return "text-red-700";
}

function confidenceBadge(c: number): string {
  if (c >= 0.85) return "✓ 確定";
  if (c >= 0.6) return "△ 要確認";
  return "✗ 低確度";
}

/* ---------- Orientation → rotation ---------- */

function orientationToEuler(orient: string): THREE.Euler {
  switch (orient) {
    case "+Z": case "-Z":
      return new THREE.Euler(Math.PI / 2, 0, 0);
    case "+X": case "-X":
      return new THREE.Euler(0, 0, Math.PI / 2);
    case "+Y": case "-Y":
      return new THREE.Euler(0, 0, 0);
    default:
      return new THREE.Euler(Math.PI / 2, 0, 0);
  }
}

/* ---------- CSG Preview with boolean subtraction ---------- */

function buildCSGMesh(elements: VerificationElement[]): THREE.BufferGeometry | null {
  const baseElements = elements.filter((e) => e.element_type === "box");
  const holeElements = elements.filter((e) => e.element_type === "hole");

  if (baseElements.length === 0) return null;

  const base = baseElements[0];
  if (!base) return null;
  const w = (base.dimensions?.width as number) ?? 10;
  const h = (base.dimensions?.height as number) ?? 10;
  const d = (base.dimensions?.depth as number) ?? 10;

  const boxGeo = new THREE.BoxGeometry(w, h, d);
  let result = new Brush(boxGeo);
  result.position.set(
    base.position?.x ?? 0,
    base.position?.y ?? 0,
    base.position?.z ?? 0,
  );
  result.updateMatrixWorld(true);

  const evaluator = new Evaluator();

  for (const hole of holeElements) {
    const diameter = (hole.dimensions?.diameter as number) ?? 6;
    const depth = (hole.dimensions?.depth as number) ?? d + 2;
    const cylGeo = new THREE.CylinderGeometry(
      diameter / 2, diameter / 2, depth + 2, 32,
    );

    const holeBrush = new Brush(cylGeo);
    holeBrush.position.set(
      hole.position?.x ?? 0,
      hole.position?.y ?? 0,
      hole.position?.z ?? 0,
    );
    holeBrush.rotation.copy(orientationToEuler(hole.orientation));
    holeBrush.updateMatrixWorld(true);

    try {
      result = evaluator.evaluate(result, holeBrush, SUBTRACTION);
    } catch {
      continue;
    }
  }

  return result.geometry;
}

function CSGPreview({ elements, highlightedElement }: { elements: VerificationElement[]; highlightedElement?: string | null }) {
  const geometry = useMemo(() => buildCSGMesh(elements), [elements]);

  const minConfidence = useMemo(() => {
    if (elements.length === 0) return 0;
    return Math.min(...elements.map((e) => e.confidence));
  }, [elements]);

  const baseElement = elements.find((e) => e.element_type === "box");
  const isBaseHighlighted = highlightedElement && baseElement?.element_seq === highlightedElement;

  const meshColor = isBaseHighlighted
    ? "#818cf8"
    : minConfidence >= 0.85
      ? "#6b9080"
      : minConfidence >= 0.6
        ? "#a68a64"
        : "#a06060";

  if (!geometry) {
    return (
      <mesh>
        <boxGeometry args={[10, 10, 10]} />
        <meshStandardMaterial color="#666" wireframe />
      </mesh>
    );
  }

  return (
    <mesh geometry={geometry}>
      <meshStandardMaterial
        color={meshColor}
        roughness={0.4}
        metalness={0.1}
      />
    </mesh>
  );
}

function HoleMarkers({ elements, highlightedElement }: { elements: VerificationElement[]; highlightedElement?: string | null }) {
  const holes = elements.filter((e) => e.element_type === "hole");
  return (
    <>
      {holes.map((hole) => {
        const diameter = (hole.dimensions?.diameter as number) ?? 6;
        const depth = (hole.dimensions?.depth as number) ?? 10;
        const isHighlighted = highlightedElement === hole.element_seq;
        const color = isHighlighted
          ? "#818cf8"
          : hole.confidence >= 0.85
            ? "#22c55e"
            : hole.confidence >= 0.6
              ? "#eab308"
              : "#ef4444";

        return (
          <mesh
            key={hole.element_seq}
            position={[
              hole.position?.x ?? 0,
              hole.position?.y ?? 0,
              hole.position?.z ?? 0,
            ]}
            rotation={orientationToEuler(hole.orientation)}
          >
            <cylinderGeometry args={[diameter / 2 + 0.3, diameter / 2 + 0.3, depth + 1, 32]} />
            <meshBasicMaterial color={color} wireframe transparent opacity={isHighlighted ? 0.8 : 0.4} />
          </mesh>
        );
      })}
    </>
  );
}

export function ElementPreview({ elements, className, highlightedElement }: { elements: VerificationElement[]; className?: string; highlightedElement?: string | null }) {
  const base = elements.find((e) => e.element_type === "box");
  const maxDim = base
    ? Math.max(
        (base.dimensions?.width as number) ?? 50,
        (base.dimensions?.height as number) ?? 50,
        (base.dimensions?.depth as number) ?? 50,
      )
    : 50;
  const camDist = maxDim * 1.8;

  return (
    <div className={className ?? "h-48 w-full rounded border bg-gray-900"}>
      <Canvas camera={{ position: [camDist, camDist * 0.7, camDist], fov: 45 }}>
        <ambientLight intensity={0.5} />
        <directionalLight position={[camDist, camDist, camDist * 0.5]} intensity={0.8} />
        <CSGPreview elements={elements} highlightedElement={highlightedElement} />
        <HoleMarkers elements={elements} highlightedElement={highlightedElement} />
        <gridHelper args={[maxDim * 3, 20, "#444", "#333"]} />
        <OrbitControls enableDamping />
      </Canvas>
    </div>
  );
}

/* ---------- Main Panel ---------- */

export function VerificationPanel({
  sessionId: _sessionId,
  elements,
  iterations,
  isVerifying,
  currentIteration,
  maxIterations,
  isBuildingFinal,
  highlightedElement,
  onElementClick,
  onElementDoubleClick,
}: VerificationPanelProps) {
  const [expandedIteration, setExpandedIteration] = useState<number | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const verifiedCount = elements.filter((e) => e.is_verified).length;
  const totalCount = elements.length;
  const overallProgress = totalCount > 0 ? (verifiedCount / totalCount) * 100 : 0;

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden" aria-label="寸法検証パネル">
      {/* Progress header */}
      <div className="border-b bg-indigo-50 px-4 py-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-indigo-800">寸法検証</h3>
          {isVerifying && (
            <span className="inline-flex items-center gap-1 rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-blue-500" />
              反復 {currentIteration}/{maxIterations}
            </span>
          )}
        </div>
        <div className="mt-2">
          <div className="flex items-center justify-between text-xs text-indigo-600">
            <span>確定済み: {verifiedCount}/{totalCount}</span>
            <span>{overallProgress.toFixed(0)}%</span>
          </div>
          <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-indigo-200">
            <div
              className="h-full rounded-full bg-indigo-600 transition-all duration-500"
              style={{ width: `${overallProgress}%` }}
            />
          </div>
        </div>
      </div>

      {/* Element list */}
      <div className="flex-1 overflow-y-auto">
        {elements.length > 0 ? (
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-gray-50">
              <tr>
                <th className="px-3 py-1.5 text-left font-medium text-gray-500">要素</th>
                <th className="px-3 py-1.5 text-left font-medium text-gray-500">確度</th>
                <th className="px-3 py-1.5 text-left font-medium text-gray-500">状態</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {elements.map((elem) => (
                <tr
                  key={elem.element_seq}
                  className={`cursor-pointer transition-colors ${
                    highlightedElement === elem.element_seq
                      ? "bg-indigo-100 ring-1 ring-inset ring-indigo-400"
                      : "hover:bg-gray-50"
                  }`}
                  onClick={() => onElementClick?.(highlightedElement === elem.element_seq ? null : elem.element_seq)}
                  onDoubleClick={() => onElementDoubleClick?.(elem.feature_label || elem.element_seq)}
                  role="button"
                  tabIndex={0}
                  aria-selected={highlightedElement === elem.element_seq}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") onElementClick?.(highlightedElement === elem.element_seq ? null : elem.element_seq);
                  }}
                >
                  <td className="px-3 py-1.5">
                    <div className="font-medium text-gray-900">
                      {elem.feature_label || elem.element_seq}
                    </div>
                    <div className="text-gray-400">{elem.element_type}</div>
                  </td>
                  <td className="px-3 py-1.5">
                    <div className="flex items-center gap-1.5">
                      <div className="h-1.5 w-12 overflow-hidden rounded-full bg-gray-200">
                        <div
                          className={`h-full rounded-full ${confidenceColor(elem.confidence)} transition-all duration-300`}
                          style={{ width: `${elem.confidence * 100}%` }}
                        />
                      </div>
                      <span className={`font-mono ${confidenceTextColor(elem.confidence)}`}>
                        {(elem.confidence * 100).toFixed(0)}%
                      </span>
                    </div>
                  </td>
                  <td className="px-3 py-1.5">
                    <span
                      className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-medium ${
                        elem.is_verified
                          ? "bg-green-100 text-green-700"
                          : elem.confidence >= 0.6
                            ? "bg-yellow-100 text-yellow-700"
                            : "bg-red-100 text-red-700"
                      }`}
                    >
                      {confidenceBadge(elem.confidence)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="flex h-32 items-center justify-center text-xs text-gray-400">
            {isVerifying ? "検証データを取得中..." : "検証データがありません"}
          </div>
        )}

        {/* Iteration history */}
        {iterations.length > 0 && (
          <div className="border-t px-3 py-2">
            <p className="mb-1 text-xs font-semibold text-gray-500">反復履歴</p>
            {iterations.map((iter) => (
              <details
                key={iter.iteration}
                className="mb-1"
                open={expandedIteration === iter.iteration}
                onToggle={(e) =>
                  setExpandedIteration(
                    (e.target as HTMLDetailsElement).open ? iter.iteration : null,
                  )
                }
              >
                <summary className="cursor-pointer rounded bg-gray-50 px-2 py-1 text-xs text-gray-600 hover:bg-gray-100">
                  反復 #{iter.iteration} — {iter.elements.filter((e) => e.is_verified).length}/
                  {iter.elements.length} 確定
                </summary>
                <div className="mt-1 space-y-0.5 pl-2 text-[10px] text-gray-500">
                  {iter.elements
                    .filter((e) => !e.is_verified)
                    .map((e) => (
                      <div key={e.element_seq}>
                        {e.feature_label}: {(e.confidence * 100).toFixed(0)}%
                      </div>
                    ))}
                </div>
              </details>
            ))}
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Building final 3D model indicator */}
      {isBuildingFinal && (
        <div className="flex items-center gap-2 border-t bg-blue-50 px-4 py-3" role="status" aria-label="3Dモデル生成中">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-blue-300 border-t-blue-600" />
          <div className="flex-1">
            <p className="text-xs font-semibold text-blue-700">最終3Dモデルを生成中...</p>
            <p className="text-[10px] text-blue-500">検証が完了しました。CadQueryで3Dモデルを構築しています</p>
          </div>
        </div>
      )}
    </div>
  );
}
