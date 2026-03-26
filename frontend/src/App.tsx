import { useState, useRef, useCallback } from "react";
import { Viewer3D } from "./components/Viewer3D";
import { UploadPanel } from "./components/UploadPanel";
import { ChatPanel } from "./components/ChatPanel";
import { HistoryPanel } from "./components/HistoryPanel";
import { LoginPanel } from "./components/LoginPanel";
import { getIdToken, signOut } from "./auth";
import { WS_URL } from "./config";

type AppView = "upload" | "viewer";

// WebSocket から届く通知メッセージの型
interface WsNotifyMessage {
  type: "PROCESSING_COMPLETE" | "PROCESSING_FAILED" | "PROGRESS" | string;
  session_id?: string;
  node_id?: string;
  gltf_url?: string;
  error?: string;
  step?: string;
  progress?: number;
  message?: string;
}

export default function App() {
  const [view, setView] = useState<AppView>("upload");
  const [sessionId, setSessionId] = useState<string>("");
  const [nodeId, setNodeId] = useState<string>("");
  const [gltfUrl, setGltfUrl] = useState<string>("");
  const [idToken, setIdToken] = useState<string>("");
  const [processingStep, setProcessingStep] = useState<string>("");
  const [processingProgress, setProcessingProgress] = useState<number>(0);

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
              <Viewer3D gltfUrl={gltfUrl} />
            </section>
            <aside className="flex w-80 flex-col border-l bg-white" aria-label="サイドパネル">
              <ChatPanel sessionId={sessionId} nodeId={nodeId} idToken={idToken} />
              <HistoryPanel sessionId={sessionId} onNodeSelect={setNodeId} idToken={idToken} />
            </aside>
          </>
        )}
      </main>
    </div>
  );
}
