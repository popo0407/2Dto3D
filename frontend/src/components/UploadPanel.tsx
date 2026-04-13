import { useState, useCallback } from "react";
import { API_BASE } from "../config";

interface UploadPanelProps {
  idToken: string;
  onSessionCreated: (sessionId: string) => void;
  onProcessingComplete: (nodeId: string, gltfUrl: string, reasoning?: string) => void;
  onProcessingStart: (
    sessionId: string,
    onComplete: (nodeId: string, url: string, reasoning?: string) => void,
    onError: (msg: string) => void,
  ) => Promise<void>;
  onBuildPlanStart: (sessionId: string) => void;
  processingStep: string;
  processingProgress: number;
}

type ProcessingMode = "auto" | "buildplan";

type UploadStatus = "idle" | "uploading" | "processing" | "error";

const ALLOWED_EXTENSIONS = [".dxf", ".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif"];
const MAX_FILES = 5;

const PIPELINE_STEPS = [
  { key: "PARSING",      label: "ファイル解析中",    pct: 20 },
  { key: "AI_ANALYZING", label: "AI図面解釈中", pct: 55 },
  { key: "BUILDING",     label: "3Dモデル構築中",   pct: 70 },
  { key: "OPTIMIZING",   label: "形状最適化中",   pct: 90 },
  { key: "VALIDATING",   label: "品質検証中",    pct: 95 },
];

