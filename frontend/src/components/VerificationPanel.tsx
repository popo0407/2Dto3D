import { useState, useRef, useCallback } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";

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
  onSendComment: (comment: string) => void;
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

/* ---------- Mini 3D Preview ---------- */

function ElementPreview({ elements }: { elements: VerificationElement[] }) {
  return (
    <div className="h-48 w-full rounded border bg-gray-900">
      <Canvas camera={{ position: [150, 100, 150], fov: 50 }}>
        <ambientLight intensity={0.6} />
        <directionalLight position={[10, 10, 5]} intensity={0.8} />
        {elements.map((elem) => (
          <ElementMesh key={elem.element_seq} element={elem} />
        ))}
        <gridHelper args={[200, 20, "#444", "#333"]} />
        <OrbitControls enableDamping />
      </Canvas>
    </div>
  );
}

function ElementMesh({ element }: { element: VerificationElement }) {
  const { dimensions, position, confidence, element_type } = element;
  const pos: [number, number, number] = [
    position?.x ?? 0,
    position?.y ?? 0,
    position?.z ?? 0,
  ];

  const color = confidence >= 0.85
    ? "#22c55e"
    : confidence >= 0.6
      ? "#eab308"
      : "#ef4444";

  if (element_type === "hole") {
    const diameter = dimensions?.diameter ?? 6;
    const depth = dimensions?.depth ?? 10;
    return (
      <mesh position={pos}>
        <cylinderGeometry args={[diameter / 2, diameter / 2, depth, 16]} />
        <meshStandardMaterial color={color} transparent opacity={0.7} wireframe />
      </mesh>
    );
  }

  const w = dimensions?.width ?? 10;
  const h = dimensions?.height ?? 10;
  const d = dimensions?.depth ?? 10;
  return (
    <mesh position={pos}>
      <boxGeometry args={[w, h, d]} />
      <meshStandardMaterial color={color} transparent opacity={0.6} />
    </mesh>
  );
}

/* ---------- Main Panel ---------- */

export function VerificationPanel({
  sessionId,
  elements,
  iterations,
  isVerifying,
  currentIteration,
  maxIterations,
  onSendComment,
}: VerificationPanelProps) {
  const [comment, setComment] = useState("");
  const [expandedIteration, setExpandedIteration] = useState<number | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const handleSend = useCallback(() => {
    if (!comment.trim() || !sessionId) return;
    onSendComment(comment.trim());
    setComment("");
  }, [comment, sessionId, onSendComment]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const verifiedCount = elements.filter((e) => e.is_verified).length;
  const totalCount = elements.length;
  const overallProgress = totalCount > 0 ? (verifiedCount / totalCount) * 100 : 0;

  return (
    <div className="flex flex-1 flex-col" aria-label="寸法検証パネル">
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

      {/* 3D Preview */}
      {elements.length > 0 && (
        <div className="border-b p-2">
          <p className="mb-1 text-xs font-medium text-gray-500">中間プレビュー</p>
          <ElementPreview elements={elements} />
        </div>
      )}

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
                <tr key={elem.element_seq} className="hover:bg-gray-50">
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

      {/* Comment input */}
      <div className="border-t bg-white p-3">
        <label htmlFor="verify-comment" className="mb-1 block text-xs font-medium text-gray-500">
          AIへのコメント（次の反復に反映）
        </label>
        <div className="flex gap-2">
          <textarea
            id="verify-comment"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="例: 穴の位置が上面図と一致していません"
            className="flex-1 resize-none rounded border px-2 py-1.5 text-xs focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
            rows={2}
            disabled={!isVerifying}
          />
          <button
            type="button"
            onClick={handleSend}
            disabled={!comment.trim() || !isVerifying}
            className="self-end rounded bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            送信
          </button>
        </div>
      </div>
    </div>
  );
}
