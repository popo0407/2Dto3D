import { useState } from "react";
import { Viewer3D } from "./components/Viewer3D";
import { UploadPanel } from "./components/UploadPanel";
import { ChatPanel } from "./components/ChatPanel";
import { HistoryPanel } from "./components/HistoryPanel";
import { LoginPanel } from "./components/LoginPanel";
import { getIdToken, signOut } from "./auth";

type AppView = "upload" | "viewer";

export default function App() {
  const [view, setView] = useState<AppView>("upload");
  const [sessionId, setSessionId] = useState<string>("");
  const [nodeId, setNodeId] = useState<string>("");
  const [gltfUrl, setGltfUrl] = useState<string>("");
  const [idToken, setIdToken] = useState<string>("");

  const handleLoginSuccess = async () => {
    const token = await getIdToken();
    setIdToken(token ?? "");
  };

  const handleSignOut = () => {
    signOut();
    setIdToken("");
    setSessionId("");
    setNodeId("");
    setGltfUrl("");
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
