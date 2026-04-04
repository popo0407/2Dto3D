import { useState, useCallback, useRef, useEffect } from "react";
import { API_BASE } from "../config";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface StepParameter {
  value: number | string | boolean;
  unit: string;
  source: "extracted" | "standard" | "calculated" | "user";
  confidence: number;
}

export interface BuildStep {
  plan_id: string;
  step_seq: string;
  step_type: string;
  step_name: string;
  parameters: Record<string, StepParameter>;
  cq_code: string;
  dependencies: string[];
  group_id: string;
  confidence: number;
  status: "planned" | "executing" | "completed" | "modified" | "failed";
  ai_reasoning: string;
  checkpoint_step_key: string;
  checkpoint_glb_key: string;
  executed_at: number;
}

export interface BuildPlan {
  plan_id: string;
  session_id: string;
  node_id: string;
  total_steps: number;
  reasoning: string;
  steps: BuildStep[];
}

interface Props {
  sessionId: string;
  idToken: string;
  plan: BuildPlan | null;
  onPlanCreated: (plan: BuildPlan) => void;
  onExecutionComplete: (gltfUrl: string, nodeId: string) => void;
  onTokenUsage?: (inp: number, out: number) => void;
}

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------

const STATUS_ICON: Record<string, string> = {
  planned: "○",
  executing: "◎",
  completed: "✓",
  modified: "✎",
  failed: "✗",
};

const STATUS_COLOR: Record<string, string> = {
  planned: "text-gray-400",
  executing: "text-blue-500 animate-pulse",
  completed: "text-green-600",
  modified: "text-amber-500",
  failed: "text-red-500",
};

