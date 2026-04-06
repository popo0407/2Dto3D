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
  status: "proposed" | "confirmed" | "executing" | "completed" | "planned" | "modified" | "failed";
  ai_reasoning: string;
  choices?: Array<{ id: string; label: string }>;
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

interface ChatMessage {
  id: string;
  role: "ai" | "user" | "system";
  content: string;
  choices?: Array<{ id: string; label: string }>;
}

interface PollState {
  plan_status: string;
  current_step_seq: string;
  current_step_status: string;
  reasoning: string;
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
// Constants
// ---------------------------------------------------------------------------

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
// Sub-components
// ---------------------------------------------------------------------------

function DrawingViewer({ url }: { url: string | null }) {
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const dragging = useRef(false);
  const lastPoint = useRef({ x: 0, y: 0 });
  const containerRef = useRef<HTMLDivElement>(null);

  // Non-passive wheel listener (needed to call preventDefault)
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      setScale((prev) => Math.min(8, Math.max(0.2, prev * (e.deltaY < 0 ? 1.15 : 1 / 1.15))));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  const handleMouseDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return;
    dragging.current = true;
    lastPoint.current = { x: e.clientX, y: e.clientY };
  };
  const handleMouseMove = (e: React.MouseEvent) => {
    if (!dragging.current) return;
    const dx = e.clientX - lastPoint.current.x;
    const dy = e.clientY - lastPoint.current.y;
    lastPoint.current = { x: e.clientX, y: e.clientY };
    setOffset((prev) => ({ x: prev.x + dx, y: prev.y + dy }));
  };
  const handleMouseUp = () => {
    dragging.current = false;
  };
  const handleReset = () => {
    setScale(1);
    setOffset({ x: 0, y: 0 });
  };

