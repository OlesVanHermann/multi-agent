// ============================================
//  RecordingIndicator — TopBar badge
//  Shows recording state inline in the header
//  Click navigates to Greffier SaaS panel
// ============================================

import { useRecording } from "./RecordingContext";

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export default function RecordingIndicator({ onClick }: { onClick?: () => void }) {
  const { state } = useRecording();

  // Invisible when idle or done
  if (state.phase === "idle" || state.phase === "done") return null;

  let label = "";
  let color = "";
  let pulse = false;

  switch (state.phase) {
    case "requesting":
      label = formatElapsed(state.elapsed);
      color = "#EF4444";
      pulse = true;
      break;
    case "recording":
      label = formatElapsed(state.elapsed);
      color = "#EF4444";
      pulse = true;
      break;
    case "stopping":
      label = "Stopping";
      color = "#EAB308";
      break;
    case "processing":
      label = "Greffier";
      color = "#8B90A0";
      break;
    case "error":
      label = "Greffier error";
      color = "#EF4444";
      break;
  }

  return (
    <span
      onClick={onClick}
      style={{
        display: "flex",
        alignItems: "center",
        gap: "0.35rem",
        padding: "0.15rem 0.5rem",
        background: `${color}15`,
        border: `1px solid ${color}40`,
        borderRadius: "3px",
        fontSize: "0.65rem",
        color,
        cursor: onClick ? "pointer" : "default",
        fontFamily: "inherit",
      }}
      title="Greffier recording"
    >
      {/* Dot — pulsing red for recording, hourglass for processing/stopping */}
      {(state.phase === "recording" || state.phase === "requesting") ? (
        <span
          style={{
            display: "inline-block",
            width: 7,
            height: 7,
            borderRadius: "50%",
            background: color,
            boxShadow: pulse ? `0 0 6px ${color}` : undefined,
            animation: pulse ? "greffier-pulse-dot 1.2s ease-in-out infinite" : undefined,
          }}
        />
      ) : (state.phase === "processing" || state.phase === "stopping") ? (
        <span style={{ fontSize: "0.6rem" }}>&#9203;</span>
      ) : null}

      <span style={{ fontWeight: 600 }}>{label}</span>

      {/* Inline keyframe for pulse animation */}
      <style>{`
        @keyframes greffier-pulse-dot {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.5; transform: scale(0.85); }
        }
      `}</style>
    </span>
  );
}
