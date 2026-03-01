// ============================================
//  GreffierPanel — SaaS panel for Greffier
//  RecordTab reads from useRecording() singleton
//  Upload uses TransferQueue
// ============================================

import { useState, useRef } from "react";
import { useRecording } from "./RecordingContext";
import { useTransfers } from "../transfers/TransferContext";

// ---- Helpers ----

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}

// ---- Volume bar ----

function VolumeBar({ volume }: { volume: number }) {
  const pct = Math.min(100, (volume / 255) * 100);
  return (
    <div style={{ width: "100%", height: 6, background: "rgba(255,255,255,0.08)", borderRadius: 3, overflow: "hidden" }}>
      <div
        style={{
          height: "100%",
          width: `${pct}%`,
          background: pct > 70 ? "#EF4444" : pct > 30 ? "#22B47A" : "#4A7AFF",
          borderRadius: 3,
          transition: "width 0.08s",
        }}
      />
    </div>
  );
}

// ---- Use-case options ----

const USE_CASES = [
  { value: "meeting", label: "Meeting" },
  { value: "interview", label: "Interview" },
  { value: "lecture", label: "Lecture" },
  { value: "dictation", label: "Dictation" },
  { value: "other", label: "Other" },
];

const LANGUAGES = [
  { value: "fr", label: "Francais" },
  { value: "en", label: "English" },
  { value: "de", label: "Deutsch" },
  { value: "es", label: "Espanol" },
  { value: "it", label: "Italiano" },
  { value: "pt", label: "Portugues" },
  { value: "nl", label: "Nederlands" },
  { value: "auto", label: "Auto-detect" },
];

const GREFFIER_COLOR = "#E8457A";

// ---- Styles ----

const styles = {
  container: { flex: 1, overflow: "auto", padding: "1.5rem" } as const,
  inner: { maxWidth: "42rem", margin: "0 auto" } as const,
  section: { marginBottom: "1.5rem" } as const,
  label: { display: "block", fontSize: "0.875rem", fontWeight: 500, color: "#888", marginBottom: "0.5rem" } as const,
  chipRow: { display: "flex", gap: "0.5rem", flexWrap: "wrap" as const },
  chipActive: {
    padding: "0.375rem 0.75rem", borderRadius: 8, fontSize: "0.875rem", fontWeight: 500,
    border: `1px solid ${GREFFIER_COLOR}40`, background: `${GREFFIER_COLOR}18`, color: GREFFIER_COLOR,
    cursor: "pointer",
  } as const,
  chipInactive: {
    padding: "0.375rem 0.75rem", borderRadius: 8, fontSize: "0.875rem", fontWeight: 500,
    border: "1px solid rgba(255,255,255,0.1)", background: "transparent", color: "#8B90A0",
    cursor: "pointer",
  } as const,
  select: {
    padding: "0.5rem 0.75rem", borderRadius: 8, fontSize: "0.875rem",
    border: "1px solid rgba(255,255,255,0.1)", background: "var(--bg-panel, #0f0f23)", color: "#ccc",
  } as const,
  btnPrimary: {
    flex: 1, padding: "0.75rem 1rem", borderRadius: 12, fontSize: "0.875rem", fontWeight: 600,
    background: "#EF4444", color: "#fff", border: "none", cursor: "pointer",
  } as const,
  btnSecondary: {
    padding: "0.75rem 1rem", borderRadius: 12, fontSize: "0.875rem", fontWeight: 500,
    border: "1px solid rgba(255,255,255,0.15)", background: "transparent", color: "#8B90A0", cursor: "pointer",
  } as const,
  btnSmall: {
    padding: "0.25rem 0.5rem", borderRadius: 4, fontSize: "0.75rem",
    border: "1px solid rgba(255,255,255,0.1)", background: "transparent", color: "#8B90A0", cursor: "pointer",
  } as const,
  dropZone: (active: boolean) => ({
    borderRadius: 12, border: `2px dashed ${active ? GREFFIER_COLOR : "rgba(255,255,255,0.1)"}`,
    padding: "2rem", textAlign: "center" as const, fontSize: "0.875rem", color: "#8B90A0",
    background: active ? `${GREFFIER_COLOR}10` : "transparent",
    transition: "border-color 0.2s, background 0.2s",
  }),
  errorBox: {
    padding: "0.75rem 1rem", borderRadius: 8, fontSize: "0.875rem",
    border: "1px solid #EF444440", background: "#EF444410", color: "#EF4444",
    marginBottom: "1rem",
  } as const,
  bigTimer: { fontSize: "3rem", fontFamily: "inherit", fontWeight: 700, color: "#EF4444", textAlign: "center" as const } as const,
  subText: { fontSize: "0.875rem", color: "#888", textAlign: "center" as const, marginTop: "0.5rem" } as const,
  warningText: { fontSize: "0.75rem", color: "#EAB308", textAlign: "center" as const, marginTop: "0.25rem" } as const,
  resultCard: {
    padding: "1rem", borderRadius: 8,
    border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.02)",
    fontSize: "0.875rem", lineHeight: 1.6,
  } as const,
  resultTitle: { fontSize: "0.875rem", fontWeight: 600, color: GREFFIER_COLOR } as const,
  progressBar: { width: "100%", height: 6, background: "rgba(255,255,255,0.08)", borderRadius: 3, overflow: "hidden" } as const,
  downloadLink: {
    display: "inline-block", padding: "0.5rem 1rem", borderRadius: 8, fontSize: "0.875rem", fontWeight: 500,
    border: "1px solid rgba(255,255,255,0.15)", color: "#8B90A0", textDecoration: "none", cursor: "pointer",
    background: "transparent",
  } as const,
  newRecBtn: {
    padding: "0.5rem 1rem", borderRadius: 12, fontSize: "0.875rem", fontWeight: 500,
    background: `${GREFFIER_COLOR}18`, color: GREFFIER_COLOR, border: `1px solid ${GREFFIER_COLOR}40`,
    cursor: "pointer",
  } as const,
  meta: { fontSize: "0.75rem", color: "#888" } as const,
};

