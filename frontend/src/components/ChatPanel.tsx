import { useState, useEffect, useRef } from "react";
import { API_BASE } from "../config";

interface ChatPanelProps {
  sessionId: string;
  nodeId: string;
  idToken: string;
  /** チャット送信後、パイプライン再実行のために新 nodeId を親へ通知する */
  onChatNodeCreated?: (newNodeId: string) => void;
  /** 3Dビューアで選択中の要素情報（AIへのコンテキストとして送信） */
  selectionContext?: string;
  /** パイプライン再実行が完了したら true になる（親が管理） */
  pipelineComplete?: boolean;
  /** 検証中モード: true の場合は HTTP API の代わりに WebSocket コメントを送信 */
  verifyMode?: boolean;
  /** 検証コメント送信コールバック（verifyMode=true のとき使用） */
  onVerifyComment?: (comment: string) => void;
  /** 3Dモデル生成中フラグ（入力無効化に使用） */
  isBuildingFinal?: boolean;
  /** トークン数が更新されたとき通知するコールバック */
  onTokenUsage?: (inputTokens: number, outputTokens: number) => void;
}

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export function ChatPanel({ sessionId, nodeId, idToken, onChatNodeCreated, selectionContext, pipelineComplete, verifyMode, onVerifyComment, isBuildingFinal, onTokenUsage }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [waitingPipeline, setWaitingPipeline] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  // パイプライン完了時にチャットへ完了メッセージを追加
  useEffect(() => {
    if (waitingPipeline && pipelineComplete) {
      setWaitingPipeline(false);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "✅ 3Dモデルの再生成が完了しました。ビューアに反映済みです。" },
      ]);
    }
  }, [pipelineComplete, waitingPipeline]);

  // 新着メッセージ時に最下部へスクロール
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = async () => {
    if (!input.trim() || !sessionId) return;

    const userMessage = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: userMessage }]);

    // --- 検証モード: WebSocket 経由でコメント送信 ---
    if (verifyMode && onVerifyComment) {
      onVerifyComment(userMessage);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "✅ 検証AIにコメントを送信しました。次の反復に反映されます。" },
      ]);
      return;
    }

    // --- 通常モード: HTTP API 経由でモデル修正 ---
    if (!nodeId) return;
    setLoading(true);

    try {
      const messageToSend = selectionContext
        ? `[選択中の要素: ${selectionContext}] ${userMessage}`
        : userMessage;
      const res = await fetch(
        `${API_BASE}/sessions/${sessionId}/nodes/${nodeId}/chat`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${idToken}` },
          body: JSON.stringify({ message: messageToSend }),
        },
      );
      if (!res.ok) throw new Error("チャットリクエストに失敗しました");

      const data = (await res.json()) as { diff_patch?: string; node_id?: string; input_tokens?: number; output_tokens?: number };
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.diff_patch
            ? `✅ ${data.diff_patch}\n\n3Dモデルを再生成中...`
            : "モデルを更新しました。再生成中...",
        },
      ]);

      if (data.input_tokens != null || data.output_tokens != null) {
        onTokenUsage?.(data.input_tokens ?? 0, data.output_tokens ?? 0);
      }

      // 新 node_id をパイプライン再実行のために親へ通知
      if (data.node_id && onChatNodeCreated) {
        setWaitingPipeline(true);
        onChatNodeCreated(data.node_id);
      }
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
    <div className="flex min-h-0 flex-1 flex-col" aria-label="AIチャット">
      <h3 className="shrink-0 border-b px-4 py-2 text-sm font-medium text-gray-700">
        {verifyMode ? "検証チャット" : "AIチャット"}
      </h3>
      <div className="flex-1 overflow-y-auto p-3 space-y-2" role="log" aria-live="polite">
        {messages.length === 0 && (
          <p className="text-center text-xs text-gray-400 py-4">
            {verifyMode
              ? "検証AIへのコメントを入力してください（次の反復に反映）"
              : "モデルの修正指示を入力してください"}
          </p>
        )}
        {selectionContext && (
          <div className="mx-2 rounded bg-orange-50 border border-orange-200 px-3 py-1.5 text-xs text-orange-700">
            🎯 選択中: {selectionContext}
          </div>
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
        {waitingPipeline && !loading && (
          <div className="mr-6 rounded-lg bg-blue-50 border border-blue-200 px-3 py-2 text-sm text-blue-600 animate-pulse">
            ⚙️ 3Dモデルを再構築中...
          </div>
        )}
        <div ref={bottomRef} />
      </div>
      <div className="shrink-0 flex gap-2 border-t p-3">
        <label htmlFor="chat-input" className="sr-only">
          メッセージ入力
        </label>
        <input
          id="chat-input"
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={verifyMode ? "例: 穴の位置が上面図と一致していません" : "例: 穴の直径を8mmに変更して"}
          className="flex-1 rounded-lg border px-3 py-1.5 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
          disabled={!sessionId || loading || isBuildingFinal}
        />
        <button
          type="button"
          onClick={handleSend}
          disabled={!input.trim() || loading || isBuildingFinal}
          className="rounded-lg bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed"
          aria-label="メッセージ送信"
        >
          送信
        </button>
      </div>
    </div>
  );
}