const STEP_TYPE_LABEL: Record<string, string> = {
  base_body: "基本形状",
  hole_through: "貫通穴",
  hole_blind: "止め穴",
  tapped_hole: "ネジ穴",
  fillet: "R面取り",
  chamfer: "C面取り",
  slot: "長穴",
  pocket: "ポケット",
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function BuildPlanPanel({
  sessionId,
  idToken,
  plan,
  onPlanCreated,
  onExecutionComplete,
}: Props) {
  const [selectedStep, setSelectedStep] = useState<string | null>(null);
  const [editingParams, setEditingParams] = useState<Record<string, string>>({});
  const [chatInput, setChatInput] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const [isExecuting, setIsExecuting] = useState(false);
  const [isModifying, setIsModifying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [executionLog, setExecutionLog] = useState<string[]>([]);
  const [localSteps, setLocalSteps] = useState<BuildStep[]>([]);
  const chatInputRef = useRef<HTMLInputElement>(null);
  const pollingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Cleanup polling timer on unmount
  useEffect(() => () => {
    if (pollingTimerRef.current) clearTimeout(pollingTimerRef.current);
  }, []);

  useEffect(() => {
    if (plan?.steps) {
      setLocalSteps(plan.steps);
    }
  }, [plan?.steps]);

  // Auto-create BuildPlan when navigated here with a session but no plan yet
  useEffect(() => {
    if (sessionId && !plan && !isCreating) {
      handleCreatePlan();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  // --- Poll plan status until planned or failed ---
  const startPolling = useCallback(
    (
      planId: string,
      onDone: (planData: Record<string, unknown>, steps: BuildStep[]) => void,
      onError: (msg: string) => void,
    ) => {
      const poll = async () => {
        try {
          const planRes = await fetch(`${API_BASE}/build-plans/${planId}`, {
            headers: { Authorization: `Bearer ${idToken}` },
          });
          if (!planRes.ok) {
            pollingTimerRef.current = setTimeout(poll, 3000);
            return;
          }
          const planData = await planRes.json();
          if (planData.plan_status === "planned") {
            const stepsRes = await fetch(`${API_BASE}/build-plans/${planId}/steps`, {
              headers: { Authorization: `Bearer ${idToken}` },
            });
            if (!stepsRes.ok) {
              onError("ステップ取得に失敗しました");
              return;
            }
            const stepsData = await stepsRes.json();
            onDone(planData as Record<string, unknown>, stepsData.steps ?? []);
          } else if (planData.plan_status === "failed") {
            onError(planData.reasoning || "BuildPlan 処理に失敗しました");
          } else {
            // Still creating or modifying — keep polling
            pollingTimerRef.current = setTimeout(poll, 3000);
          }
        } catch {
          // Retry on network error
          pollingTimerRef.current = setTimeout(poll, 3000);
        }
      };
      pollingTimerRef.current = setTimeout(poll, 3000);
    },
    [idToken],
  );

  // --- Create BuildPlan ---
  const handleCreatePlan = useCallback(async () => {
    setIsCreating(true);
    setError(null);
    setExecutionLog(["AI が図面を分析中... (1〜2分かかる場合があります)"]);
    try {
      const res = await fetch(`${API_BASE}/sessions/${sessionId}/build-plans`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${idToken}`,
        },
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error ?? "BuildPlan 作成に失敗");
      }
      const { plan_id: planId } = await res.json();
      // Backend returns 202 — poll until status = "planned"
      startPolling(
        planId,
        (planData, steps) => {
          onPlanCreated({
            plan_id: planId,
            session_id: String(planData.session_id ?? ""),
            node_id: String(planData.node_id ?? ""),
            total_steps: steps.length,
            reasoning: String(planData.reasoning ?? ""),
            steps,
          });
          setExecutionLog((prev) => [...prev, `BuildPlan 作成完了: ${steps.length} ステップ`]);
          setIsCreating(false);
        },
        (msg) => {
          setError(msg);
          setExecutionLog((prev) => [...prev, `エラー: ${msg}`]);
          setIsCreating(false);
        },
      );
    } catch (e) {
      setError(String(e));
      setExecutionLog((prev) => [...prev, `エラー: ${e}`]);
      setIsCreating(false);
    }
  }, [sessionId, idToken, onPlanCreated, startPolling]);

  // --- Execute Plan ---
  const handleExecute = useCallback(
    async (fromStep = "0001") => {
      if (!plan) return;
      setIsExecuting(true);
      setError(null);
      setExecutionLog((prev) => [...prev, `Step ${fromStep} から実行開始...`]);
      try {
        const res = await fetch(`${API_BASE}/build-plans/${plan.plan_id}/execute`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${idToken}`,
          },
          body: JSON.stringify({ from_step: fromStep }),
        });
        if (!res.ok) {
          const data = await res.json();
          throw new Error(data.error ?? "実行に失敗");
        }
        const data = await res.json();
        // Update local step statuses
        if (data.results) {
          setLocalSteps((prev) =>
            prev.map((s) => {
              const result = data.results.find((r: { step_seq: string }) => r.step_seq === s.step_seq);
              return result ? { ...s, status: result.status } : s;
            }),
          );
        }
        setExecutionLog((prev) => [
          ...prev,
          `実行完了: ${data.executed_count} ステップ`,
        ]);
        if (data.gltf_url) {
          onExecutionComplete(data.gltf_url, plan.node_id);
        }
      } catch (e) {
        setError(String(e));
        setExecutionLog((prev) => [...prev, `実行エラー: ${e}`]);
      } finally {
        setIsExecuting(false);
      }
    },
    [plan, idToken, onExecutionComplete],
  );

  // --- Modify Step ---
  const handleModifyByParams = useCallback(async () => {
    if (!plan || !selectedStep) return;
    setIsModifying(true);
    setError(null);
    setExecutionLog((prev) => [...prev, `Step ${selectedStep} パラメータ修正中...`]);
    try {
      const params: Record<string, { value: number | string; unit: string; source: string; confidence: number }> = {};
      for (const [key, val] of Object.entries(editingParams)) {
        const numVal = parseFloat(val);
        params[key] = { value: isNaN(numVal) ? val : numVal, unit: "mm", source: "user", confidence: 1.0 };
      }
      const res = await fetch(
        `${API_BASE}/build-plans/${plan.plan_id}/steps/${selectedStep}/modify`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${idToken}` },
          body: JSON.stringify({ type: "parameter", parameters: params }),
        },
      );
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error ?? "修正に失敗");
      }
      const { plan_id: planId } = await res.json();
      // Backend returns 202 — poll until status = "planned"
      startPolling(
        planId,
        (_planData, steps) => {
          setLocalSteps(steps);
          setExecutionLog((prev) => [...prev, `修正完了: ${steps.length} ステップ更新`]);
          setIsModifying(false);
        },
        (msg) => {
          setError(msg);
          setIsModifying(false);
        },
      );
    } catch (e) {
      setError(String(e));
      setIsModifying(false);
    }
  }, [plan, selectedStep, editingParams, idToken, startPolling]);

  const handleModifyByChat = useCallback(async () => {
    if (!plan || !selectedStep || !chatInput.trim()) return;
    setIsModifying(true);
    setError(null);
    const instruction = chatInput.trim();
    setChatInput("");
    setExecutionLog((prev) => [...prev, `AI修正: 「${instruction}」`]);
    try {
      const res = await fetch(
        `${API_BASE}/build-plans/${plan.plan_id}/steps/${selectedStep}/modify`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${idToken}` },
          body: JSON.stringify({ type: "natural_language", instruction }),
        },
      );
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error ?? "修正に失敗");
      }
      const { plan_id: planId } = await res.json();
      // Backend returns 202 — poll until status = "planned"
      startPolling(
        planId,
        (_planData, steps) => {
          setLocalSteps(steps);
          setExecutionLog((prev) => [...prev, `AI修正完了: ${steps.length} ステップ更新`]);
          setIsModifying(false);
        },
        (msg) => {
          setError(msg);
          setIsModifying(false);
        },
      );
    } catch (e) {
      setError(String(e));
      setIsModifying(false);
    }
  }, [plan, selectedStep, chatInput, idToken, startPolling]);

  // --- Select step ---
  const handleStepClick = useCallback(
    (stepSeq: string) => {
      setSelectedStep(stepSeq === selectedStep ? null : stepSeq);
      setEditingParams({});
      const step = localSteps.find((s) => s.step_seq === stepSeq);
      if (step) {
        const params: Record<string, string> = {};
        for (const [key, val] of Object.entries(step.parameters)) {
          const p = val as StepParameter;
          params[key] = String(p.value);
        }
        setEditingParams(params);
      }
    },
    [selectedStep, localSteps],
  );

  // --- No plan yet: show loading / retry ---
  if (!plan) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-4 p-6">
        {isCreating ? (
          <div className="text-center">
            <div className="mx-auto mb-4 h-10 w-10 animate-spin rounded-full border-4 border-indigo-200 border-t-indigo-600" />
            <h2 className="text-base font-semibold text-gray-800">BuildPlan を作成中...</h2>
            <p className="mt-1 text-sm text-gray-500">
              AI が図面を分析し、段階的構築プランを生成しています
            </p>
            {executionLog.length > 0 && (
              <p className="mt-3 text-xs text-indigo-600">{executionLog[executionLog.length - 1]}</p>
            )}
          </div>
        ) : (
          <div className="text-center">
            <h2 className="text-lg font-semibold text-gray-800">段階的構築モード</h2>
            <p className="mt-1 text-sm text-gray-500">
              AIが図面を分析し、1ステップずつ3Dモデルを構築します
            </p>
            {error && (
              <p className="mt-3 text-sm text-red-600" role="alert">{error}</p>
            )}
            <button
              type="button"
              onClick={handleCreatePlan}
              disabled={!sessionId}
              className="mt-4 rounded-lg bg-indigo-600 px-6 py-2.5 text-sm font-medium text-white shadow-sm hover:bg-indigo-700 disabled:opacity-50"
            >
              再試行
            </button>
          </div>
        )}
      </div>
    );
  }

  // --- Plan exists: show steps ---
  const selectedStepData = localSteps.find((s) => s.step_seq === selectedStep);

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 border-b bg-indigo-50 px-4 py-2">
        <span className="text-xs font-semibold text-indigo-700">
          BuildPlan ({plan.total_steps} ステップ)
        </span>
        <div className="ml-auto flex gap-2">
          <button
            type="button"
            onClick={() => handleExecute(selectedStep ?? "0001")}
            disabled={isExecuting}
            className="rounded bg-green-600 px-3 py-1 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50"
          >
            {isExecuting ? "実行中..." : selectedStep ? `Step ${selectedStep} から実行` : "全実行"}
          </button>
        </div>
      </div>

      {/* Step list */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        <div className="w-1/2 overflow-y-auto border-r" role="list" aria-label="構築ステップ一覧">
          {localSteps.map((step) => {
            const isSelected = step.step_seq === selectedStep;
            return (
              <button
                key={step.step_seq}
                type="button"
                role="listitem"
                onClick={() => handleStepClick(step.step_seq)}
                className={`flex w-full items-start gap-2 border-b px-3 py-2 text-left transition-colors ${
                  isSelected ? "bg-indigo-50 ring-1 ring-indigo-300" : "hover:bg-gray-50"
                }`}
                aria-selected={isSelected}
              >
                <span className={`mt-0.5 text-sm font-bold ${STATUS_COLOR[step.status] ?? "text-gray-400"}`}>
                  {STATUS_ICON[step.status] ?? "?"}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="text-[10px] font-mono text-gray-400">{step.step_seq}</span>
                    <span className="rounded bg-gray-100 px-1 text-[10px] text-gray-500">
                      {STEP_TYPE_LABEL[step.step_type] ?? step.step_type}
                    </span>
                    {step.group_id && (
                      <span className="rounded bg-blue-50 px-1 text-[10px] text-blue-500">
                        {step.group_id}
                      </span>
                    )}
                  </div>
                  <p className="truncate text-xs font-medium text-gray-800">{step.step_name}</p>
                  {step.confidence < 0.85 && (
                    <span className="text-[10px] text-amber-600">
                      確度: {(step.confidence * 100).toFixed(0)}%
                    </span>
                  )}
                </div>
              </button>
            );
          })}
        </div>

        {/* Detail / Edit panel */}
        <div className="flex w-1/2 flex-col overflow-y-auto">
          {selectedStepData ? (
            <div className="flex flex-col gap-3 p-3">
              {/* Step info */}
              <div>
                <h3 className="text-sm font-semibold text-gray-800">{selectedStepData.step_name}</h3>
                {selectedStepData.ai_reasoning && (
                  <p className="mt-1 text-[11px] text-gray-500">{selectedStepData.ai_reasoning}</p>
                )}
              </div>

              {/* Parameter editor */}
              <fieldset className="rounded border p-2">
                <legend className="px-1 text-[10px] font-semibold text-gray-500">パラメータ</legend>
                <div className="space-y-1.5">
                  {Object.entries(selectedStepData.parameters).map(([key, val]) => {
                    const p = val as StepParameter;
                    return (
                      <label key={key} className="flex items-center gap-2 text-xs">
                        <span className="w-28 truncate font-medium text-gray-700" title={key}>{key}</span>
                        <input
                          type="text"
                          value={editingParams[key] ?? String(p.value)}
                          onChange={(e) => setEditingParams((prev) => ({ ...prev, [key]: e.target.value }))}
                          className="flex-1 rounded border border-gray-300 px-2 py-1 text-xs focus:border-indigo-400 focus:ring-1 focus:ring-indigo-400"
                        />
                        <span className="w-8 text-[10px] text-gray-400">{p.unit}</span>
                        {p.source !== "user" && (
                          <span
                            className={`rounded px-1 text-[9px] ${
                              p.confidence >= 0.9 ? "bg-green-50 text-green-600" :
                              p.confidence >= 0.7 ? "bg-amber-50 text-amber-600" :
                              "bg-red-50 text-red-600"
                            }`}
                          >
                            {p.source} {(p.confidence * 100).toFixed(0)}%
                          </span>
                        )}
                      </label>
                    );
                  })}
                </div>
                <button
                  type="button"
                  onClick={handleModifyByParams}
                  disabled={isModifying}
                  className="mt-2 w-full rounded bg-amber-500 px-3 py-1 text-xs font-medium text-white hover:bg-amber-600 disabled:opacity-50"
                >
                  {isModifying ? "修正中..." : "パラメータで修正"}
                </button>
              </fieldset>

              {/* NL chat modification */}
              <div className="rounded border p-2">
                <p className="mb-1 text-[10px] font-semibold text-gray-500">自然言語で修正</p>
                <div className="flex gap-1">
                  <input
                    ref={chatInputRef}
                    type="text"
                    value={chatInput}
                    onChange={(e) => setChatInput(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") handleModifyByChat(); }}
                    placeholder="例: 直径を8mmに変更"
                    className="flex-1 rounded border border-gray-300 px-2 py-1 text-xs focus:border-indigo-400 focus:ring-1 focus:ring-indigo-400"
                    disabled={isModifying}
                  />
                  <button
                    type="button"
                    onClick={handleModifyByChat}
                    disabled={isModifying || !chatInput.trim()}
                    className="rounded bg-indigo-600 px-3 py-1 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                  >
                    送信
                  </button>
                </div>
              </div>

              {/* CadQuery code preview */}
              <details className="rounded border">
                <summary className="cursor-pointer px-2 py-1 text-[10px] font-semibold text-gray-500 hover:bg-gray-50">
                  CadQuery コード
                </summary>
                <pre className="max-h-40 overflow-auto bg-gray-900 p-2 text-[10px] leading-relaxed text-green-300">
                  {selectedStepData.cq_code}
                </pre>
              </details>
            </div>
          ) : (
            <div className="flex flex-1 items-center justify-center p-4 text-xs text-gray-400">
              ステップを選択してください
            </div>
          )}
        </div>
      </div>

      {/* Execution log (AI thinking process) */}
      {executionLog.length > 0 && (
        <div className="max-h-24 shrink-0 overflow-y-auto border-t bg-gray-50 px-3 py-2">
          <p className="mb-1 text-[10px] font-semibold text-gray-500">実行ログ</p>
          {executionLog.map((log, i) => (
            <p key={i} className="text-[10px] text-gray-600">
              <span className="text-gray-400">{String(i + 1).padStart(2, "0")}</span>{" "}
              {log}
            </p>
          ))}
        </div>
      )}

      {error && (
        <div className="shrink-0 border-t bg-red-50 px-3 py-2" role="alert">
          <p className="text-xs text-red-600">{error}</p>
        </div>
      )}
    </div>
  );
}
