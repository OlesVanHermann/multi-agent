import { useState, useEffect, useRef } from "react";
import { cn, formatBytes } from "../lib/utils";
import type { DriveEntry, DriveFile } from "./drive-types";
import { apiFetch, verboseCheck } from '../lib/apiFetch';
import { useBlobUrl } from './useBlobUrl';
import { useVideoResume, useTranscript, usePlaybackSpeed, useVideoSkip } from './useVideoPlayer';

// =======================================
//  DRIVE PREVIEW — Agent 305 (Cycle 3)
//  Inline preview for images, text, PDF, code
// =======================================

const DRIVE_COLOR = "var(--color-drive)";
const API_BASE = import.meta.env.VITE_API_URL ?? "/api";

/** Apply alpha to --color-drive via color-mix (CSS variable-safe) */
function driveAlpha(a: number): string {
  return `color-mix(in oklch, var(--color-drive) ${Math.round(a * 100)}%, transparent)`;
}

interface DrivePreviewProps {
  item: DriveEntry;
  onClose: () => void;
  onDownload: (file: DriveFile) => void;
}

type PreviewKind = "image" | "pdf" | "text" | "code" | "video" | "audio" | "unsupported";

function detectPreviewKind(item: DriveEntry): PreviewKind {
  if (item.kind === "folder") return "unsupported";
  const ext = (item as DriveFile).extension?.toLowerCase() ?? "";
  const mime = item.mimeType?.toLowerCase() ?? "";

  if (mime.startsWith("image/") || /^(png|jpg|jpeg|gif|webp|svg|bmp|ico)$/.test(ext)) return "image";
  if (mime === "application/pdf" || ext === "pdf") return "pdf";
  if (mime.startsWith("video/") || /^(mp4|webm|ogg|mov)$/.test(ext)) return "video";
  if (mime.startsWith("audio/") || /^(mp3|wav|ogg|flac|aac)$/.test(ext)) return "audio";
  if (/^(ts|tsx|js|jsx|py|rs|go|java|c|cpp|h|hpp|rb|php|sh|bash|zsh|yaml|yml|toml|json|xml|html|css|scss|sql|md|txt|log|csv|env|conf|ini|cfg)$/.test(ext)) return "code";
  if (mime.startsWith("text/")) return "text";

  return "unsupported";
}

function PreviewImage({ url, name }: { url: string; name: string }) {
  const blobUrl = useBlobUrl(url);
  if (!blobUrl) return <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">Loading...</div>;
  return (
    <div className="flex-1 flex items-center justify-center p-4 overflow-hidden">
      <img
        src={blobUrl}
        alt={name}
        className="max-w-full max-h-full object-contain rounded-lg"
        draggable={false}
      />
    </div>
  );
}

function PreviewPdf({ url }: { url: string }) {
  const blobUrl = useBlobUrl(url);
  return (
    <div className="flex-1 w-full relative">
      {!blobUrl && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-white rounded-lg">
          <div className="w-8 h-8 border-2 border-muted-foreground/30 border-t-muted-foreground rounded-full animate-spin" />
          <span className="text-xs text-muted-foreground">Loading PDF…</span>
        </div>
      )}
      {blobUrl && (
        <iframe
          src={blobUrl}
          className="w-full h-full border-0 rounded-lg bg-white"
          title="PDF Preview"
        />
      )}
    </div>
  );
}

function PreviewVideo({ url, itemId }: { url: string; itemId?: string }) {
  const blobUrl = useBlobUrl(url);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [showTranscript, setShowTranscript] = useState(false);
  const transcript = useTranscript(itemId);
  const { speed, cycleSpeed, applySpeed } = usePlaybackSpeed(videoRef);
  const skip = useVideoSkip(videoRef);

  useVideoResume(videoRef, itemId, !!blobUrl);

  if (!blobUrl) return <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">Loading...</div>;
  return (
    <div className="flex-1 flex flex-col items-center justify-center p-4 gap-2">
      <div className="relative w-full flex-1 flex items-center justify-center min-h-0">
        <video
          ref={videoRef}
          src={blobUrl}
          controls
          className="max-w-full max-h-full rounded-lg"
          onLoadedMetadata={applySpeed}
        />
        {showTranscript && transcript && (
          <div className="absolute bottom-14 left-4 right-4 bg-black/75 text-white text-sm p-3 rounded-lg max-h-32 overflow-y-auto backdrop-blur-sm">
            {transcript}
          </div>
        )}
      </div>
      <div className="flex items-center gap-1.5 text-xs shrink-0">
        <button onClick={() => skip(-30)} className="px-2 py-1 rounded bg-muted hover:bg-muted/80 transition-colors cursor-pointer" title="Rewind 30s">-30s</button>
        <button onClick={() => skip(30)} className="px-2 py-1 rounded bg-muted hover:bg-muted/80 transition-colors cursor-pointer" title="Forward 30s">+30s</button>
        <button onClick={cycleSpeed} className="px-2 py-1 rounded bg-muted hover:bg-muted/80 transition-colors cursor-pointer font-mono min-w-[3rem] text-center" title="Playback speed">{speed}x</button>
        {transcript && (
          <button
            onClick={() => setShowTranscript(s => !s)}
            className={cn("px-2 py-1 rounded transition-colors cursor-pointer", showTranscript ? "text-white" : "bg-muted hover:bg-muted/80")}
            style={showTranscript ? { background: DRIVE_COLOR } : undefined}
            title="Toggle transcript"
          >
            Transcript
          </button>
        )}
      </div>
    </div>
  );
}

