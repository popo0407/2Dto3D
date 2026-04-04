import { useState, useRef, useCallback } from "react";
import { Viewer3D, type SelectionInfo } from "./components/Viewer3D";
import { UploadPanel } from "./components/UploadPanel";
import { ChatPanel } from "./components/ChatPanel";
import { HistoryPanel } from "./components/HistoryPanel";
import { LoginPanel } from "./components/LoginPanel";
import { VerificationPanel, ElementPreview, type VerificationElement } from "./components/VerificationPanel";
import { BuildPlanPanel, type BuildPlan } from "./components/BuildPlanPanel";
import { getIdToken, signOut } from "./auth";
import { WS_URL, API_BASE } from "./config";

type AppView = "upload" | "viewer" | "buildplan";

// WebSocket から届く通知メッセージの型
interface WsNotifyMessage {
  type: "PROCESSING_COMPLETE" | "PROCESSING_FAILED" | "PROGRESS" | "AI_QUESTION" | "VERIFICATION_PROGRESS" | "TOKEN_USAGE" | string;
  session_id?: string;
  node_id?: string;
  gltf_url?: string;
  ai_reasoning?: string;
  error?: string;
  step?: string;
  progress?: number;
  message?: string;
  questions?: AiQuestion[];
  // Verification-specific fields
  iteration_count?: number;
  all_verified?: boolean;
  elements?: VerificationElement[];
  // Token usage fields
  input_tokens?: number;
  output_tokens?: number;
}

interface VerificationIteration {
  iteration: number;
  elements: VerificationElement[];
  timestamp: number;
}

interface AiQuestion {
  id: string;
  feature_id?: string;
  text: string;
  confidence?: number;
  priority?: "high" | "medium" | "low";
}