export function UploadPanel({ idToken, onSessionCreated, onProcessingComplete, onProcessingStart, onBuildPlanStart, processingStep, processingProgress }: UploadPanelProps) {
  const authHeader = { Authorization: `Bearer ${idToken}` };

  const [status, setStatus] = useState<UploadStatus>("idle");
  const [projectName, setProjectName] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [fileDescriptions, setFileDescriptions] = useState<Record<string, string>>({});
  const [drawingNotes, setDrawingNotes] = useState("");
  const [error, setError] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [mode, setMode] = useState<ProcessingMode>("auto");

  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(e.target.files ?? []);
    const combined = [...files, ...selected].slice(0, MAX_FILES);
    const invalid = combined.filter(
      (f) => !ALLOWED_EXTENSIONS.some((ext) => f.name.toLowerCase().endsWith(ext)),
    );
    if (invalid.length > 0) {
      setError(`非対応ファイル: ${invalid.map((f) => f.name).join(", ")}`);
      return;
    }
    if (files.length + selected.length > MAX_FILES) {
      setError(`ファイルは最大 ${MAX_FILES} 枚まで選択できます（現在 ${files.length} 枚）`);
    } else {
      setError("");
    }
    setFiles(combined);
    // Reset file input so the same file can be re-added after removal
    e.target.value = "";
  }, [files]);

  const removeFile = useCallback((index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
    setFileDescriptions((prev) => {
      const next = { ...prev };
      delete next[index];
      // Shift keys above the removed index
      const shifted: Record<string, string> = {};
      Object.entries(next).forEach(([k, v]) => {
        const n = Number(k);
        shifted[n > index ? String(n - 1) : k] = v;
      });
      return shifted;
    });
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (files.length === 0) {
      setError("ファイルを選択してください");
      return;
    }

    setStatus("uploading");
    setError("");

    try {
      // 1. Create session
      const sessionRes = await fetch(`${API_BASE}/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeader },
        body: JSON.stringify({ project_name: projectName || "Untitled", drawing_notes: drawingNotes }),
      });
      if (!sessionRes.ok) throw new Error("セッション作成に失敗しました");

      const session = (await sessionRes.json()) as { session_id: string };
      setSessionId(session.session_id);
      onSessionCreated(session.session_id);

      // 2. Upload each file
      for (let i = 0; i < files.length; i++) {
        const file = files[i]!;
        const description = fileDescriptions[i] ?? "";
        const uploadRes = await fetch(
          `${API_BASE}/sessions/${session.session_id}/upload`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json", ...authHeader },
            body: JSON.stringify({
              filename: file.name,
              content_type: file.type || "application/octet-stream",
              description,
            }),
          },
        );
        if (!uploadRes.ok) throw new Error(`${file.name} のアップロードURLの取得に失敗しました`);

        const { upload_url } = (await uploadRes.json()) as { upload_url: string };

        const putRes = await fetch(upload_url, {
          method: "PUT",
          body: file,
          headers: { "Content-Type": file.type || "application/octet-stream" },
        });
        if (!putRes.ok) throw new Error(`${file.name} のアップロードに失敗しました`);
      }

      if (mode === "buildplan") {
        // BuildPlan モード: パイプラインを起動せずに BuildPlan 画面へ遷移
        // drawing_notes はセッション作成時に既に保存されている
        setStatus("idle");
        onBuildPlanStart(session.session_id);
        return;
      }

      // 3. WebSocket 接続を先に確立してからパイプラインを起動（競合状態防止）
      setStatus("processing");
      await onProcessingStart(
        session.session_id,
        (nid, url, reasoning) => {
          setStatus("idle");
          onProcessingComplete(nid, url, reasoning);
        },
        (msg) => {
          setError(msg);
          setStatus("error");
        },
      );

      // 4. WebSocket 接続確立後に処理を開始
      const processRes = await fetch(
        `${API_BASE}/sessions/${session.session_id}/process`,
        { method: "POST", headers: authHeader },
      );
      if (!processRes.ok) throw new Error("処理の開始に失敗しました");
    } catch (err) {
      setError(err instanceof Error ? err.message : "エラーが発生しました");
      setStatus("error");
    }
  };

  return (
    <div className="flex flex-1 items-center justify-center p-8">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-lg space-y-6 rounded-xl bg-white p-8 shadow-lg"
        aria-label="図面アップロードフォーム"
      >
        <h2 className="text-xl font-semibold text-gray-900">
          2D図面をアップロード
        </h2>

        {/* Mode selector */}
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium text-gray-700">生成モード</legend>
          <label
            className={`flex cursor-pointer items-start gap-3 rounded-lg border-2 p-3 transition-colors ${
              mode === "auto" ? "border-blue-500 bg-blue-50" : "border-gray-200 hover:border-gray-300"
            }`}
          >
            <input
              type="radio"
              name="mode"
              value="auto"
              checked={mode === "auto"}
              onChange={() => setMode("auto")}
              className="mt-0.5 accent-blue-600"
              disabled={status === "uploading" || status === "processing"}
            />
            <div>
              <p className="text-sm font-semibold text-gray-800">自動生成</p>
              <p className="text-xs text-gray-500">AIが図面を解析し3Dモデルを自動で一括生成します</p>
            </div>
          </label>
          <label
            className={`flex cursor-pointer items-start gap-3 rounded-lg border-2 p-3 transition-colors ${
              mode === "buildplan" ? "border-indigo-500 bg-indigo-50" : "border-gray-200 hover:border-gray-300"
            }`}
          >
            <input
              type="radio"
              name="mode"
              value="buildplan"
              checked={mode === "buildplan"}
              onChange={() => setMode("buildplan")}
              className="mt-0.5 accent-indigo-600"
              disabled={status === "uploading" || status === "processing"}
            />
            <div>
              <p className="text-sm font-semibold text-gray-800">段階的構築</p>
              <p className="text-xs text-gray-500">AIが構築手順（BuildPlan）を生成し、各ステップをパラメータ編集・チャットで修正しながら構築します</p>
            </div>
          </label>
        </fieldset>

        <div>
          <label htmlFor="project-name" className="mb-1 block text-sm font-medium text-gray-700">
            プロジェクト名
          </label>
          <input
            id="project-name"
            type="text"
            value={projectName}
            onChange={(e) => setProjectName(e.target.value)}
            placeholder="例: 機械部品A"
            className="w-full rounded-lg border px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
          />
        </div>

        <div>
          <label htmlFor="file-input" className="mb-1 block text-sm font-medium text-gray-700">
            図面ファイル <span className="text-xs text-gray-400">（最大{MAX_FILES}枚）</span>
          </label>
          <input
            id="file-input"
            type="file"
            multiple
            accept={ALLOWED_EXTENSIONS.join(",")}
            onChange={handleFileChange}
            disabled={files.length >= MAX_FILES || status === "uploading" || status === "processing"}
            className="w-full rounded-lg border px-3 py-2 text-sm file:mr-3 file:rounded file:border-0 file:bg-blue-50 file:px-3 file:py-1 file:text-sm file:font-medium file:text-blue-700 disabled:opacity-50"
            aria-describedby="file-help"
          />
          <p id="file-help" className="mt-1 text-xs text-gray-500">
            対応形式: DXF, PDF, PNG, JPG, TIFF (最大50MB / 1ファイル) ・ {files.length}/{MAX_FILES} 枚選択中
          </p>
        </div>

        {files.length > 0 && (
          <ul className="space-y-2" aria-label="選択ファイル一覧">
            {files.map((file, index) => (
              <li
                key={`${file.name}-${index}`}
                className="rounded-lg border border-gray-200 bg-gray-50 p-3"
              >
                <div className="flex items-center gap-2">
                  <span className="text-gray-400" aria-hidden="true">📄</span>
                  <span className="flex-1 truncate text-sm text-gray-700">{file.name}</span>
                  <span className="text-xs text-gray-400">{(file.size / 1024).toFixed(0)} KB</span>
                  <button
                    type="button"
                    onClick={() => removeFile(index)}
                    className="ml-1 rounded p-0.5 text-gray-400 hover:bg-gray-200 hover:text-red-500"
                    aria-label={`${file.name} を削除`}
                    disabled={status === "uploading" || status === "processing"}
                  >
                    ✕
                  </button>
                </div>
                <input
                  type="text"
                  value={fileDescriptions[index] ?? ""}
                  onChange={(e) =>
                    setFileDescriptions((prev) => ({ ...prev, [index]: e.target.value }))
                  }
                  placeholder="この図面の説明（例: 正面図、側面図、寸法補足 など）"
                  className="mt-2 w-full rounded border px-2 py-1 text-xs text-gray-600 placeholder-gray-400 focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
                  aria-label={`${file.name} の説明`}
                  disabled={status === "uploading" || status === "processing"}
                />
              </li>
            ))}
          </ul>
        )}

        <div>
          <label htmlFor="drawing-notes" className="mb-1 block text-sm font-medium text-gray-700">
            図面情報・補足メモ <span className="text-xs text-gray-400">（任意）</span>
          </label>
          <textarea
            id="drawing-notes"
            value={drawingNotes}
            onChange={(e) => setDrawingNotes(e.target.value)}
            placeholder="材質、表面処理、特殊な寸法・公差、注意事項など、AIへ伝えたい情報を自由に記入してください"
            rows={3}
            className="w-full rounded-lg border px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
            aria-describedby="notes-help"
            disabled={status === "uploading" || status === "processing"}
          />
          <p id="notes-help" className="mt-1 text-xs text-gray-500">
            記入した情報はAIの解析精度向上に使われます
          </p>
        </div>

        {error && (
          <p className="rounded-lg bg-red-50 px-4 py-2 text-sm text-red-700" role="alert">
            {error}
          </p>
        )}

        {status === "processing" && sessionId && (
          <div className="space-y-3">
            <div className="flex items-center justify-between text-sm">
              <span className="font-medium text-blue-700">
                {PIPELINE_STEPS.find((s) => s.key === processingStep)?.label
                  ?? (processingStep === "" ? "処理開始中..." : "処理中...")}
              </span>
              <span className="tabular-nums text-blue-600">{processingProgress}%</span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-blue-100" role="progressbar" aria-valuenow={processingProgress} aria-valuemin={0} aria-valuemax={100}>
              <div
                className="h-full rounded-full bg-blue-500 transition-all duration-700 ease-out"
                style={{ width: `${processingProgress}%` }}
              />
            </div>
            <ol className="flex justify-between" aria-label="パイプラインステップ">
              {PIPELINE_STEPS.map((step) => {
                const done = processingProgress >= step.pct;
                const active = processingStep === step.key;
                return (
                  <li key={step.key} className="flex flex-col items-center gap-0.5">
                    <span
                      className={`flex h-5 w-5 items-center justify-center rounded-full text-xs font-bold transition-colors duration-500 ${
                        done
                          ? "bg-blue-500 text-white"
                          : active
                            ? "ring-2 ring-blue-400 bg-blue-100 text-blue-600"
                            : "bg-gray-200 text-gray-400"
                      }`}
                      aria-hidden="true"
                    >
                      {done ? "✓" : PIPELINE_STEPS.indexOf(step) + 1}
                    </span>
                    <span className={`text-[10px] leading-tight text-center ${done || active ? "text-blue-600" : "text-gray-400"}`}>
                      {step.label.replace("中", "")}
                    </span>
                  </li>
                );
              })}
            </ol>
          </div>
        )}

        <button
          type="submit"
          disabled={status === "uploading" || status === "processing"}
          className={`w-full rounded-lg py-2.5 text-sm font-medium text-white disabled:bg-gray-400 disabled:cursor-not-allowed ${
            mode === "buildplan" ? "bg-indigo-600 hover:bg-indigo-700" : "bg-blue-600 hover:bg-blue-700"
          }`}
        >
          {status === "uploading"
            ? "アップロード中..."
            : status === "processing"
              ? "処理中..."
              : mode === "buildplan"
                ? "段階的構築を開始"
                : "3Dモデルを自動生成"}
        </button>
      </form>
    </div>
  );
}
