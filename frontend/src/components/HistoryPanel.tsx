import { useEffect, useState } from "react";
import { API_BASE } from "../config";

interface HistoryPanelProps {
  sessionId: string;
  onNodeSelect: (nodeId: string) => void;
}

interface NodeSummary {
  node_id: string;
  type: string;
  user_message: string;
  created_at: number;
}

export function HistoryPanel({ sessionId, onNodeSelect }: HistoryPanelProps) {
  const [nodes, setNodes] = useState<NodeSummary[]>([]);

  useEffect(() => {
    if (!sessionId) return;

    const fetchNodes = async () => {
      try {
        const res = await fetch(`${API_BASE}/sessions/${sessionId}/nodes`);
        if (!res.ok) return;
        const data = (await res.json()) as { nodes: NodeSummary[] };
        setNodes(data.nodes);
      } catch {
        // silently ignore fetch errors
      }
    };

    fetchNodes();
  }, [sessionId]);

  return (
    <div className="flex flex-col" aria-label="バージョン履歴">
      <h3 className="border-b px-4 py-2 text-sm font-medium text-gray-700">
        バージョン履歴
      </h3>
      <ul className="flex-1 overflow-y-auto">
        {nodes.length === 0 && (
          <li className="px-4 py-3 text-center text-xs text-gray-400">
            履歴なし
          </li>
        )}
        {nodes.map((node, index) => (
          <li key={node.node_id}>
            <button
              type="button"
              onClick={() => onNodeSelect(node.node_id)}
              className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-gray-50 focus:bg-blue-50"
              aria-label={`バージョン ${nodes.length - index}: ${node.type}`}
            >
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-100 text-xs font-medium text-blue-700">
                {nodes.length - index}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-gray-800">
                  {node.type === "INITIAL" ? "初期生成" : "チャット編集"}
                </p>
                {node.user_message && (
                  <p className="truncate text-xs text-gray-500">
                    {node.user_message}
                  </p>
                )}
                <time className="text-xs text-gray-400" dateTime={new Date(node.created_at * 1000).toISOString()}>
                  {new Date(node.created_at * 1000).toLocaleString("ja-JP")}
                </time>
              </div>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