// ---- RecordTab ----

function RecordTab() {
  const { state, startRecording, stopRecording, cancelRecording, reset } = useRecording();
  const { enqueueUpload } = useTransfers();
  const [useCase, setUseCase] = useState("meeting");
  const [lang, setLang] = useState("fr");
  const [copiedSummary, setCopiedSummary] = useState(false);
  const [copiedTranscript, setCopiedTranscript] = useState(false);

  // Upload state
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const showSelector = state.phase === "idle" || state.phase === "error" || state.phase === "done";

  const handleUpload = (file: File) => {
    enqueueUpload({
      file,
      url: `/api/greffier/upload?use_case=${encodeURIComponent(useCase)}&lang=${encodeURIComponent(lang)}`,
      serviceId: "greffier",
      serviceLabel: "Greffier",
      formDataFields: { use_case: useCase, lang },
    });
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const files = e.dataTransfer.files;
    if (files.length > 0) handleUpload(files[0]);
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) handleUpload(files[0]);
    e.target.value = "";
  };

  const copyToClipboard = (text: string, setter: (v: boolean) => void) => {
    navigator.clipboard.writeText(text).then(() => {
      setter(true);
      setTimeout(() => setter(false), 2000);
    });
  };

  return (
    <div style={styles.container}>
      <div style={styles.inner}>

        {/* ---- Config + Actions (idle / error / done) ---- */}
        {showSelector && (
          <>
            {/* Use-case selector */}
            <div style={styles.section}>
              <span style={styles.label}>Use case</span>
              <div style={styles.chipRow}>
                {USE_CASES.map((uc) => (
                  <button
                    key={uc.value}
                    onClick={() => setUseCase(uc.value)}
                    style={useCase === uc.value ? styles.chipActive : styles.chipInactive}
                  >
                    {uc.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Language selector */}
            <div style={styles.section}>
              <span style={styles.label}>Language</span>
              <select value={lang} onChange={(e) => setLang(e.target.value)} style={styles.select}>
                {LANGUAGES.map((l) => (
                  <option key={l.value} value={l.value}>{l.label}</option>
                ))}
              </select>
            </div>

            {/* Error display */}
            {state.phase === "error" && state.error && (
              <div style={styles.errorBox}>{state.error}</div>
            )}

            {/* Record + Upload buttons */}
            <div style={{ display: "flex", gap: "0.75rem", marginBottom: "1.5rem" }}>
              <button onClick={() => startRecording(useCase, lang)} style={styles.btnPrimary}>
                Start Recording
              </button>
              <button onClick={() => inputRef.current?.click()} style={styles.btnSecondary}>
                Upload File
              </button>
              <input
                ref={inputRef}
                type="file"
                accept="audio/*,video/*"
                onChange={handleFileSelect}
                style={{ display: "none" }}
              />
            </div>

            {/* Drop zone */}
            <div
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              style={styles.dropZone(dragOver)}
            >
              Drop audio/video file here
            </div>
          </>
        )}

        {/* ---- Recording in progress ---- */}
        {(state.phase === "recording" || state.phase === "requesting") && (
          <div>
            <div style={{ textAlign: "center", marginBottom: "1rem" }}>
              <div style={styles.bigTimer}>{formatElapsed(state.elapsed)}</div>
              <div style={styles.subText}>{formatBytes(state.bytesRecorded)} sent</div>
              {state.warning && <div style={styles.warningText}>{state.warning}</div>}
            </div>

            <div style={{ marginBottom: "1rem" }}>
              <VolumeBar volume={state.volume} />
            </div>

            <div style={{ display: "flex", gap: "0.75rem", justifyContent: "center" }}>
              <button onClick={stopRecording} style={{ ...styles.btnPrimary, flex: "none", padding: "0.75rem 1.5rem" }}>
                Stop
              </button>
              <button onClick={cancelRecording} style={styles.btnSecondary}>
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* ---- Stopping ---- */}
        {state.phase === "stopping" && (
          <div style={{ textAlign: "center", padding: "2rem 0" }}>
            <div style={{ fontSize: "1.125rem", fontWeight: 500, color: "#EAB308" }}>Stopping...</div>
            <div style={styles.subText}>Encoding WAV and finalizing</div>
          </div>
        )}

        {/* ---- Processing ---- */}
        {state.phase === "processing" && (
          <div>
            <div style={{ textAlign: "center", padding: "1rem 0", marginBottom: "1rem" }}>
              <div style={{ fontSize: "1.125rem", fontWeight: 500, color: "#888" }}>Processing...</div>
              <div style={styles.subText}>{state.progressMsg}</div>
            </div>

            {state.stepInfo && (
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.75rem", color: "#888", marginBottom: "0.5rem" }}>
                  <span>{state.stepInfo.label}</span>
                  <span>{state.stepInfo.step}/{state.stepInfo.total}</span>
                </div>
                <div style={styles.progressBar}>
                  <div
                    style={{
                      height: "100%",
                      width: `${(state.stepInfo.step / state.stepInfo.total) * 100}%`,
                      background: "#8B90A0",
                      borderRadius: 3,
                      transition: "width 0.3s",
                    }}
                  />
                </div>
              </div>
            )}
          </div>
        )}

        {/* ---- Done — Results ---- */}
        {state.phase === "done" && state.result && (
          <div>
            {/* Summary */}
            {state.result.summary && (
              <div style={styles.section}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "0.5rem" }}>
                  <span style={styles.resultTitle}>Summary</span>
                  <button onClick={() => copyToClipboard(state.result!.summary!, setCopiedSummary)} style={styles.btnSmall}>
                    {copiedSummary ? "Copied!" : "Copy"}
                  </button>
                </div>
                <div style={styles.resultCard}>{state.result.summary}</div>
              </div>
            )}

            {/* Transcript */}
            {state.result.transcript && (
              <div style={styles.section}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "0.5rem" }}>
                  <span style={styles.resultTitle}>Transcript</span>
                  <button onClick={() => copyToClipboard(state.result!.transcript!, setCopiedTranscript)} style={styles.btnSmall}>
                    {copiedTranscript ? "Copied!" : "Copy"}
                  </button>
                </div>
                <div style={{ ...styles.resultCard, maxHeight: "16rem", overflow: "auto", fontSize: "0.8rem" }}>
                  {state.result.transcript}
                </div>
              </div>
            )}

            {/* Downloads */}
            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginBottom: "1.5rem" }}>
              {state.wavBlobUrl && (
                <a
                  href={state.wavBlobUrl}
                  download={`greffier-${state.result.fileId}.wav`}
                  style={styles.downloadLink}
                >
                  Download WAV
                </a>
              )}
              {state.result.transcript && (
                <button
                  onClick={() => {
                    const blob = new Blob([state.result!.transcript!], { type: "text/plain" });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement("a");
                    a.href = url;
                    a.download = `greffier-${state.result!.fileId}.txt`;
                    a.click();
                    URL.revokeObjectURL(url);
                  }}
                  style={styles.downloadLink}
                >
                  Download TXT
                </button>
              )}
              {state.result.summary && (
                <button
                  onClick={() => {
                    const blob = new Blob(
                      [`# Summary\n\n${state.result!.summary}\n\n# Transcript\n\n${state.result!.transcript || ""}`],
                      { type: "text/markdown" },
                    );
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement("a");
                    a.href = url;
                    a.download = `greffier-${state.result!.fileId}.md`;
                    a.click();
                    URL.revokeObjectURL(url);
                  }}
                  style={styles.downloadLink}
                >
                  Download MD
                </button>
              )}
            </div>

            {/* File metadata */}
            {state.result.fileMeta && (
              <div style={{ ...styles.meta, marginBottom: "1.5rem" }}>
                {state.result.fileMeta.duration && (
                  <span style={{ marginRight: "1rem" }}>Duration: {formatElapsed(Math.round(state.result.fileMeta.duration))}</span>
                )}
                {state.result.fileMeta.sampleRate && (
                  <span style={{ marginRight: "1rem" }}>Sample rate: {state.result.fileMeta.sampleRate} Hz</span>
                )}
                {state.result.fileMeta.fileType && (
                  <span>Format: {state.result.fileMeta.fileType}</span>
                )}
              </div>
            )}

            {/* New recording */}
            <button onClick={reset} style={styles.newRecBtn}>
              New Recording
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ---- GreffierPanel ----

export default function GreffierPanel({ activeTab, tabs }: { activeTab: number; tabs: string[] }) {
  const tabName = tabs[activeTab] ?? tabs[0];

  if (tabName === "Record") {
    return <RecordTab />;
  }

  // Placeholder for other tabs (History, Settings, MCP handled by App.tsx)
  return (
    <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ textAlign: "center" }}>
        <div style={{ fontSize: "3.75rem", marginBottom: "1rem" }}>&#128196;</div>
        <div style={{ fontSize: "1.25rem", fontWeight: 600, color: "var(--text-primary, #e0e0e0)" }}>
          Greffier — {tabName}
        </div>
        <div style={{ fontSize: "0.875rem", color: "#888", fontFamily: "inherit", marginTop: "0.5rem" }}>
          Coming soon
        </div>
      </div>
    </div>
  );
}
