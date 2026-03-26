import { useState } from "react";
import { API_BASE } from "../config";

interface ChatPanelProps {
  sessionId: string;
  nodeId: string;
}

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export function ChatPanel({ sessionId, nodeId }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSend = async () => {
    if (!input.trim() || !sessionId || !nodeId) return;

    const userMessage = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: userMessage }]);
    setLoading(true);

    try {
      const res = await fetch(
        `${API_BASE}/sessions/${sessionId}/nodes/${nodeId}/chat`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: userMessage }),
        },
      );
      if (!res.ok) throw new Error("チャットリクエストに失敗しました");

      const data = (await res.json()) as { diff_patch?: string; node_id?: string };
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.diff_patch || "モデルを更新しました。",
        },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "エラーが発生しました。再度お試しください。" },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex flex-1 flex-col border-b" aria-label="AIチャット">
      <h3 className="border-b px-4 py-2 text-sm font-medium text-gray-700">
        AIチャット
      </h3>
      <div className="flex-1 overflow-y-auto p-3 space-y-2" role="log" aria-live="polite">
        {messages.length === 0 && (
          <p className="text-center text-xs text-gray-400 py-4">
            モデルの修正指示を入力してください
          </p>
        )}
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`rounded-lg px-3 py-2 text-sm ${
              msg.role === "user"
                ? "ml-6 bg-blue-100 text-blue-900"
                : "mr-6 bg-gray-100 text-gray-800"
            }`}
          >
            {msg.content}
          </div>
        ))}
        {loading && (
          <div className="mr-6 rounded-lg bg-gray-100 px-3 py-2 text-sm text-gray-500 animate-pulse">
            考え中...
          </div>
        )}
      </div>
      <div className="flex gap-2 border-t p-3">
        <label htmlFor="chat-input" className="sr-only">
          メッセージ入力
        </label>
        <input
          id="chat-input"
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="例: 穴の直径を8mmに変更して"
          className="flex-1 rounded-lg border px-3 py-1.5 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
          disabled={!sessionId || loading}
        />
        <button
          type="button"
          onClick={handleSend}
          disabled={!input.trim() || loading}
          className="rounded-lg bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed"
          aria-label="メッセージ送信"
        >
          送信
        </button>
      </div>
    </div>
  );
}