  if (!url) {
    return (
      <div className="flex h-full items-center justify-center bg-gray-100 text-xs text-gray-400">
        2D 図面を読み込み中...
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="relative h-full w-full select-none overflow-hidden bg-gray-50 cursor-grab active:cursor-grabbing"
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      onDoubleClick={handleReset}
    >
      {/* Transformed image layer */}
      <div
        className="pointer-events-none absolute inset-0 flex items-center justify-center p-2"
        style={{
          transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})`,
          transformOrigin: "center",
        }}
      >
        <img
          src={url}
          alt="2D図面"
          draggable={false}
          className="max-h-full max-w-full object-contain"
        />
      </div>

      {/* Zoom controls */}
      <div
        className="absolute bottom-2 right-2 z-10 flex items-center gap-0.5 rounded bg-white/90 px-2 py-1 shadow text-[10px] text-gray-600 backdrop-blur-sm"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          title="縮小 (スクロールダウン)"
          onClick={() => setScale((p) => Math.max(0.2, p / 1.2))}
          className="flex h-5 w-5 items-center justify-center rounded hover:bg-gray-100 font-bold"
        >
          −
        </button>
        <span className="w-9 text-center font-mono">{Math.round(scale * 100)}%</span>
        <button
          type="button"
          title="拡大 (スクロールアップ)"
          onClick={() => setScale((p) => Math.min(8, p * 1.2))}
          className="flex h-5 w-5 items-center justify-center rounded hover:bg-gray-100 font-bold"
        >
          +
        </button>
        <button
          type="button"
          title="リセット (ダブルクリックでも可)"
          onClick={handleReset}
          className="ml-1 flex h-5 w-5 items-center justify-center rounded hover:bg-gray-100"
        >
          ↺
        </button>
      </div>
    </div>
  );
}

function ChatBubble({ message }: { message: ChatMessage }) {
  const isAi = message.role === "ai";
  const isSystem = message.role === "system";
  return (
    <div className={`flex ${isAi || isSystem ? "justify-start" : "justify-end"} mb-2`}>
      <div
        className={`max-w-[88%] rounded-xl px-3 py-2 text-xs ${
          isSystem
            ? "bg-green-50 text-[10px] italic text-green-700"
            : isAi
            ? "border border-gray-100 bg-white text-gray-800 shadow-sm"
            : "bg-indigo-600 text-white"
        }`}
      >
        {isAi && (
          <span className="mb-1 block text-[10px] font-semibold text-indigo-500">AI</span>
        )}
        <p className="whitespace-pre-wrap leading-relaxed">{message.content}</p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function BuildPlanPanel({
  sessionId,
  idToken,
  plan,
  onPlanCreated,
  onExecutionComplete,
}: Props) {
  const [planId, setPlanId] = useState<string | null>(plan?.plan_id ?? null);
  const [nodeId, setNodeId] = useState<string>(plan?.node_id ?? "");
  const [pollState, setPollState] = useState<PollState | null>(null);
  const [currentStep, setCurrentStep] = useState<BuildStep | null>(null);
  const [confirmedSteps, setConfirmedSteps] = useState<BuildStep[]>([]);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [userInput, setUserInput] = useState("");
  const [activeTab, setActiveTab] = useState<"chat" | "step">("chat");
  const [drawingUrl, setDrawingUrl] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [isWaiting, setIsWaiting] = useState(false);
  const [isExecuting, setIsExecuting] = useState(false);
  const [execElapsed, setExecElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const pollingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const execTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const hasCreatedRef = useRef(false);
  const prevStepSeqRef = useRef<string>("");

  // Cleanup on unmount
  useEffect(
    () => () => {
      if (pollingTimerRef.current) clearTimeout(pollingTimerRef.current);
      if (execTimerRef.current) clearInterval(execTimerRef.current);
    },
    [],
  );

  // Auto-scroll chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages]);

  // Fetch drawing image URL
  useEffect(() => {
    if (!sessionId || !idToken) return;
    fetch(`${API_BASE}/sessions/${sessionId}/drawing`, {
      headers: { Authorization: `Bearer ${idToken}` },
    })
      .then((r) => r.json())
      .then((d) => {
        if (d.url) setDrawingUrl(d.url);
      })
      .catch(() => {});
  }, [sessionId, idToken]);

  // --- Poll plan status ---
  const startPolling = useCallback(
    (pid: string) => {
      if (pollingTimerRef.current) clearTimeout(pollingTimerRef.current);
      const poll = async () => {
        try {
          const r = await fetch(`${API_BASE}/build-plans/${pid}`, {
            headers: { Authorization: `Bearer ${idToken}` },
          });
          if (!r.ok) {
            pollingTimerRef.current = setTimeout(poll, 3000);
            return;
          }
          const data = await r.json();
          const ps: PollState = {
            plan_status: data.plan_status ?? "",
            current_step_seq: data.current_step_seq ?? "",
            current_step_status: data.current_step_status ?? "",
            reasoning: data.reasoning ?? "",
          };
          setPollState(ps);

          if (ps.plan_status === "failed") {
            setError(ps.reasoning || "BuildPlan の処理に失敗しました");
            setIsWaiting(false);
            return;
          }

          if (
            ps.plan_status === "interactive" &&
            ps.current_step_status === "ready" &&
            ps.current_step_seq &&
            ps.current_step_seq !== prevStepSeqRef.current
          ) {
            prevStepSeqRef.current = ps.current_step_seq;
            try {
              const sr = await fetch(
                `${API_BASE}/build-plans/${pid}/steps/${ps.current_step_seq}`,
                { headers: { Authorization: `Bearer ${idToken}` } },
              );
              if (sr.ok) {
                const step: BuildStep = await sr.json();
                setCurrentStep(step);
                setIsWaiting(false);
                const explanation = step.ai_reasoning || "このステップを提案します。";
                const stepLabel = STEP_TYPE_LABEL[step.step_type] ?? step.step_type;
                const content = `Step ${step.step_seq} — ${step.step_name} (${stepLabel})\n\n${explanation}`;
                setChatMessages((prev) => [
                  ...prev.filter((m) => m.role !== "system" || !m.content.includes("生成中")),
                  {
                    id: `ai-${step.step_seq}-${Date.now()}`,
                    role: "ai",
                    content,
                    choices: (step.choices ?? []).length > 0 ? step.choices : undefined,
                  },
                ]);
              } else {
                pollingTimerRef.current = setTimeout(poll, 3000);
              }
            } catch {
              pollingTimerRef.current = setTimeout(poll, 3000);
            }
            return;
          }

          if (ps.plan_status === "interactive" && ps.current_step_status === "done") {
            setIsWaiting(false);
            setCurrentStep(null);
            setChatMessages((prev) => [
              ...prev.filter((m) => m.role !== "system" || !m.content.includes("生成中")),
              {
                id: `sys-done-${Date.now()}`,
                role: "system",
                content: "✓ 全ステップが確定しました。右上の「3D 生成」ボタンで実行できます。",
              },
            ]);
            return;
          }

          // Still creating / generating / revising — keep polling
          pollingTimerRef.current = setTimeout(poll, 3000);
        } catch {
          pollingTimerRef.current = setTimeout(poll, 3000);
        }
      };
      pollingTimerRef.current = setTimeout(poll, 2000);
    },
    [idToken],
  );

  // --- Create BuildPlan ---
  const handleCreatePlan = useCallback(async () => {
    if (hasCreatedRef.current) return;
    hasCreatedRef.current = true;
    setIsCreating(true);
    setError(null);
    try {
      const r = await fetch(`${API_BASE}/sessions/${sessionId}/build-plans`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${idToken}` },
      });
      if (!r.ok) {
        const d = await r.json();
        throw new Error(d.error ?? "BuildPlan 作成に失敗");
      }
      const { plan_id: pid, node_id: nid } = await r.json();
      setPlanId(pid);
      if (nid) setNodeId(nid);
      onPlanCreated({
        plan_id: pid,
        session_id: sessionId,
        node_id: nid ?? "",
        total_steps: 0,
        reasoning: "",
        steps: [],
      });
      setIsCreating(false);
      setIsWaiting(true);
      setChatMessages([
        {
          id: "sys-init",
          role: "system",
          content: "AI が図面を分析し、最初のステップを生成中です...",
        },
      ]);
      startPolling(pid);
    } catch (e) {
      setError(String(e));
      setIsCreating(false);
      hasCreatedRef.current = false;
    }
  }, [sessionId, idToken, onPlanCreated, startPolling]);

  // Auto-create on mount
  useEffect(() => {
    if (sessionId && idToken && !planId && !isCreating) {
      handleCreatePlan();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, idToken]);

  // --- Confirm step ---
  const handleConfirm = useCallback(async () => {
    if (!planId || !currentStep) return;
    const step = currentStep;
    setCurrentStep(null);
    setConfirmedSteps((prev) => [...prev, step]);
    setChatMessages((prev) => [
      ...prev,
      { id: `user-ok-${Date.now()}`, role: "user", content: "OK ✓  次のステップへ進みます" },
      { id: `sys-gen-${Date.now()}`, role: "system", content: "次のステップを生成中..." },
    ]);
    setIsWaiting(true);
    try {
      await fetch(`${API_BASE}/build-plans/${planId}/steps/${step.step_seq}/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${idToken}` },
      });
      startPolling(planId);
    } catch (e) {
      setError(String(e));
      setIsWaiting(false);
    }
  }, [planId, currentStep, idToken, startPolling]);

  // --- Revise step ---
  const handleRevise = useCallback(
    async (instruction: string) => {
      if (!planId || !currentStep || !instruction.trim()) return;
      const msg = instruction.trim();
      setUserInput("");
      setChatMessages((prev) => [
        ...prev,
        { id: `user-rev-${Date.now()}`, role: "user", content: msg },
        { id: `sys-rev-${Date.now()}`, role: "system", content: "AI が修正案を生成中..." },
      ]);
      setIsWaiting(true);
      try {
        await fetch(
          `${API_BASE}/build-plans/${planId}/steps/${currentStep.step_seq}/revise`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json", Authorization: `Bearer ${idToken}` },
            body: JSON.stringify({ instruction: msg }),
          },
        );
        prevStepSeqRef.current = ""; // Allow re-fetch of same seq after revision
        startPolling(planId);
      } catch (e) {
        setError(String(e));
        setIsWaiting(false);
      }
    },
    [planId, currentStep, idToken, startPolling],
  );

  // --- Execute plan ---
  const handleExecute = useCallback(async () => {
    if (!planId) return;
    setIsExecuting(true);
    setExecElapsed(0);
    execTimerRef.current = setInterval(() => setExecElapsed((p) => p + 1), 1000);
    try {
      const r = await fetch(`${API_BASE}/build-plans/${planId}/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${idToken}` },
        body: JSON.stringify({ from_step: "0001" }),
      });
      if (!r.ok) {
        const d = await r.json();
        throw new Error(d.error ?? "実行に失敗");
      }
      const data = await r.json();
      if (data.gltf_url) onExecutionComplete(data.gltf_url, nodeId);
    } catch (e) {
      setError(String(e));
    } finally {
      if (execTimerRef.current) {
        clearInterval(execTimerRef.current);
        execTimerRef.current = null;
      }
      setIsExecuting(false);
    }
  }, [planId, nodeId, idToken, onExecutionComplete]);

  // All steps for 3D preview (confirmed + proposed current)
  const allPreviewSteps = useMemo(
    () => [...confirmedSteps, ...(currentStep ? [currentStep] : [])],
    [confirmedSteps, currentStep],
  );

  const isDone = pollState?.current_step_status === "done";
  const waitingLabel =
    pollState?.current_step_status === "revising"
      ? "修正案を生成中..."
      : isCreating || pollState?.plan_status === "creating"
      ? "図面を分析中..."
      : "次のステップを生成中...";

  // ---------------------------------------------------------------------------
  // Early render: creating plan
  if (isCreating && !planId) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6">
        <div className="h-10 w-10 animate-spin rounded-full border-4 border-indigo-200 border-t-indigo-600" />
        <p className="text-sm font-semibold text-gray-700">図面を分析中...</p>
        <p className="text-xs text-gray-400">AI が構築プランを生成しています（1〜2分かかる場合があります）</p>
      </div>
    );
  }

  if (!planId) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-4 p-6">
        <p className="text-sm text-gray-600">段階的構築モード</p>
        {error && (
          <>
            <p className="text-xs text-red-600" role="alert">
              {error}
            </p>
            <button
              type="button"
              onClick={() => {
                hasCreatedRef.current = false;
                handleCreatePlan();
              }}
              className="rounded bg-indigo-600 px-4 py-2 text-xs font-medium text-white hover:bg-indigo-700"
            >
              再試行
            </button>
          </>
        )}
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Main layout: 60 / 40 split
  // ---------------------------------------------------------------------------
  return (
    <div className="relative flex h-full w-full overflow-hidden">
      {/* Execution overlay */}
      {isExecuting && (
        <div className="absolute inset-0 z-50 flex flex-col items-center justify-center bg-gray-950/85 backdrop-blur-sm">
          <div className="h-10 w-10 animate-spin rounded-full border-4 border-green-800 border-t-green-400" />
          <p className="mt-4 text-sm font-semibold text-white">3D モデル生成中...</p>
          <p className="mt-1 font-mono text-xs text-green-400">経過: {execElapsed} 秒</p>
        </div>
      )}

      {/* ── Left 60%: 2D drawing (top) + 3D preview (bottom) ── */}
      <div className="flex h-full flex-col border-r" style={{ width: "60%" }}>
        {/* Top half: 2D drawing */}
        <div className="flex min-h-0 flex-1 flex-col border-b">
          <div className="flex h-6 shrink-0 items-center border-b bg-gray-50 px-3">
            <span className="text-[10px] font-semibold text-gray-500">2D 図面</span>
          </div>
          <div className="min-h-0 flex-1">
            <DrawingViewer url={drawingUrl} />
          </div>
        </div>
        {/* Bottom half: 3D preview */}
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="flex h-6 shrink-0 items-center border-b bg-gray-50 px-3">
            <span className="text-[10px] font-semibold text-gray-500">
              3D プレビュー
              {confirmedSteps.length > 0 && (
                <span className="ml-1 text-indigo-500">
                  （{confirmedSteps.length} ステップ確定済み）
                </span>
              )}
            </span>
          </div>
          <div className="min-h-0 flex-1">
            <StepPreview3D
              step={allPreviewSteps.at(-1) ?? null}
              allSteps={allPreviewSteps}
              planId={planId}
              idToken={idToken}
            />
          </div>
        </div>
      </div>

      {/* ── Right 40%: Tab panel ── */}
      <div className="flex h-full flex-col" style={{ width: "40%" }}>
        {/* Tab header */}
        <div className="flex shrink-0 items-center border-b bg-gray-50">
          <button
            type="button"
            onClick={() => setActiveTab("chat")}
            className={`px-4 py-2 text-xs font-semibold transition-colors ${
              activeTab === "chat"
                ? "border-b-2 border-indigo-600 text-indigo-700"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            チャット
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("step")}
            className={`px-4 py-2 text-xs font-semibold transition-colors ${
              activeTab === "step"
                ? "border-b-2 border-indigo-600 text-indigo-700"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            ステップ情報
          </button>
          {/* Execute button (visible when all steps are done) */}
          {isDone && (
            <div className="ml-auto flex items-center pr-2">
              <button
                type="button"
                onClick={handleExecute}
                disabled={isExecuting}
                className="rounded bg-green-600 px-3 py-1 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50"
              >
                3D 生成
              </button>
            </div>
          )}
        </div>

        {/* ── Chat tab ── */}
        {activeTab === "chat" && (
          <div className="flex min-h-0 flex-1 flex-col">
            {/* Message list */}
            <div className="flex-1 overflow-y-auto bg-gray-50 px-3 py-3">
              {chatMessages.map((msg) => (
                <ChatBubble key={msg.id} message={msg} />
              ))}

              {/* AI choices for current step */}
              {!isWaiting && currentStep && (currentStep.choices ?? []).length > 0 && (
                <div className="mb-3 ml-1 flex flex-wrap gap-1.5">
                  {(currentStep.choices ?? []).map((c) => (
                    <button
                      key={c.id}
                      type="button"
                      onClick={() => handleRevise(c.label)}
                      className="rounded-full border border-indigo-300 bg-white px-3 py-1 text-xs text-indigo-700 hover:bg-indigo-50"
                    >
                      {c.label}
                    </button>
                  ))}
                </div>
              )}

              {/* Waiting spinner */}
              {isWaiting && (
                <div className="mb-2 flex items-center gap-2 text-[10px] text-gray-400">
                  <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-gray-300 border-t-indigo-500" />
                  {waitingLabel}
                </div>
              )}

              <div ref={chatEndRef} />
            </div>

            {/* Input area */}
            <div className="shrink-0 border-t bg-white px-3 py-2">
              {error && (
                <p className="mb-1 text-[10px] text-red-600" role="alert">
                  {error}
                </p>
              )}

              {/* OK button when step is ready */}
              {!isWaiting && currentStep && (
                <button
                  type="button"
                  onClick={handleConfirm}
                  className="mb-2 w-full rounded-lg bg-indigo-600 py-2 text-xs font-semibold text-white hover:bg-indigo-700"
                >
                  ✓ OK — 次のステップへ
                </button>
              )}

              {/* Done state message */}
              {!isWaiting && isDone && (
                <p className="mb-2 text-center text-xs font-semibold text-green-600">
                  全ステップ確定 — 「3D 生成」ボタンで実行
                </p>
              )}

              {/* Free text input */}
              <div className="flex gap-1.5">
                <textarea
                  value={userInput}
                  onChange={(e) => setUserInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey && userInput.trim()) {
                      e.preventDefault();
                      handleRevise(userInput);
                    }
                  }}
                  placeholder={
                    currentStep
                      ? "指摘・修正内容を入力（Enter 送信 / Shift+Enter 改行）"
                      : isWaiting
                      ? "AI が処理中です..."
                      : "メッセージを入力"
                  }
                  disabled={isWaiting || !currentStep}
                  rows={2}
                  className="flex-1 resize-none rounded-lg border border-gray-300 px-2 py-1.5 text-xs focus:border-indigo-400 focus:ring-1 focus:ring-indigo-400 disabled:bg-gray-50 disabled:text-gray-400"
                />
                <button
                  type="button"
                  onClick={() => handleRevise(userInput)}
                  disabled={isWaiting || !userInput.trim() || !currentStep}
                  className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                >
                  送信
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ── Step info tab ── */}
        {activeTab === "step" && (
          <div className="flex-1 overflow-y-auto px-3 py-3">
            {currentStep ? (
              <div className="space-y-3">
                <div>
                  <div className="mb-1 flex items-center gap-2">
                    <span className="rounded bg-indigo-100 px-1.5 py-0.5 text-[10px] font-semibold text-indigo-700">
                      {STEP_TYPE_LABEL[currentStep.step_type] ?? currentStep.step_type}
                    </span>
                    <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-600">
                      提案中
                    </span>
                    {currentStep.confidence < 0.85 && (
                      <span className="rounded bg-red-50 px-1 text-[9px] text-red-600">
                        確度 {(currentStep.confidence * 100).toFixed(0)}%
                      </span>
                    )}
                  </div>
                  <h3 className="text-sm font-semibold text-gray-800">{currentStep.step_name}</h3>
                  {currentStep.ai_reasoning && (
                    <p className="mt-1 text-[11px] leading-relaxed text-gray-500">
                      {currentStep.ai_reasoning}
                    </p>
                  )}
                </div>

                {/* Parameters */}
                <fieldset className="rounded border p-2">
                  <legend className="px-1 text-[10px] font-semibold text-gray-500">パラメータ</legend>
                  <div className="space-y-1">
                    {Object.entries(currentStep.parameters).map(([key, val]) => {
                      const p = val as StepParameter;
                      return (
                        <div key={key} className="flex items-center gap-2 text-xs">
                          <span
                            className="w-28 truncate font-medium text-gray-700"
                            title={key}
                          >
                            {key}
                          </span>
                          <span className="flex-1 text-gray-800">{String(p.value)}</span>
                          <span className="text-[10px] text-gray-400">{p.unit}</span>
                          <span
                            className={`rounded px-1 text-[9px] ${
                              p.confidence >= 0.9
                                ? "bg-green-50 text-green-600"
                                : p.confidence >= 0.7
                                ? "bg-amber-50 text-amber-600"
                                : "bg-red-50 text-red-600"
                            }`}
                          >
                            {(p.confidence * 100).toFixed(0)}%
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </fieldset>

                {/* CadQuery code */}
                <details className="rounded border">
                  <summary className="cursor-pointer px-2 py-1 text-[10px] font-semibold text-gray-500 hover:bg-gray-50">
                    CadQuery コード
                  </summary>
                  <pre className="max-h-40 overflow-auto bg-gray-900 p-2 text-[10px] leading-relaxed text-green-300">
                    {currentStep.cq_code}
                  </pre>
                </details>
              </div>
            ) : (
              <p className="mb-4 text-[10px] text-gray-400">現在提案中のステップはありません</p>
            )}

            {/* Confirmed steps list */}
            {confirmedSteps.length > 0 && (
              <div className={currentStep ? "mt-4" : ""}>
                <p className="mb-2 text-[10px] font-semibold text-gray-500">
                  確定済みステップ（{confirmedSteps.length}）
                </p>
                <div className="space-y-1">
                  {confirmedSteps.map((s) => (
                    <div
                      key={s.step_seq}
                      className="flex items-center gap-2 rounded bg-green-50 px-2 py-1.5 text-xs"
                    >
                      <span className="font-semibold text-green-600">✓</span>
                      <span className="font-mono text-[10px] text-gray-400">{s.step_seq}</span>
                      <span className="flex-1 truncate text-gray-700">{s.step_name}</span>
                      <span className="text-[10px] text-gray-400">
                        {STEP_TYPE_LABEL[s.step_type] ?? s.step_type}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
