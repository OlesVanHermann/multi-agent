// ============================================
//  Recording Types — Greffier recording state
// ============================================

export type RecordingPhase = "idle" | "requesting" | "recording" | "stopping" | "processing" | "done" | "error";

export interface RecordingResult {
  fileId: string;
  transcript: string | null;
  summary: string | null;
  utterances: { start: number; end: number; text: string }[];
  wavDriveId: string | null;
  summaryDriveId: string | null;
  transcriptDriveId: string | null;
  fileMeta: { duration?: number; sampleRate?: number; fileType?: string } | null;
}

export interface RecordingState {
  phase: RecordingPhase;
  elapsed: number;           // seconds since recording started
  bytesRecorded: number;     // bytes received by backend
  volume: number;            // 0-255 RMS level
  fileId: string | null;
  error: string | null;
  warning: string | null;
  wavBlobUrl: string | null; // local WAV download (generated on stop)
  taskId: string | null;     // unified task ID for processing tracking
  // Processing progress (from /api/greffier/status poll)
  status: string;            // pending | processing | completed | error
  progressMsg: string;
  stepInfo: { step: number; total: number; label: string } | null;
  result: RecordingResult | null;
}