function PreviewAudio({ url, name }: { url: string; name: string }) {
  const blobUrl = useBlobUrl(url);
  if (!blobUrl) return <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">Loading...</div>;
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-4 p-4">
      <div className="text-5xl">{"\uD83C\uDFB5"}</div>
      <div className="text-sm font-medium text-foreground">{name}</div>
      <audio src={blobUrl} controls className="w-full max-w-md" />
    </div>
  );
}

// BUG-2 FIX: useEffect for side-effect (fetch text content)
function PreviewText({ url }: { url: string }) {
  const [content, setContent] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    apiFetch(url, { signal: ctrl.signal })
      .then(r => {
        if (r.status === 404) throw new Error("File not found on server");
        return verboseCheck(r, "fetch");
      })
      .then(r => r.text())
      .then(setContent)
      .catch(e => {
        if (e.name !== "AbortError") setErr(e.message);
      });
    return () => ctrl.abort();
  }, [url]);

  if (err) return (
    <div className="flex-1 flex flex-col items-center justify-center gap-3 text-muted-foreground">
      <div className="text-5xl">{"\uD83D\uDCC4"}</div>
      <div className="text-sm">{err}</div>
    </div>
  );
  if (content === null) return <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">Loading...</div>;

  return (
    <pre className="flex-1 overflow-auto p-4 text-sm font-mono text-foreground bg-card rounded-lg m-4 border border-border whitespace-pre-wrap break-words">
      {content}
    </pre>
  );
}

function PreviewUnsupported({ item }: { item: DriveEntry }) {
  const ext = item.kind === "file" ? (item as DriveFile).extension : "folder";
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-3 text-muted-foreground">
      <div className="text-6xl">{"\uD83D\uDCC4"}</div>
      <div className="text-base font-medium text-foreground">{item.name}</div>
      <div className="text-sm font-mono">.{ext} — no preview available</div>
      <div className="text-xs">{formatBytes(item.size)}</div>
    </div>
  );
}

export default function DrivePreview({ item, onClose, onDownload }: DrivePreviewProps) {
  const kind = detectPreviewKind(item);
  const previewUrl = item.kind === "file"
    ? (item as DriveFile).previewUrl ?? `${API_BASE}/drive/preview/${item.id}`
    : null;
  // PDFs use /preview/ endpoint (fetched via apiFetch with Authorization header)
  const pdfUrl = (kind === "pdf" && item.kind === "file")
    ? `${API_BASE}/drive/preview/${item.id}`
    : null;

  return (
    <div className="h-full flex flex-col bg-background">
      {/* Header */}
      <div className="px-4 py-3 border-b border-border flex items-center gap-3 shrink-0">
        <button
          onClick={onClose}
          className="w-8 h-8 rounded-lg flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors cursor-pointer shrink-0 text-lg"
          title="Close preview"
        >
          {"\u2715"}
        </button>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium truncate">{item.name}</div>
          <div className="text-xs text-muted-foreground font-mono mt-0.5">
            {formatBytes(item.size)}{item.mimeType ? ` \u00B7 ${item.mimeType}` : ""}
          </div>
        </div>
        {item.kind === "file" && (
          <button
            onClick={() => onDownload(item as DriveFile)}
            className={cn(
              "px-3 py-1.5 rounded-lg text-xs font-medium cursor-pointer transition-colors shrink-0",
              "border"
            )}
            style={{
              background: driveAlpha(0.09),
              borderColor: driveAlpha(0.25),
              color: DRIVE_COLOR,
            }}
          >
            Download
          </button>
        )}
      </div>

      {/* Content */}
      {kind === "image" && previewUrl && <PreviewImage url={previewUrl} name={item.name} />}
      {kind === "pdf" && pdfUrl && <PreviewPdf url={pdfUrl} />}
      {kind === "video" && previewUrl && <PreviewVideo url={previewUrl} itemId={item.id} />}
      {kind === "audio" && previewUrl && <PreviewAudio url={previewUrl} name={item.name} />}
      {(kind === "text" || kind === "code") && previewUrl && <PreviewText url={previewUrl} />}
      {kind === "unsupported" && <PreviewUnsupported item={item} />}
    </div>
  );
}
