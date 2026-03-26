import { useState, useCallback } from "react";
import { API_BASE } from "../config";

interface UploadPanelProps {
  idToken: string;
  onSessionCreated: (sessionId: string) => void;
  onProcessingComplete: (nodeId: string, gltfUrl: string) => void;
  onProcessingStart: (
    sessionId: string,
    onComplete: (nodeId: string, url: string) => void,
    onError: (msg: string) => void,
  ) => Promise<void>;
  processingStep: string;
  processingProgress: number;
}

type UploadStatus = "idle" | "uploading" | "processing" | "error";

const ALLOWED_EXTENSIONS = [".dxf", ".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif"];

const PIPELINE_STEPS = [
  { key: "PARSING",      label: "ファイル解析中",    pct: 20 },
  { key: "AI_ANALYZING", label: "AI図面解釈中", pct: 55 },
  { key: "BUILDING",     label: "3Dモデル構築中",   pct: 70 },
  { key: "OPTIMIZING",   label: "形状最適化中",   pct: 90 },
  { key: "VALIDATING",   label: "品質検証中",    pct: 95 },
];

export function UploadPanel({ idToken, onSessionCreated, onProcessingComplete, onProcessingStart, processingStep, processingProgress }: UploadPanelProps) {
  const authHeader = { Authorization: `Bearer ${idToken}` };

  const [status, setStatus] = useState<UploadStatus>("idle");
  const [projectName, setProjectName] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState("");
  const [sessionId, setSessionId] = useState("");

  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(e.target.files ?? []);
    const invalid = selected.filter(
      (f) => !ALLOWED_EXTENSIONS.some((ext) => f.name.toLowerCase().endsWith(ext)),
    );
    if (invalid.length > 0) {
      setError(`非対応ファイル: ${invalid.map((f) => f.name).join(", ")}`);
      return;
    }
    setFiles(selected);
    setError("");
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
        body: JSON.stringify({ project_name: projectName || "Untitled" }),
      });
      if (!sessionRes.ok) throw new Error("セッション作成に失敗しました");

      const session = (await sessionRes.json()) as { session_id: string };
      setSessionId(session.session_id);
      onSessionCreated(session.session_id);

      // 2. Upload each file
      for (const file of files) {
        const uploadRes = await fetch(
          `${API_BASE}/sessions/${session.session_id}/upload`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json", ...authHeader },
            body: JSON.stringify({
              filename: file.name,
              content_type: file.type || "application/octet-stream",
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

      // 3. WebSocket 接続を先に確立してからパイプラインを起動（競合状態防止）
      setStatus("processing");
      await onProcessingStart(
        session.session_id,
        (nid, url) => {
          setStatus("idle");
          onProcessingComplete(nid, url);
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
            図面ファイル
          </label>
          <input
            id="file-input"
            type="file"
            multiple
            accept={ALLOWED_EXTENSIONS.join(",")}
            onChange={handleFileChange}
            className="w-full rounded-lg border px-3 py-2 text-sm file:mr-3 file:rounded file:border-0 file:bg-blue-50 file:px-3 file:py-1 file:text-sm file:font-medium file:text-blue-700"
            aria-describedby="file-help"
          />
          <p id="file-help" className="mt-1 text-xs text-gray-500">
            対応形式: DXF, PDF, PNG, JPG, TIFF (最大50MB)
          </p>
        </div>

        {files.length > 0 && (
          <ul className="space-y-1" aria-label="選択ファイル一覧">
            {files.map((file) => (
              <li
                key={file.name}
                className="flex items-center gap-2 rounded bg-gray-50 px-3 py-1.5 text-sm text-gray-700"
              >
                <span className="text-gray-400" aria-hidden="true">📄</span>
                {file.name}
                <span className="ml-auto text-xs text-gray-400">
                  {(file.size / 1024).toFixed(0)} KB
                </span>
              </li>
            ))}
          </ul>
        )}

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
          className="w-full rounded-lg bg-blue-600 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed"
        >
          {status === "uploading"
            ? "アップロード中..."
            : status === "processing"
              ? "処理中..."
              : "3Dモデルを生成"}
        </button>
      </form>
    </div>
  );
}
