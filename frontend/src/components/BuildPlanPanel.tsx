import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { API_BASE } from "../config";
import { StepPreview3D } from "./StepPreview3D";

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
  const [checkedSteps, setCheckedSteps] = useState<Set<string>>(new Set());
  const [batchParams, setBatchParams] = useState<Record<string, Record<string, string>>>({});
  const [batchInstruction, setBatchInstruction] = useState("");
  const [showExecConfirm, setShowExecConfirm] = useState(false);
  const [execElapsed, setExecElapsed] = useState(0);
  const chatInputRef = useRef<HTMLInputElement>(null);
  const pollingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const execTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Auto-detect starting step: earliest modified → earliest non-completed → "0001"
  const autoFromStep = useMemo(
    () =>
      localSteps.find((s) => s.status === "modified")?.step_seq ??
      localSteps.find((s) => s.status !== "completed")?.step_seq ??
      "0001",
    [localSteps],
  );
  const hasModified = useMemo(
    () => localSteps.some((s) => s.status === "modified"),
    [localSteps],
  );

  // Cleanup timers on unmount
  useEffect(() => () => {
    if (pollingTimerRef.current) clearTimeout(pollingTimerRef.current);
    if (execTimerRef.current) clearInterval(execTimerRef.current);
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

  // --- Execute Plan (with confirmation) ---
  const handleConfirmExecute = useCallback(async () => {
    if (!plan) return;
    setShowExecConfirm(false);
    setIsExecuting(true);
    setExecElapsed(0);
    setError(null);
    execTimerRef.current = setInterval(() => setExecElapsed((p) => p + 1), 1000);
    setExecutionLog((prev) => [...prev, `Step ${autoFromStep} から実行開始...`]);
    try {
      const res = await fetch(`${API_BASE}/build-plans/${plan.plan_id}/execute`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${idToken}`,
        },
        body: JSON.stringify({ from_step: autoFromStep }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error ?? "実行に失敗");
      }
      const data = await res.json();
      if (data.results) {
        setLocalSteps((prev) =>
          prev.map((s) => {
            const result = data.results.find((r: { step_seq: string }) => r.step_seq === s.step_seq);
            return result ? { ...s, status: result.status } : s;
          }),
        );
      }
      setExecutionLog((prev) => [...prev, `実行完了: ${data.executed_count} ステップ`]);
      if (data.gltf_url) {
        onExecutionComplete(data.gltf_url, plan.node_id);
      }
    } catch (e) {
      setError(String(e));
      setExecutionLog((prev) => [...prev, `実行エラー: ${e}`]);
    } finally {
      if (execTimerRef.current) {
        clearInterval(execTimerRef.current);
        execTimerRef.current = null;
      }
      setIsExecuting(false);
    }
  }, [plan, autoFromStep, idToken, onExecutionComplete]);

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
      const targetStepSeq = selectedStep; // capture for closure
      startPolling(
        planId,
        (_planData, steps) => {
          setLocalSteps(steps);
          // Reset editingParams to reflect the new persisted values
          const updated = steps.find((s) => s.step_seq === targetStepSeq);
          if (updated) {
            const newParams: Record<string, string> = {};
            for (const [k, v] of Object.entries(updated.parameters)) {
              newParams[k] = String((v as StepParameter).value);
            }
            setEditingParams(newParams);
          }
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

  // --- Toggle batch check ---
  const toggleCheck = useCallback(
    (stepSeq: string) => {
      setCheckedSteps((prev) => {
        const next = new Set(prev);
        if (next.has(stepSeq)) {
          next.delete(stepSeq);
          setBatchParams((p) => {
            const q = { ...p };
            delete q[stepSeq];
            return q;
          });
        } else {
          next.add(stepSeq);
          const step = localSteps.find((s) => s.step_seq === stepSeq);
          if (step) {
            const params: Record<string, string> = {};
            for (const [k, v] of Object.entries(step.parameters)) {
              params[k] = String((v as StepParameter).value);
            }
            setBatchParams((p) => ({ ...p, [stepSeq]: params }));
          }
        }
        return next;
      });
    },
    [localSteps],
  );

  // --- Batch modify ---
  const handleBatchModify = useCallback(async () => {
    if (!plan || (checkedSteps.size === 0 && !batchInstruction.trim())) return;
    setIsModifying(true);
    setError(null);
    setExecutionLog((prev) => [...prev, `${checkedSteps.size} ステップを一括修正中...`]);

    const modifications = Array.from(checkedSteps).map((seq) => {
      const rawParams = batchParams[seq] ?? {};
      if (Object.keys(rawParams).length === 0) return { step_seq: seq };
      const params: Record<string, { value: number | string; unit: string; source: string; confidence: number }> = {};
      for (const [key, val] of Object.entries(rawParams)) {
        const numVal = parseFloat(val);
        params[key] = { value: isNaN(numVal) ? val : numVal, unit: "mm", source: "user", confidence: 1.0 };
      }
      return { step_seq: seq, parameters: params };
    });

    try {
      const res = await fetch(`${API_BASE}/build-plans/${plan.plan_id}/modify`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${idToken}` },
        body: JSON.stringify({ modifications, instruction: batchInstruction }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error ?? "修正に失敗");
      }
      const { plan_id: planId } = await res.json();
      const seqsAtSubmit = new Set(checkedSteps);
      startPolling(
        planId,
        (_planData, steps) => {
          setLocalSteps(steps);
          const newBatchParams: Record<string, Record<string, string>> = {};
          for (const seq of seqsAtSubmit) {
            const updated = steps.find((s) => s.step_seq === seq);
            if (updated) {
              const p: Record<string, string> = {};
              for (const [k, v] of Object.entries(updated.parameters)) {
                p[k] = String((v as StepParameter).value);
              }
              newBatchParams[seq] = p;
            }
          }
          setBatchParams(newBatchParams);
          setBatchInstruction("");
          setExecutionLog((prev) => [...prev, `一括修正完了: ${steps.length} ステップ更新`]);
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
  }, [plan, checkedSteps, batchParams, batchInstruction, idToken, startPolling]);

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
    <div className="relative flex flex-1 flex-col overflow-hidden">
      {/* Confirmation dialog */}
      {showExecConfirm && (
        <div
          className="absolute inset-0 z-50 flex items-center justify-center bg-black/60"
          role="dialog"
          aria-modal="true"
        >
          <div className="w-80 rounded-2xl bg-white p-6 shadow-2xl">
            <h3 className="text-sm font-bold text-gray-900">3D モデルを生成しますか？</h3>
            <p className="mt-2 text-xs text-gray-600">
              {hasModified ? (
                <>
                  Step{" "}
                  <span className="font-semibold text-amber-600">{autoFromStep}</span>{" "}
                  以降を再実行します（修正済みステップを検出しました）。
                </>
              ) : (
                <>
                  Step{" "}
                  <span className="font-semibold text-gray-800">{autoFromStep}</span>{" "}
                  から実行します。
                </>
              )}
            </p>
            <p className="mt-1 text-xs text-gray-500">
              CadQuery でステップを順番に処理します。形状の複雑さによって数十秒〜数分かかる場合があります。
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowExecConfirm(false)}
                className="rounded-lg border px-4 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
              >
                キャンセル
              </button>
              <button
                type="button"
                onClick={handleConfirmExecute}
                className="rounded-lg bg-green-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-green-700"
              >
                実行する
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Execution progress overlay */}
      {isExecuting && (
        <div className="absolute inset-0 z-40 flex flex-col items-center justify-center bg-gray-950/85 backdrop-blur-sm">
          <div className="h-10 w-10 animate-spin rounded-full border-4 border-green-800 border-t-green-400" />
          <p className="mt-4 text-sm font-semibold text-white">3D モデル生成中...</p>
          <p className="mt-1 text-xs text-gray-400">CadQuery がステップを順番に処理しています</p>
          <p className="mt-1 font-mono text-xs text-green-400">経過: {execElapsed} 秒</p>
          {executionLog.length > 0 && (
            <p className="mt-2 max-w-xs truncate text-center text-[10px] text-gray-500">
              {executionLog[executionLog.length - 1]}
            </p>
          )}
        </div>
      )}

      {/* Header */}
      <div className="flex items-center gap-2 border-b bg-indigo-50 px-4 py-2">
        <span className="text-xs font-semibold text-indigo-700">
          BuildPlan ({plan.total_steps} ステップ)
        </span>
        <div className="ml-auto flex items-center gap-2">
          {hasModified && (
            <span className="text-[10px] text-amber-600">✎ Step {autoFromStep} から再実行</span>
          )}
          <button
            type="button"
            onClick={() => setShowExecConfirm(true)}
            disabled={isExecuting || localSteps.length === 0}
            className="rounded bg-green-600 px-3 py-1 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50"
          >
            3D 生成
          </button>
        </div>
      </div>

      {/* Step list */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        <div className="w-52 shrink-0 overflow-y-auto border-r" role="list" aria-label="構築ステップ一覧">
          {localSteps.map((step) => {
            const isSelected = step.step_seq === selectedStep;
            const isChecked = checkedSteps.has(step.step_seq);
            return (
              <div
                key={step.step_seq}
                className={`flex items-stretch border-b transition-colors ${
                  isChecked
                    ? "bg-violet-50 ring-1 ring-inset ring-violet-300"
                    : isSelected
                    ? "bg-indigo-50 ring-1 ring-inset ring-indigo-300"
                    : "hover:bg-gray-50"
                }`}
              >
                <label className="flex shrink-0 cursor-pointer items-start px-2 pt-2.5">
                  <input
                    type="checkbox"
                    checked={isChecked}
                    onChange={() => toggleCheck(step.step_seq)}
                    className="h-3.5 w-3.5 cursor-pointer rounded border-gray-300 text-violet-600 focus:ring-violet-400"
                  />
                </label>
                <button
                  type="button"
                  role="listitem"
                  onClick={() => handleStepClick(step.step_seq)}
                  className="flex flex-1 items-start gap-2 py-2 pr-3 text-left"
                  aria-selected={isSelected}
                >
                  <span className={`mt-0.5 text-sm font-bold ${STATUS_COLOR[step.status] ?? "text-gray-400"}`}>
                    {STATUS_ICON[step.status] ?? "?"}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className="text-[10px] font-mono text-gray-400">{step.step_seq}</span>
                      {step.step_seq === autoFromStep && (
                        <span className="rounded bg-green-100 px-1 text-[9px] font-bold text-green-700">▶</span>
                      )}
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
              </div>
            );
          })}
        </div>

        {/* 3D Preview (center) */}
        <div className="relative flex-1 min-w-0 border-r">
          <StepPreview3D
            step={selectedStepData ?? null}
            allSteps={localSteps}
            planId={plan.plan_id}
            idToken={idToken}
          />
        </div>

        {/* Detail / Edit panel */}
        <div className="flex w-64 shrink-0 flex-col overflow-y-auto">
          {checkedSteps.size > 0 ? (
            <div className="flex flex-col gap-3 p-3">
              {/* Batch header */}
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold text-violet-700">
                  {checkedSteps.size} ステップを一括修正
                </span>
                <button
                  type="button"
                  onClick={() => { setCheckedSteps(new Set()); setBatchParams({}); setBatchInstruction(""); }}
                  className="text-xs text-gray-400 hover:text-gray-600"
                >
                  選択クリア
                </button>
              </div>
              {/* Per-step parameter editors */}
              {Array.from(checkedSteps).sort().map((seq) => {
                const step = localSteps.find((s) => s.step_seq === seq);
                if (!step) return null;
                return (
                  <details key={seq} open className="rounded border">
                    <summary className="cursor-pointer bg-gray-50 px-2 py-1.5 text-xs font-semibold text-gray-700 hover:bg-gray-100">
                      {seq} · {step.step_name}
                    </summary>
                    <div className="space-y-1.5 p-2">
                      {Object.entries(step.parameters).map(([key, val]) => {
                        const p = val as StepParameter;
                        return (
                          <label key={key} className="flex items-center gap-2 text-xs">
                            <span className="w-24 truncate font-medium text-gray-700" title={key}>{key}</span>
                            <input
                              type="text"
                              value={batchParams[seq]?.[key] ?? String(p.value)}
                              onChange={(e) =>
                                setBatchParams((prev) => ({
                                  ...prev,
                                  [seq]: { ...(prev[seq] ?? {}), [key]: e.target.value },
                                }))
                              }
                              className="flex-1 rounded border border-gray-300 px-2 py-1 text-xs focus:border-violet-400 focus:ring-1 focus:ring-violet-400"
                              disabled={isModifying}
                            />
                            <span className="w-8 text-[10px] text-gray-400">{p.unit}</span>
                          </label>
                        );
                      })}
                    </div>
                  </details>
                );
              })}
              {/* NL instruction */}
              <div className="rounded border p-2">
                <p className="mb-1 text-[10px] font-semibold text-gray-500">自然言語での追加指示（任意）</p>
                <textarea
                  value={batchInstruction}
                  onChange={(e) => setBatchInstruction(e.target.value)}
                  placeholder="例: 全ての穴を同じ直径にそろえてください"
                  className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs focus:border-violet-400 focus:ring-1 focus:ring-violet-400"
                  rows={2}
                  disabled={isModifying}
                />
              </div>
              {/* Submit */}
              <button
                type="button"
                onClick={handleBatchModify}
                disabled={isModifying}
                className="w-full rounded bg-violet-600 py-2 text-sm font-medium text-white hover:bg-violet-700 disabled:opacity-50"
              >
                {isModifying ? "AI修正中..." : `${checkedSteps.size} ステップを一括修正`}
              </button>
            </div>
          ) : selectedStepData ? (
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
            <div className="flex flex-1 items-center justify-center p-4 text-center text-xs text-gray-400">
              ステップをクリックして詳細表示<br />チェックして一括修正
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