export default function App() {
  const [view, setView] = useState<AppView>("upload");
  const [sessionId, setSessionId] = useState<string>("");
  const [nodeId, setNodeId] = useState<string>("");
  const [gltfUrl, setGltfUrl] = useState<string>("");
  const [idToken, setIdToken] = useState<string>("");
  const [processingStep, setProcessingStep] = useState<string>("");
  const [processingProgress, setProcessingProgress] = useState<number>(0);
  const [aiQuestions, setAiQuestions] = useState<AiQuestion[]>([]);
  const [aiReasoning, setAiReasoning] = useState<string>("");
  const [selection, setSelection] = useState<SelectionInfo | null>(null);
  const [chatPipelineComplete, setChatPipelineComplete] = useState(false);

  // Token usage state (accumulated across all steps)
  const [totalInputTokens, setTotalInputTokens] = useState(0);
  const [totalOutputTokens, setTotalOutputTokens] = useState(0);

  // Verification state
  const [verifyElements, setVerifyElements] = useState<VerificationElement[]>([]);
  const [verifyIterations, setVerifyIterations] = useState<VerificationIteration[]>([]);
  const [isVerifying, setIsVerifying] = useState(false);
  const [currentVerifyIteration, setCurrentVerifyIteration] = useState(0);
  const [highlightedElement, setHighlightedElement] = useState<string | null>(null);
  const [isBuildingFinal, setIsBuildingFinal] = useState(false);

  // BuildPlan mode state
  const [buildPlan, setBuildPlan] = useState<BuildPlan | null>(null);

  // WebSocket ref（セッションをまたいで保持）
  const wsRef = useRef<WebSocket | null>(null);

  // UploadPanel から呼ばれる。WebSocket を接続して接続確立後に resolve する Promise を返す。
  // 呼び出し元は await してから /process を呼ぶことで競合状態を防ぐ。
  const handleProcessingStart = useCallback(
    (sid: string, onComplete: (nodeId: string, url: string, reasoning?: string) => void, onError: (msg: string) => void): Promise<void> => {
      return new Promise((resolve, reject) => {
        // 既存 WS があれば閉じる
        wsRef.current?.close();

        const ws = new WebSocket(`${WS_URL}?session_id=${sid}`);
        wsRef.current = ws;

        ws.onopen = () => {
          // 接続後にセッションを subscribe し、接続確立を呼び出し元へ通知
          ws.send(JSON.stringify({ action: "subscribe", session_id: sid }));
          resolve();
        };

        ws.onmessage = (event) => {
          try {
            const msg = JSON.parse(event.data as string) as WsNotifyMessage;
            if (msg.type === "PROGRESS") {
              setProcessingStep(msg.step ?? "");
              setProcessingProgress(msg.progress ?? 0);
              setView("viewer");
              // Track verification state
              if (msg.step === "VERIFYING_DIMENSIONS" || msg.step === "EXTRACTING_DIMENSIONS") {
                setIsVerifying(true);
              }
            } else if (msg.type === "VERIFICATION_PROGRESS") {
              const elems = msg.elements ?? [];
              setVerifyElements(elems);
              setCurrentVerifyIteration(msg.iteration_count ?? 0);
              const allVerified = !!msg.all_verified;
              setIsVerifying(!allVerified);
              if (allVerified) {
                setIsBuildingFinal(true);
              }
              setVerifyIterations((prev) => [
                ...prev,
                {
                  iteration: msg.iteration_count ?? 0,
                  elements: elems,
                  timestamp: Date.now(),
                },
              ]);
            } else if (msg.type === "TOKEN_USAGE") {
              setTotalInputTokens((prev) => prev + (msg.input_tokens ?? 0));
              setTotalOutputTokens((prev) => prev + (msg.output_tokens ?? 0));
            } else if (msg.type === "AI_QUESTION" && msg.questions?.length) {
            setAiQuestions(msg.questions);
          } else if (msg.type === "PROCESSING_COMPLETE" && msg.node_id && msg.gltf_url) {
              setProcessingProgress(100);
              setIsVerifying(false);
              setIsBuildingFinal(false);
              ws.close();
              onComplete(msg.node_id, msg.gltf_url, msg.ai_reasoning);
            } else if (msg.type === "PROCESSING_FAILED") {
              setIsVerifying(false);
              setIsBuildingFinal(false);
              ws.close();
              onError(msg.error ?? "処理に失敗しました");
            }
          } catch {
            // JSON parse 失敗は無視
          }
        };

        ws.onerror = () => {
          onError("WebSocket 接続エラーが発生しました");
          reject(new Error("WebSocket 接続エラーが発生しました"));
        };
      });
    },
    [],
  );

  /** チャット編集後、新 node_id で WebSocket を再接続してパイプライン完了を待つ */
  const handleChatNodeCreated = useCallback(
    (sid: string, _newNodeId: string) => {
      setChatPipelineComplete(false);
      setGltfUrl("");
      setVerifyElements([]);
      setVerifyIterations([]);
      setIsVerifying(false);
      setIsBuildingFinal(false);
      setProcessingStep("BUILDING");
      setProcessingProgress(55);
      setView("viewer");
      handleProcessingStart(
        sid,
        (completedNodeId, url, reasoning) => {
          setNodeId(completedNodeId);
          setGltfUrl(url);
          setProcessingStep("");
          setProcessingProgress(0);
          setChatPipelineComplete(true);
          if (reasoning) setAiReasoning(reasoning);
          // 次回チャット変更に備えて少し遅延してリセット
          setTimeout(() => setChatPipelineComplete(false), 500);
        },
        (err) => {
          console.error("Chat pipeline failed:", err);
          setProcessingStep("");
          setProcessingProgress(0);
        },
      );
    },
    [handleProcessingStart],
  );

  const handleLoginSuccess = async () => {
    const token = await getIdToken();
    setIdToken(token ?? "");
  };

  const handleSignOut = () => {
    wsRef.current?.close();
    signOut();
    setIdToken("");
    setSessionId("");
    setNodeId("");
    setGltfUrl("");
    setProcessingStep("");
    setProcessingProgress(0);
    setAiQuestions([]);
    setAiReasoning("");
    setVerifyElements([]);
    setVerifyIterations([]);
    setIsVerifying(false);
    setCurrentVerifyIteration(0);
    setHighlightedElement(null);
    setIsBuildingFinal(false);
    setTotalInputTokens(0);
    setTotalOutputTokens(0);
    setBuildPlan(null);
    setView("upload");
  };

  const handleVerifyComment = useCallback(
    (comment: string) => {
      if (wsRef.current?.readyState === WebSocket.OPEN && sessionId) {
        wsRef.current.send(
          JSON.stringify({
            action: "verifyComment",
            session_id: sessionId,
            comment,
          }),
        );
      }
    },
    [sessionId],
  );

  if (!idToken) {
    return <LoginPanel onLoginSuccess={handleLoginSuccess} />;
  }

  const handleSessionCreated = (id: string) => {
    setSessionId(id);
  };

  const handleProcessingComplete = (nid: string, url: string, reasoning?: string) => {
    setNodeId(nid);
    setGltfUrl(url);
    setView("viewer");
    if (reasoning) setAiReasoning(reasoning);
  };

  const handleDownloadStep = async (sid: string, nid: string, token: string) => {
    try {
      const res = await fetch(`${API_BASE}/sessions/${sid}/nodes/${nid}/download?format=step`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error("STEP取得に失敗");
      const data = (await res.json()) as { download_url?: string };
      if (data.download_url) {
        const a = document.createElement("a");
        a.href = data.download_url;
        a.download = "model.step";
        a.click();
      }
    } catch (e) {
      console.error("STEP download failed:", e);
    }
  };

  return (
    <div className="flex h-screen flex-col bg-gray-50">
      <header className="flex h-14 shrink-0 items-center border-b bg-white px-6">
        <h1 className="text-lg font-semibold text-gray-900">
          2D to 3D AI 変換
        </h1>
        <nav className="ml-auto flex items-center gap-2" role="navigation" aria-label="メイン">
          <button
            type="button"
            onClick={() => setView("upload")}
            className={`rounded-md px-3 py-1.5 text-sm font-medium ${
              view === "upload"
                ? "bg-blue-100 text-blue-700"
                : "text-gray-600 hover:bg-gray-100"
            }`}
            aria-current={view === "upload" ? "page" : undefined}
          >
            アップロード
          </button>
          <button
            type="button"
            onClick={() => setView("viewer")}
            className={`rounded-md px-3 py-1.5 text-sm font-medium ${
              view === "viewer"
                ? "bg-blue-100 text-blue-700"
                : "text-gray-600 hover:bg-gray-100"
            }`}
            disabled={!sessionId}
            aria-current={view === "viewer" ? "page" : undefined}
          >
            3Dビューア
          </button>
          <button
            type="button"
            onClick={() => setView("buildplan")}
            className={`rounded-md px-3 py-1.5 text-sm font-medium ${
              view === "buildplan"
                ? "bg-indigo-100 text-indigo-700"
                : "text-gray-600 hover:bg-gray-100"
            }`}
            disabled={!sessionId}
            aria-current={view === "buildplan" ? "page" : undefined}
          >
            段階的構築
          </button>
          {/* Token usage display */}
          {(totalInputTokens > 0 || totalOutputTokens > 0) && (
            <div className="ml-4 flex items-center gap-2 rounded-md bg-gray-100 px-3 py-1 text-xs text-gray-600" title="累計トークン使用量">
              <span>入力: <span className="font-mono font-semibold text-gray-800">{totalInputTokens.toLocaleString()}</span></span>
              <span className="text-gray-400">/</span>
              <span>出力: <span className="font-mono font-semibold text-gray-800">{totalOutputTokens.toLocaleString()}</span></span>
              <span className="text-gray-400">tok</span>
            </div>
          )}
          <button
            type="button"
            onClick={handleSignOut}
            className="ml-4 rounded-md px-3 py-1.5 text-sm font-medium text-gray-500 hover:bg-gray-100"
          >
            ログアウト
          </button>
        </nav>
      </header>

      <main className="flex flex-1 overflow-hidden">
        {view === "upload" ? (
          <UploadPanel
            idToken={idToken}
            onSessionCreated={handleSessionCreated}
            onProcessingComplete={handleProcessingComplete}
            onProcessingStart={handleProcessingStart}
            processingStep={processingStep}
            processingProgress={processingProgress}
          />
        ) : view === "buildplan" ? (
          <BuildPlanPanel
            sessionId={sessionId}
            idToken={idToken}
            plan={buildPlan}
            onPlanCreated={setBuildPlan}
            onExecutionComplete={(url, nid) => {
              setNodeId(nid);
              setGltfUrl(url);
              setView("viewer");
            }}
            onTokenUsage={(inp, out) => {
              setTotalInputTokens((prev) => prev + inp);
              setTotalOutputTokens((prev) => prev + out);
            }}
          />
        ) : (
          <>
            <section className="flex w-1/2 flex-col" aria-label="3Dビューア">
              {gltfUrl ? (
                <Viewer3D
                  gltfUrl={gltfUrl}
                  onDownloadStep={nodeId ? () => handleDownloadStep(sessionId, nodeId, idToken) : undefined}
                  onSelectionChange={setSelection}
                />
              ) : verifyElements.length > 0 ? (
                <div className="flex flex-1 flex-col">
                  <div className="flex items-center gap-2 border-b bg-indigo-50 px-4 py-2">
                    <span className="h-2 w-2 animate-pulse rounded-full bg-indigo-500" />
                    <span className="text-xs font-semibold text-indigo-700">
                      {isBuildingFinal ? "最終3Dモデル生成中..." : "中間プレビュー"}
                    </span>
                    {isBuildingFinal && (
                      <span className="ml-auto text-[10px] text-indigo-500">検証完了 → CadQuery構築中</span>
                    )}
                  </div>
                  <div className="relative flex-1">
                    <ElementPreview elements={verifyElements} className="h-full w-full bg-gray-900" highlightedElement={highlightedElement} />
                    {isBuildingFinal && (
                      <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-black/30">
                        <div className="flex flex-col items-center gap-2 rounded-lg bg-white/90 px-6 py-4 shadow-lg">
                          <div className="h-8 w-8 animate-spin rounded-full border-3 border-indigo-200 border-t-indigo-600" />
                          <p className="text-sm font-semibold text-indigo-700">最終3Dモデルを生成中</p>
                          <p className="text-xs text-gray-500">検証済みデータを元にCadQueryで構築しています</p>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="flex flex-1 items-center justify-center bg-gray-100">
                  <div className="text-center">
                    <div className="mx-auto mb-3 h-10 w-10 animate-spin rounded-full border-4 border-blue-200 border-t-blue-600" />
                    <p className="text-sm font-medium text-gray-600">
                      {processingStep === "PARSING" ? "ファイル解析中..." : processingStep === "AI_ANALYZING" ? "AI図面解釈中..." : processingStep === "BUILDING" ? "3Dモデル構築中..." : processingStep ? "処理中..." : "処理開始中..."}
                    </p>
                    <p className="mt-1 text-xs text-gray-400">{processingProgress}%</p>
                  </div>
                </div>
              )}
            </section>
            <aside className="flex w-1/2 min-h-0 flex-col border-l bg-white overflow-hidden" aria-label="サイドパネル">
              {/* AI reasoning and questions (collapsible, shrink-0) */}
              <div className="shrink-0">
                {aiReasoning && (
                  <details className="border-b" open>
                    <summary className="cursor-pointer bg-indigo-50 px-4 py-2 text-xs font-semibold text-indigo-700 hover:bg-indigo-100">
                      AIの解析理由
                    </summary>
                    <div className="max-h-48 overflow-y-auto px-4 py-3 text-xs text-gray-700 whitespace-pre-wrap leading-relaxed">
                      {aiReasoning}
                    </div>
                  </details>
                )}
                {aiQuestions.length > 0 && (
                  <div
                    className="border-b bg-amber-50 px-4 py-3"
                    role="alert"
                    aria-label="AIからの質問"
                  >
                    <p className="mb-2 text-xs font-semibold text-amber-700">
                      AI が確認を求めています
                    </p>
                    <ul className="space-y-1">
                      {aiQuestions.map((q) => (
                        <li key={q.id} className="text-xs text-amber-800">
                          <span className="font-medium">[{q.feature_id ?? q.id}]</span> {q.text}
                        </li>
                      ))}
                    </ul>
                    <button
                      type="button"
                      onClick={() => setAiQuestions([])}
                      className="mt-2 text-xs text-amber-600 underline hover:text-amber-800"
                    >
                      閉じる
                    </button>
                  </div>
                )}
              </div>

              {/* Verification elements (visible when verifying, shrinkable) */}
              {verifyElements.length > 0 && (
                <div className="flex max-h-64 shrink-0 flex-col border-b overflow-hidden">
                  <VerificationPanel
                    sessionId={sessionId}
                    elements={verifyElements}
                    iterations={verifyIterations}
                    isVerifying={isVerifying}
                    currentIteration={currentVerifyIteration}
                    maxIterations={5}
                    isBuildingFinal={isBuildingFinal}
                    highlightedElement={highlightedElement}
                    onElementClick={setHighlightedElement}
                  />
                </div>
              )}

              {/* Unified chat (flex-1, always visible) */}
              <ChatPanel
                sessionId={sessionId}
                nodeId={nodeId}
                idToken={idToken}
                onChatNodeCreated={(newNodeId) => handleChatNodeCreated(sessionId, newNodeId)}
                selectionContext={
                  selection
                    ? [
                        selection.meshName,
                        selection.featureId ? `Feature: ${selection.featureId}` : "",
                        selection.cylinderInfo
                          ? `穴: Φ${selection.cylinderInfo.diameter} ${selection.cylinderInfo.axis}軸 深さ${selection.cylinderInfo.depth}`
                          : "",
                        selection.faceDimensions
                          ? `面: ${selection.faceDimensions.width}×${selection.faceDimensions.height} 面積${selection.faceDimensions.area}`
                          : "",
                        `全体: W:${selection.dimensions.width} H:${selection.dimensions.height} D:${selection.dimensions.depth}`,
                        selection.normal
                          ? `面方向: ${selection.normal.x > 0.5 ? "+X" : selection.normal.x < -0.5 ? "-X" : ""}${selection.normal.y > 0.5 ? "+Y" : selection.normal.y < -0.5 ? "-Y" : ""}${selection.normal.z > 0.5 ? "+Z" : selection.normal.z < -0.5 ? "-Z" : "斜面"}`
                          : "",
                      ]
                        .filter(Boolean)
                        .join(" / ")
                    : undefined
                }
                pipelineComplete={chatPipelineComplete}
                verifyMode={isVerifying}
                onVerifyComment={handleVerifyComment}
                isBuildingFinal={isBuildingFinal}
                onTokenUsage={(inp, out) => {
                  setTotalInputTokens((prev) => prev + inp);
                  setTotalOutputTokens((prev) => prev + out);
                }}
              />
              <HistoryPanel sessionId={sessionId} onNodeSelect={setNodeId} idToken={idToken} />
            </aside>
          </>
        )}
      </main>
    </div>
  );
}
