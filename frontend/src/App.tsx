import { useState, useRef, useCallback } from "react";
import { Viewer3D } from "./components/Viewer3D";
import { UploadPanel } from "./components/UploadPanel";
import { ChatPanel } from "./components/ChatPanel";
import { HistoryPanel } from "./components/HistoryPanel";
import { LoginPanel } from "./components/LoginPanel";
import { getIdToken, signOut } from "./auth";
import { WS_URL, API_BASE } from "./config";

type AppView = "upload" | "viewer";

// WebSocket から届く通知メッセージの型
interface WsNotifyMessage {
  type: "PROCESSING_COMPLETE" | "PROCESSING_FAILED" | "PROGRESS" | "AI_QUESTION" | string;
  session_id?: string;
  node_id?: string;
  gltf_url?: string;
  error?: string;
  step?: string;
  progress?: number;
  message?: string;
  questions?: AiQuestion[];
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
  const [confidenceMap, setConfidenceMap] = useState<Record<string, number>>({});
  const [aiQuestions, setAiQuestions] = useState<AiQuestion[]>([]);

  // WebSocket ref（セッションをまたいで保持）
  const wsRef = useRef<WebSocket | null>(null);

  // UploadPanel から呼ばれる。WebSocket を接続して接続確立後に resolve する Promise を返す。
  // 呼び出し元は await してから /process を呼ぶことで競合状態を防ぐ。
  const handleProcessingStart = useCallback(
    (sid: string, onComplete: (nodeId: string, url: string) => void, onError: (msg: string) => void): Promise<void> => {
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
            } else if (msg.type === "AI_QUESTION" && msg.questions?.length) {
            setAiQuestions(msg.questions);
          } else if (msg.type === "PROCESSING_COMPLETE" && msg.node_id && msg.gltf_url) {
              setProcessingProgress(100);
              ws.close();
              onComplete(msg.node_id, msg.gltf_url);
            } else if (msg.type === "PROCESSING_FAILED") {
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
      setProcessingStep("BUILDING");
      setProcessingProgress(55);
      setView("viewer");
      handleProcessingStart(
        sid,
        (completedNodeId, url) => {
          setNodeId(completedNodeId);
          setGltfUrl(url);
          setProcessingStep("");
          setProcessingProgress(0);
          _fetchNodeConfidenceMap(completedNodeId, sid, idToken, setConfidenceMap);
        },
        (err) => {
          console.error("Chat pipeline failed:", err);
          setProcessingStep("");
          setProcessingProgress(0);
        },
      );
    },
    [handleProcessingStart, idToken],
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
    setConfidenceMap({});
    setAiQuestions([]);
    setView("upload");
  };

  if (!idToken) {
    return <LoginPanel onLoginSuccess={handleLoginSuccess} />;
  }

  const handleSessionCreated = (id: string) => {
    setSessionId(id);
  };

  const handleProcessingComplete = (nid: string, url: string) => {
    setNodeId(nid);
    setGltfUrl(url);
    setView("viewer");
    _fetchNodeConfidenceMap(nid, sessionId, idToken, setConfidenceMap);
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
        ) : (
          <>
            <section className="flex flex-1 flex-col" aria-label="3Dビューア">
              <Viewer3D gltfUrl={gltfUrl} confidenceMap={confidenceMap} />
            </section>
            <aside className="flex w-80 flex-col border-l bg-white" aria-label="サイドパネル">
              {aiQuestions.length > 0 && (
                <div
                  className="border-b bg-amber-50 px-4 py-3"
                  role="alert"
                  aria-label="AIからの質問"
                >
                  <p className="mb-2 text-xs font-semibold text-amber-700">
                    ⚠ AI が確認を求めています
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
              <ChatPanel
                sessionId={sessionId}
                nodeId={nodeId}
                idToken={idToken}
                onChatNodeCreated={(newNodeId) => handleChatNodeCreated(sessionId, newNodeId)}
              />
              <HistoryPanel sessionId={sessionId} onNodeSelect={setNodeId} idToken={idToken} />
            </aside>
          </>
        )}
      </main>
    </div>
  );
}

/** ノードの確度マップを API から取得して set する */
async function _fetchNodeConfidenceMap(
  nodeId: string,
  sessionId: string,
  idToken: string,
  setter: (map: Record<string, number>) => void,
): Promise<void> {
  if (!nodeId || !sessionId) return;
  try {
    const res = await fetch(`${API_BASE}/sessions/${sessionId}/nodes/${nodeId}`, {
      headers: { Authorization: `Bearer ${idToken}` },
    });
    if (!res.ok) return;
    const data = (await res.json()) as { confidence_map?: Record<string, number> };
    if (data.confidence_map && Object.keys(data.confidence_map).length > 0) {
      setter(data.confidence_map);
    }
  } catch {
    // サイレント無視（表示機能なので処理を止めない）
  }
}
