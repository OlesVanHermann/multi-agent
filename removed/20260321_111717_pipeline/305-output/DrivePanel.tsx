import React, { useState, useRef, useCallback, useMemo, useEffect, Suspense } from "react";
import { apiFetch, verboseCheck } from '../lib/apiFetch';
import { useBlobUrl, useMediaUrl } from './useBlobUrl';
import { cn, formatBytes } from "../lib/utils";
import { useDrive } from "./useDrive";
import type { DriveEntry, DriveFile, DriveFolder, DriveViewTab, DriveSortField, SharePermission, ShareInfo } from "./drive-types";
import AlbumsTab from "./AlbumsTab";
import AlbumsSection from "./CreateAlbumDialog";
import AlbumsPanel from "./AlbumsPanel";
import { useDownload } from "./useDownload";
import { log } from "../lib/logger";
import { useVideoResume, useTranscript, usePlaybackSpeed, useVideoSkip } from './useVideoPlayer';

// Lazy imports to preserve code-splitting with drive-features-registry
const GalleryViewPanel = React.lazy(() => import("./GalleryViewPanel"));
const CopyFilesPanel = React.lazy(() => import("./CopyFilesPanel"));
const LazyMoveDialog = React.lazy(() => import("./MoveFilesPanel").then(m => ({ default: m.MoveDialog })));
const VersionHistoryPanel = React.lazy(() => import("./VersionHistoryPanel"));
const CommanderMode = React.lazy(() => import("./CommanderMode"));
import type { CommanderActions } from "./CommanderMode";

// =======================================
//  DRIVE PANEL — Agent 305 (Cycle 3)
//  File browser for the SaaS split-screen
// =======================================

const DRIVE_COLOR = "var(--color-drive)";
const DRIVE_ICON = "\uD83D\uDCBE";

/** Apply alpha to --color-drive via color-mix (CSS variable-safe) */
function driveAlpha(a: number): string {
  return `color-mix(in oklch, var(--color-drive) ${Math.round(a * 100)}%, transparent)`;
}

/** Truncate folder name: keep start + end with "..." in middle. Max ~20 chars (2 lines of 10). */
function truncFolderName(name: string, max = 20): string {
  if (name.length <= max) return name;
  const side = Math.floor((max - 3) / 2);
  return name.slice(0, side) + "..." + name.slice(-side);
}

// -- Icon helpers --
/** Returns { label, color } for a file type badge instead of emoji */
function fileTypeBadge(item: DriveEntry): { label: string; color: string } {
  if (item.kind === "folder") return { label: "DIR", color: "var(--color-drive)" };
  const ext = (item as DriveFile).extension?.toLowerCase() ?? "";
  const mime = item.mimeType?.toLowerCase() ?? "";
  if (mime.startsWith("image/") || /^(png|jpg|jpeg|gif|webp|svg|bmp|ico)$/.test(ext)) return { label: ext.toUpperCase() || "IMG", color: "#e879a0" };
  if (mime === "application/pdf" || ext === "pdf") return { label: "PDF", color: "#e04040" };
  if (mime.startsWith("video/") || /^(mp4|webm|mov|avi|mkv)$/.test(ext)) return { label: ext.toUpperCase() || "VID", color: "#a855f7" };
  if (mime.startsWith("audio/") || /^(mp3|wav|flac|ogg|aac)$/.test(ext)) return { label: ext.toUpperCase() || "AUD", color: "#f59e0b" };
  if (/^(ts|tsx|js|jsx)$/.test(ext)) return { label: ext.toUpperCase(), color: "#3b82f6" };
  if (/^(py)$/.test(ext)) return { label: "PY", color: "#facc15" };
  if (/^(rs|go|java|c|cpp|h|hpp|rb|php|sh|bash)$/.test(ext)) return { label: ext.toUpperCase(), color: "#64748b" };
  if (/^(json|yaml|yml|toml|xml|html|css|scss|sql|md|txt|log|csv|env|conf|ini|cfg)$/.test(ext)) return { label: ext.toUpperCase(), color: "#94a3b8" };
  if (/^(zip|tar|gz|tgz|bz2|xz|rar|7z)$/.test(ext)) return { label: "ZIP", color: "#78716c" };
  if (/^(doc|docx|odt|rtf)$/.test(ext)) return { label: "DOC", color: "#2b579a" };
  if (/^(xls|xlsx|ods)$/.test(ext)) return { label: "XLS", color: "#1d7044" };
  if (/^(ppt|pptx|pptm|odp)$/.test(ext)) return { label: "PPT", color: "#d04423" };
  if (/^(dmg|iso|deb|rpm|apk)$/.test(ext)) return { label: ext.toUpperCase(), color: "#78716c" };
  if (ext) return { label: ext.toUpperCase().slice(0, 4), color: "#64748b" };
  return { label: "FILE", color: "#64748b" };
}

/** Short text label for file type (no emoji) */
function fileIcon(item: DriveEntry): string {
  if (item.kind === "folder") return "DIR";
  const ext = (item as DriveFile).extension?.toLowerCase() ?? "";
  const mime = item.mimeType?.toLowerCase() ?? "";
  if (mime.startsWith("image/") || /^(png|jpg|jpeg|gif|webp|svg)$/.test(ext)) return "IMG";
  if (mime === "application/pdf" || ext === "pdf") return "PDF";
  if (mime.startsWith("video/") || /^(mp4|webm|mov)$/.test(ext)) return "VID";
  if (mime.startsWith("audio/") || /^(mp3|wav|flac)$/.test(ext)) return "AUD";
  if (/^(ts|tsx|js|jsx|py|rs|go|java|c|cpp|rb|php)$/.test(ext)) return "SRC";
  if (/^(zip|tar|gz|rar|7z)$/.test(ext)) return "ZIP";
  if (/^(doc|docx|odt)$/.test(ext)) return "DOC";
  if (/^(xls|xlsx|ods|csv)$/.test(ext)) return "XLS";
  if (/^(ppt|pptx|odp)$/.test(ext)) return "PPT";
  return "FILE";
}

function timeAgo(dateStr: string): string {
  if (!dateStr) return "";
  const then = new Date(dateStr).getTime();
  if (isNaN(then)) return "";
  const now = Date.now();
  const diff = now - then;
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(dateStr).toLocaleDateString();
}

// =======================================
//  SUB-COMPONENTS
// =======================================

function Breadcrumbs({
  crumbs,
  onNavigate,
  hoverName,
  siblingIndex,
  siblingCount,
  onPrev,
  onNext,
}: {
  crumbs: { id: string; name: string }[];
  onNavigate: (id: string | null) => void;
  hoverName?: string | null;
  siblingIndex?: number;
  siblingCount?: number;
  onPrev?: () => void;
  onNext?: () => void;
}) {
  const hasSiblings = (siblingCount ?? 0) > 1;
  const canPrev = hasSiblings && (siblingIndex ?? 0) > 0;
  const canNext = hasSiblings && (siblingIndex ?? 0) < (siblingCount ?? 0) - 1;

  return (
    <div className={`flex items-center gap-1 text-sm min-w-0 shrink ${hoverName ? "overflow-visible" : "overflow-hidden"}`}>
      <button
        onClick={() => onNavigate(null)}
        className="shrink-0 text-muted-foreground hover:text-foreground cursor-pointer transition-colors font-medium whitespace-nowrap"
      >
        {DRIVE_ICON} Drive
      </button>
      {crumbs.map((c, i) => {
        const isLast = i === crumbs.length - 1;
        return (
          <span key={c.id} className="flex items-center gap-1 min-w-0 shrink">
            <span className="text-muted-foreground/40 shrink-0">/</span>
            {isLast && hasSiblings && (
              <>
                {canPrev ? (
                  <button
                    onClick={onPrev}
                    className="shrink-0 text-xs cursor-pointer transition-colors hover:text-foreground"
                    style={{ color: "var(--foreground)" }}
                  >{"\u2190"}</button>
                ) : (
                  <span className="shrink-0 text-xs text-muted-foreground/30">o</span>
                )}
                {canNext ? (
                  <button
                    onClick={onNext}
                    className="shrink-0 text-xs cursor-pointer transition-colors hover:text-foreground"
                    style={{ color: "var(--foreground)" }}
                  >{"\u2192"}</button>
                ) : (
                  <span className="shrink-0 text-xs text-muted-foreground/30">o</span>
                )}
                <span className="text-muted-foreground/40 shrink-0">/</span>
              </>
            )}
            <button
              onClick={() => onNavigate(c.id)}
              className="truncate text-muted-foreground hover:text-foreground cursor-pointer transition-colors whitespace-nowrap"
              style={{ maxWidth: "40ch" }}
            >
              {c.name}
            </button>
          </span>
        );
      })}
      {hoverName && (
        <span className="flex items-center gap-1 min-w-0 shrink-0">
          <span className="text-muted-foreground/40 shrink-0">/</span>
          <span
            className="whitespace-nowrap transition-colors"
            style={{ color: "var(--foreground)" }}
          >
            {hoverName}
          </span>
        </span>
      )}
    </div>
  );
}

function SortButton({
  field,
  label,
  currentSort,
  onSort,
}: {
  field: DriveSortField;
  label: string;
  currentSort: { field: DriveSortField; dir: "asc" | "desc" };
  onSort: (f: DriveSortField) => void;
}) {
  const active = currentSort.field === field;
  return (
    <button
      onClick={() => onSort(field)}
      className={cn(
        "text-xs font-mono px-2 py-1 rounded cursor-pointer transition-colors",
        active ? "text-foreground" : "text-muted-foreground hover:text-foreground"
      )}
    >
      {label} {active ? (currentSort.dir === "asc" ? "\u2191" : "\u2193") : ""}
    </button>
  );
}

function QuotaBar({ used, total }: { used: number; total: number }) {
  const pct = total > 0 ? Math.min((used / total) * 100, 100) : 0;
  const warn = pct > 80;
  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <div className="w-20 h-1.5 rounded-full bg-muted overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-300"
          style={{
            width: `${pct}%`,
            background: warn ? "var(--color-warning)" : DRIVE_COLOR,
          }}
        />
      </div>
      <span className="font-mono">{formatBytes(used)} / {formatBytes(total)}</span>
    </div>
  );
}


// -- Empty states --
function EmptyState({ tab, onUpload }: { tab: DriveViewTab; onUpload?: () => void }) {
  const configs: Record<DriveViewTab, { icon: string; title: string; sub: string }> = {
    files: { icon: "--", title: "No files yet", sub: "Upload files or create a folder to get started" },
    shared: { icon: "--", title: "No shared files", sub: "Files shared with you will appear here" },
    recent: { icon: "--", title: "No recent files", sub: "Recently accessed files will appear here" },
    trash: { icon: "--", title: "Trash is empty", sub: "Deleted files will appear here for 30 days" },
    albums: { icon: "--", title: "No albums yet", sub: "Create an album to organize your photos and videos" },
  };
  const cfg = configs[tab];
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-2 text-muted-foreground py-16">
      <span className="text-5xl mb-2">{cfg.icon}</span>
      <div className="text-base font-medium text-foreground">{cfg.title}</div>
      <div className="text-sm text-muted-foreground/60">{cfg.sub}</div>
      {tab === "files" && onUpload && (
        <button
          onClick={onUpload}
          className="mt-3 px-4 py-2 rounded text-sm font-medium cursor-pointer transition-colors border border-border text-foreground hover:bg-muted/50"
        >
          Upload files
        </button>
      )}
    </div>
  );
}

// =======================================
//  SHARE DIALOG (MISSING-1 fix)
// =======================================

function ShareDialog({
  item,
  onClose,
  onShare,
  onGetShares,
  onRevoke,
}: {
  item: DriveEntry;
  onClose: () => void;
  onShare: (id: string, permission: SharePermission, email?: string, expiresInDays?: number) => Promise<{ link: string }>;
  onGetShares: (id: string) => Promise<ShareInfo[]>;
  onRevoke: (shareId: string) => Promise<void>;
}) {
  const [permission, setPermission] = useState<SharePermission>("view");
  const [email, setEmail] = useState("");
  const [expiresInDays, setExpiresInDays] = useState<number | undefined>(undefined);
  const [link, setLink] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [shares, setShares] = useState<ShareInfo[]>([]);
  const [loadingShares, setLoadingShares] = useState(true);

  // Load existing shares
  useEffect(() => {
    let cancelled = false;
    onGetShares(item.id)
      .then(s => { if (!cancelled) setShares(s); })
      .catch((err) => { console.warn("[Drive] getShareInfo failed:", err); })
      .finally(() => { if (!cancelled) setLoadingShares(false); });
    return () => { cancelled = true; };
  }, [item.id, onGetShares]);

  const handleShare = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await onShare(item.id, permission, email || undefined, expiresInDays);
      setLink(result.link);
      // Refresh shares list
      const updated = await onGetShares(item.id);
      setShares(updated);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [item.id, permission, email, expiresInDays, onShare, onGetShares]);

  const handleCopy = useCallback(async () => {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.warn("[Drive] clipboard write failed:", err);
    }
  }, [link]);

  const handleRevoke = useCallback(async (shareId: string) => {
    await onRevoke(shareId);
    setShares(prev => prev.filter(s => s.id !== shareId));
  }, [onRevoke]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="absolute inset-0 bg-background/60 backdrop-blur-sm" />
      <div
        className="relative bg-card border border-border rounded-xl shadow-xl w-full max-w-md mx-4 p-6"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center gap-3 mb-5">
          <span className="text-2xl">{fileIcon(item)}</span>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium truncate text-foreground">Share "{item.name}"</div>
            <div className="text-xs text-muted-foreground font-mono">{formatBytes(item.size)}</div>
          </div>
          <button
            onClick={onClose}
            className="w-7 h-7 rounded-lg flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors cursor-pointer"
          >
            \u2715
          </button>
        </div>

        {/* Permission selector */}
        <div className="mb-4">
          <label className="text-xs font-medium text-muted-foreground mb-1.5 block">Permission</label>
          <div className="flex gap-2">
            {(["view", "edit"] as const).map(p => (
              <button
                key={p}
                onClick={() => setPermission(p)}
                className={cn(
                  "flex-1 px-3 py-2 rounded-lg text-sm font-medium cursor-pointer transition-colors border",
                  permission === p
                    ? "text-foreground"
                    : "border-border text-muted-foreground hover:text-foreground hover:bg-muted/30"
                )}
                style={permission === p ? {
                  background: driveAlpha(0.12),
                  borderColor: driveAlpha(0.35),
                  color: DRIVE_COLOR,
                } : undefined}
              >
                {p === "view" ? "\uD83D\uDC41\uFE0F View" : "\u270F\uFE0F Edit"}
              </button>
            ))}
          </div>
        </div>

        {/* Email (optional) */}
        <div className="mb-4">
          <label className="text-xs font-medium text-muted-foreground mb-1.5 block">Share with (optional)</label>
          <input
            value={email}
            onChange={e => setEmail(e.target.value)}
            placeholder="email@example.com"
            className="w-full px-3 py-2 rounded-lg text-sm border border-border bg-background text-foreground outline-none placeholder:text-muted-foreground/40 focus:border-ring"
          />
        </div>

        {/* Expiration selector */}
        <div className="mb-4">
          <label className="text-xs font-medium text-muted-foreground mb-1.5 block">Expires</label>
          <div className="flex gap-2">
            {([
              { label: "Never", value: undefined },
              { label: "7 days", value: 7 },
              { label: "30 days", value: 30 },
              { label: "90 days", value: 90 },
            ] as const).map(opt => (
              <button
                key={opt.label}
                onClick={() => setExpiresInDays(opt.value)}
                className={cn(
                  "flex-1 px-2 py-1.5 rounded-lg text-xs font-medium cursor-pointer transition-colors border",
                  expiresInDays === opt.value
                    ? "text-foreground"
                    : "border-border text-muted-foreground hover:text-foreground hover:bg-muted/30"
                )}
                style={expiresInDays === opt.value ? {
                  background: driveAlpha(0.12),
                  borderColor: driveAlpha(0.35),
                  color: DRIVE_COLOR,
                } : undefined}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* Share button */}
        <button
          onClick={handleShare}
          disabled={loading}
          className="w-full px-4 py-2.5 rounded-lg text-sm font-medium cursor-pointer transition-colors border mb-4"
          style={{
            background: driveAlpha(0.15),
            borderColor: driveAlpha(0.35),
            color: DRIVE_COLOR,
            opacity: loading ? 0.6 : 1,
          }}
        >
          {loading ? "Creating link..." : "\uD83D\uDD17 Create share link"}
        </button>

        {/* Error */}
        {error && (
          <div className="text-xs text-danger font-mono mb-3">{error}</div>
        )}

        {/* Generated link */}
        {link && (
          <div className="mb-4 p-3 rounded-lg bg-muted/30 border border-border">
            <div className="text-xs font-medium text-muted-foreground mb-1.5">Share link</div>
            <div className="flex items-center gap-2">
              <input
                readOnly
                value={link}
                className="flex-1 text-xs font-mono text-foreground bg-transparent outline-none truncate"
              />
              <button
                onClick={handleCopy}
                className="shrink-0 px-2.5 py-1 rounded text-xs font-medium cursor-pointer transition-colors"
                style={{ color: DRIVE_COLOR }}
              >
                {copied ? "\u2713 Copied" : "Copy"}
              </button>
            </div>
          </div>
        )}

        {/* Existing shares */}
        {!loadingShares && shares.length > 0 && (
          <div>
            <div className="text-xs font-medium text-muted-foreground mb-2">Active shares</div>
            <div className="space-y-1.5 max-h-32 overflow-auto">
              {shares.map(s => (
                <div key={s.id} className="flex items-center gap-2 text-xs">
                  <span className="text-muted-foreground">
                    {s.recipientEmail || "Anyone with link"}
                  </span>
                  <span className="font-mono text-muted-foreground/60">{s.permission}</span>
                  {s.expiresAt && (
                    <span className="font-mono text-muted-foreground/40" title={`Expires ${new Date(s.expiresAt).toLocaleDateString()}`}>
                      exp {timeAgo(s.expiresAt)}
                    </span>
                  )}
                  <div className="flex-1" />
                  <button
                    onClick={() => handleRevoke(s.id)}
                    className="text-danger hover:underline cursor-pointer"
                  >
                    Revoke
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// -- File row --
function FileRow({
  item,
  selected,
  active,
  compact,
  onSelect,
  onClick,
  onStar,
  onDelete,
  onRename,
  onShare,
  onDownload,
  onCopy,
  onMove,
  onVersionHistory,
  onEdit,
  onRestore,
  isTrash,
  menuOpen,
  onMenuToggle,
  onDragStart,
  showCheckbox,
}: {
  item: DriveEntry;
  selected: boolean;
  active?: boolean;
  compact?: boolean;
  onSelect: () => void;
  onClick: () => void;
  onStar: () => void;
  onDelete: () => void;
  onRename: (newName: string) => void;
  onShare: () => void;
  onDownload: () => void;
  onCopy: () => void;
  onMove: () => void;
  onVersionHistory: () => void;
  onEdit?: () => void;
  onRestore?: () => void;
  isTrash: boolean;
  menuOpen: boolean;
  onMenuToggle: () => void;
  onDragStart?: (clientY: number) => void;
  showCheckbox?: boolean;
}) {
  const [renaming, setRenaming] = useState(false);
  const [newName, setNewName] = useState(item.name);
  const inputRef = useRef<HTMLInputElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close menu on outside click
  useEffect(() => {
    if (!menuOpen) return;
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onMenuToggle();
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [menuOpen, onMenuToggle]);

  const startRename = useCallback(() => {
    setNewName(item.name);
    setRenaming(true);
    setTimeout(() => inputRef.current?.select(), 0);
  }, [item.name]);

  // BUG-1 FIX: commitRename passes newName to onRename callback
  const commitRename = useCallback(() => {
    setRenaming(false);
    const trimmed = newName.trim();
    if (trimmed && trimmed !== item.name) {
      onRename(trimmed);
    }
  }, [newName, item.name, onRename]);

  const isUploading = item.uploadStatus === "uploading";

  return (
    <div
      className={cn(
        "group flex items-center gap-3 px-4 transition-colors",
        item.kind === "folder" ? "py-3" : "py-2.5",
        isUploading ? "opacity-40 pointer-events-none" : "cursor-pointer hover:bg-muted/30",
        selected && "bg-muted/50",
        active && "bg-muted/40"
      )}
      style={{
        borderLeft: active ? `3px solid ${DRIVE_COLOR}` : "3px solid transparent",
        ...(item.kind === "folder" ? { background: selected ? undefined : driveAlpha(0.04) } : {}),
      }}
      onClick={isUploading ? undefined : onClick}
    >
      {/* Icon slot — checkbox in selection mode, file type badge otherwise */}
      {!compact && showCheckbox ? (
        <div
          className="flex items-center justify-center w-8 h-5 shrink-0 cursor-pointer"
          onClick={(e) => { e.stopPropagation(); }}
          onMouseDown={(e) => { if (e.button === 0 && onDragStart) { e.stopPropagation(); onDragStart(e.clientY); } }}
        >
          <input
            type="checkbox"
            checked={selected}
            readOnly
            className="w-4 h-4 rounded cursor-pointer pointer-events-none"
            style={{ accentColor: DRIVE_COLOR }}
          />
        </div>
      ) : (() => {
        const badge = fileTypeBadge(item);
        return (
          <span
            className="shrink-0 flex items-center justify-center rounded text-[9px] font-bold w-8 h-5 uppercase tracking-tight"
            style={{
              color: badge.color,
              background: badge.color + "18",
              border: `1px solid ${badge.color}30`,
            }}
          >
            {badge.label}
          </span>
        );
      })()}

      {/* Name */}
      <div className="flex-1 min-w-0">
        {renaming ? (
          <input
            ref={inputRef}
            value={newName}
            onChange={e => setNewName(e.target.value)}
            onBlur={commitRename}
            onKeyDown={e => {
              if (e.key === "Enter") commitRename();
              if (e.key === "Escape") setRenaming(false);
            }}
            onClick={e => e.stopPropagation()}
            className="w-full bg-transparent text-sm text-foreground outline-none font-medium"
            style={{ borderBottom: `1px solid ${DRIVE_COLOR}` }}
            autoFocus
          />
        ) : (
          <div className="flex items-center gap-1.5">
            <span className={cn(
              "truncate text-foreground",
              compact ? "text-xs" : "text-sm",
              item.kind === "folder" ? "font-semibold" : "font-medium"
            )}>{item.name}</span>
            {item.kind === "folder" && (
              <span className="text-[10px] text-muted-foreground opacity-60">{(item as DriveFolder).childCount} items</span>
            )}
            {item.shared && (
              <span className="text-[9px] text-muted-foreground/60 font-mono" title="Shared">shared</span>
            )}
          </div>
        )}
      </div>

      {/* Size (hidden in compact) */}
      {!compact && (
        <span className="text-xs text-muted-foreground font-mono w-16 text-right shrink-0">
          {isUploading ? "--" : (
            item.kind === "file" ? formatBytes(item.size) : `${(item as DriveFolder).childCount} items`
          )}
        </span>
      )}

      {/* Modified (hidden in compact) */}
      {!compact && (
        <span className="text-xs text-muted-foreground font-mono w-16 text-right shrink-0">
          {timeAgo(item.updatedAt)}
        </span>
      )}

      {/* Actions (hidden in compact) */}
      {!compact && <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
        {!isTrash && (
          <></>
        )}
        {isTrash && onRestore ? (
          <button
            onClick={e => { e.stopPropagation(); onRestore(); }}
            className="px-1.5 h-6 rounded flex items-center justify-center text-[10px] font-medium hover:bg-muted/50 cursor-pointer transition-colors text-muted-foreground"
            title="Restore"
          >
            Restore
          </button>
        ) : null}
        {isTrash && (
          <button
            onClick={e => { e.stopPropagation(); onDelete(); }}
            className="px-1.5 h-6 rounded flex items-center justify-center text-[10px] font-medium hover:bg-muted/50 cursor-pointer transition-colors text-danger"
            title="Delete permanently"
          >
            Del
          </button>
        )}
      </div>}
    </div>
  );
}

// =======================================
//  SPLIT-PANE SUB-COMPONENTS
// =======================================

const API_BASE = import.meta.env.VITE_API_URL ?? "/api";
const FILES_API = `${API_BASE}/drive/files`;

// =======================================
//  NEW FILE — Types & Components
// =======================================

type NewFilePhase = "idle" | "pick-type" | "editing";

const EDITABLE_EXTS = new Set(["txt","md","csv","json","html","py","js","ts","tsx","jsx","css","xml","yaml","yml","log","sh","conf","ini","cfg","sql","toml"]);
function isEditable(item: DriveEntry): boolean {
  if (item.kind !== "file") return false;
  const ext = (item as DriveFile).extension?.toLowerCase() ?? "";
  return EDITABLE_EXTS.has(ext);
}

const NEW_FILE_TYPES = [
  { ext: "txt", label: ".txt", icon: "\uD83D\uDCC4" },
  { ext: "md", label: ".md", icon: "\uD83D\uDCDD" },
  { ext: "pdf", label: ".pdf", icon: "\uD83D\uDCCB" },
  { ext: "csv", label: ".csv", icon: "\uD83D\uDCCA" },
  { ext: "json", label: ".json", icon: "\u007B\u007D" },
  { ext: "html", label: ".html", icon: "\uD83C\uDF10" },
  { ext: "py", label: ".py", icon: "\uD83D\uDC0D" },
  { ext: "js", label: ".js", icon: "\u26A1" },
] as const;

function NewFileTypePicker({ onPick, onCancel }: { onPick: (filename: string) => void; onCancel: () => void }) {
  const [names, setNames] = useState<Record<string, string>>(() => {
    const m: Record<string, string> = {};
    NEW_FILE_TYPES.forEach(ft => { m[ft.ext] = `untitled.${ft.ext}`; });
    return m;
  });
  const inputRefs = useRef<Record<string, HTMLInputElement | null>>({});

  const confirm = (ext: string) => {
    const val = (names[ext] || `untitled.${ext}`).trim();
    if (val) onPick(val);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(0,0,0,0.5)" }}
      onClick={(e) => { if (e.target === e.currentTarget) onCancel(); }}
    >
      <div className="bg-background border border-border rounded-xl p-6 shadow-xl max-w-md w-full">
        <h3 className="text-sm font-semibold text-foreground mb-4">New file — pick type &amp; name</h3>
        <div className="grid grid-cols-2 gap-2">
          {NEW_FILE_TYPES.map((ft) => (
            <div
              key={ft.ext}
              className="flex items-center gap-2 p-2 rounded-lg border border-border hover:border-current transition-colors cursor-pointer"
              onClick={() => {
                const inp = inputRefs.current[ft.ext];
                if (inp) { inp.focus(); inp.setSelectionRange(0, inp.value.lastIndexOf(".") > 0 ? inp.value.lastIndexOf(".") : inp.value.length); }
              }}
            >
              <span className="text-lg shrink-0 w-7 text-center">{ft.icon}</span>
              <input
                ref={el => { inputRefs.current[ft.ext] = el; }}
                type="text"
                value={names[ft.ext] ?? ""}
                onChange={(e) => setNames(prev => ({ ...prev, [ft.ext]: e.target.value }))}
                onKeyDown={(e) => {
                  if (e.key === "Enter") confirm(ft.ext);
                  else if (e.key === "Escape") onCancel();
                }}
                onFocus={(e) => {
                  const v = e.target.value;
                  const dot = v.lastIndexOf(".");
                  e.target.setSelectionRange(0, dot > 0 ? dot : v.length);
                }}
                onClick={(e) => e.stopPropagation()}
                className="flex-1 min-w-0 bg-transparent text-xs font-mono text-foreground outline-none border-b border-transparent focus:border-current transition-colors"
                style={{ color: DRIVE_COLOR }}
              />
              <button
                onClick={(e) => { e.stopPropagation(); confirm(ft.ext); }}
                className="shrink-0 w-6 h-6 rounded flex items-center justify-center text-xs hover:bg-muted/50 cursor-pointer transition-colors"
                style={{ color: DRIVE_COLOR }}
                title="Create"
              >
                {"\u2192"}
              </button>
            </div>
          ))}
        </div>
        <button onClick={onCancel} className="mt-4 w-6 h-6 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors cursor-pointer mx-auto text-xs" title="Cancel">{"\u2715"}</button>
      </div>
    </div>
  );
}

function NewFileEditor({
  ext, content, onChange, onSave, onCancel, fileName,
}: {
  ext: string; content: string; onChange: (v: string) => void; onSave: () => void; onCancel: () => void; fileName?: string;
}) {
  const isPdf = ext === "pdf";
  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="flex items-center justify-between px-4 py-2 border-b border-border">
        <div className="flex items-center gap-2">
          <span
            className="px-2 py-0.5 rounded-md text-xs font-mono font-medium"
            style={{ background: driveAlpha(0.15), color: DRIVE_COLOR }}
          >
            {fileName || `.${ext}`}
          </span>
          {isPdf && (
            <span className="text-xs text-muted-foreground">Write markdown — converted to PDF on save</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            className="px-3 py-1.5 rounded-lg text-xs font-medium cursor-pointer"
            style={{ color: DRIVE_COLOR }}
            onClick={onSave}
          >
            Save
          </button>
          <button onClick={onCancel} className="w-5 h-5 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors cursor-pointer shrink-0 text-[10px]" title="Cancel">{"\u2715"}</button>
        </div>
      </div>
      <textarea
        className="flex-1 min-h-[300px] p-4 bg-background text-foreground font-mono text-sm resize-none focus:outline-none border-none"
        value={content}
        onChange={(e) => onChange(e.target.value)}
        placeholder={isPdf ? "# Title\n\nWrite markdown here..." : `Start typing your .${ext} file...`}
        autoFocus
      />
    </div>
  );
}

/* NewFileSaveDialog removed — filename is now set in the type picker */

type PreviewKind = "image" | "pdf" | "text" | "code" | "video" | "audio" | "archive" | "office" | "unsupported";

function detectPreviewKind(item: DriveEntry): PreviewKind {
  if (item.kind === "folder") return "unsupported";
  const ext = (item as DriveFile).extension?.toLowerCase() ?? "";
  const mime = item.mimeType?.toLowerCase() ?? "";
  if (mime.startsWith("image/") || /^(png|jpg|jpeg|gif|webp|svg|bmp|ico)$/.test(ext)) return "image";
  if (mime === "application/pdf" || ext === "pdf") return "pdf";
  if (mime.startsWith("video/") || /^(mp4|webm|ogg|mov)$/.test(ext)) return "video";
  if (mime.startsWith("audio/") || /^(mp3|wav|ogg|flac|aac)$/.test(ext)) return "audio";
  if (/^(zip|tar|gz|tgz|bz2|xz)$/.test(ext)) return "archive";
  if (/^(doc|docx|odt|rtf|xls|xlsx|ods|ppt|pptx|pptm|odp)$/.test(ext)) return "office";
  if (mime.includes("officedocument") || mime.includes("msword") || mime.includes("ms-excel") || mime.includes("ms-powerpoint") || mime.includes("opendocument")) return "office";
  if (/^(ts|tsx|js|jsx|py|rs|go|java|c|cpp|h|hpp|rb|php|sh|bash|zsh|yaml|yml|toml|json|xml|html|css|scss|sql|md|txt|log|csv|env|conf|ini|cfg)$/.test(ext)) return "code";
  if (mime.startsWith("text/")) return "text";
  return "unsupported";
}


interface ArchiveEntry {
  path: string;
  name: string;
  size: number;
  is_dir: boolean;
  compressed: number;
  mime_type: string;
}

type ArchiveFileKind = "image" | "pdf" | "text" | "code" | "video" | "audio" | "archive" | "none";

function archiveFileKind(entry: ArchiveEntry): ArchiveFileKind {
  const mime = entry.mime_type || "";
  const name = (entry.name || "").toLowerCase();
  if (mime.startsWith("image/")) return "image";
  if (mime === "application/pdf") return "pdf";
  if (mime.startsWith("video/")) return "video";
  if (mime.startsWith("audio/")) return "audio";
  if (/\.(zip|tar\.gz|tgz|tar\.bz2|tar\.xz|tar)$/.test(name)) return "archive";
  if (mime === "application/zip" || mime === "application/gzip" || mime === "application/x-tar" || mime === "application/x-gzip") return "archive";
  if (mime.startsWith("text/") || mime === "application/json" || mime === "application/xml" || mime === "application/javascript") return "code";
  return "none";
}

function archiveEntryIcon(entry: ArchiveEntry, expanded: boolean): string {
  if (entry.is_dir) return expanded ? "\uD83D\uDCC2" : "\uD83D\uDCC1";
  const kind = archiveFileKind(entry);
  if (kind === "image") return "\uD83D\uDDBC\uFE0F";
  if (kind === "video") return "\uD83C\uDFAC";
  if (kind === "audio") return "\uD83C\uDFB5";
  if (kind === "pdf") return "\uD83D\uDCC4";
  if (kind === "code" || kind === "text") return "\uD83D\uDCDD";
  if (kind === "archive") return "\uD83D\uDCE6";
  return "\uD83D\uDCC3";
}

function ArchiveFilePreview({ itemId, entry }: { itemId: string; entry: ArchiveEntry }) {
  const kind = archiveFileKind(entry);
  const fileUrl = `${API_BASE}/drive/archive/${itemId}/file?path=${encodeURIComponent(entry.path)}`;
  const needsImgBlob = kind === "image" || kind === "pdf";
  const blobUrl = useBlobUrl(needsImgBlob ? fileUrl : null);
  const media = useMediaUrl((kind === "video" || kind === "audio") ? fileUrl : null);
  const [textContent, setTextContent] = useState<string | null>(null);
  const [textErr, setTextErr] = useState<string | null>(null);

  useEffect(() => {
    if (kind !== "text" && kind !== "code") return;
    setTextContent(null);
    setTextErr(null);
    const ctrl = new AbortController();
    apiFetch(fileUrl, { signal: ctrl.signal })
      .then(r => verboseCheck(r, "fetch")).then(r => r.text())
      .then(setTextContent)
      .catch(e => { if (e.name !== "AbortError") setTextErr(e.message); });
    return () => ctrl.abort();
  }, [fileUrl, kind]);

  if (kind === "image") {
    if (!blobUrl) return <div className="h-full flex items-center justify-center text-muted-foreground text-xs">Loading...</div>;
    return <div className="h-full flex items-center justify-center p-2"><img src={blobUrl} alt={entry.name} className="max-w-full max-h-full object-contain rounded" /></div>;
  }
  if (kind === "pdf") {
    if (!blobUrl) return <div className="h-full flex items-center justify-center text-muted-foreground text-xs">Loading PDF…</div>;
    return <iframe src={blobUrl} className="w-full h-full border-0 bg-white rounded" title={entry.name} />;
  }
  if (kind === "video") {
    if (media.error) return <div className="h-full flex items-center justify-center text-destructive text-xs">{media.error}</div>;
    if (!media.url) return (
      <div className="h-full flex flex-col items-center justify-center gap-2 text-muted-foreground">
        <span className="text-2xl opacity-60">{"\uD83C\uDFAC"}</span>
        <div className="w-32 h-1 rounded-full bg-muted overflow-hidden"><div className="h-full rounded-full transition-all duration-150" style={{ width: `${media.progress}%`, background: DRIVE_COLOR }} /></div>
        <span className="text-[10px]">{media.progress > 0 ? `${media.progress}%` : "Loading…"}</span>
      </div>
    );
    return <div className="h-full flex items-center justify-center p-2"><video src={media.url} controls className="max-w-full max-h-full rounded" /></div>;
  }
  if (kind === "audio") {
    if (media.error) return <div className="h-full flex items-center justify-center text-destructive text-xs">{media.error}</div>;
    if (!media.url) return (
      <div className="h-full flex flex-col items-center justify-center gap-2 text-muted-foreground">
        <span className="text-2xl opacity-60">{"\uD83C\uDFB5"}</span>
        <div className="w-32 h-1 rounded-full bg-muted overflow-hidden"><div className="h-full rounded-full transition-all duration-150" style={{ width: `${media.progress}%`, background: DRIVE_COLOR }} /></div>
        <span className="text-[10px]">{media.progress > 0 ? `${media.progress}%` : "Loading…"}</span>
      </div>
    );
    return <div className="h-full flex items-center justify-center p-4"><audio src={media.url} controls className="w-full" /></div>;
  }
  if (kind === "code" || kind === "text") {
    if (textErr) return <div className="flex items-center justify-center h-full text-destructive text-xs">{textErr}</div>;
    if (textContent === null) return <div className="flex items-center justify-center h-full text-muted-foreground text-xs">Loading...</div>;
    return <pre className="overflow-auto p-3 text-xs font-mono text-foreground/80 whitespace-pre-wrap break-words h-full">{textContent}</pre>;
  }
  if (kind === "archive") {
    return <NestedArchivePreview outerItemId={itemId} archivePath={entry.path} />;
  }
  return (
    <div className="h-full flex flex-col items-center justify-center gap-2 text-muted-foreground/50">
      <span className="text-2xl">{"\uD83D\uDCC4"}</span>
      <span className="text-xs">No preview for this file type</span>
      <span className="text-[10px] font-mono">{entry.name} -- {formatBytes(entry.size)}</span>
    </div>
  );
}

function NestedArchivePreview({ outerItemId, archivePath }: { outerItemId: string; archivePath: string }) {
  const [entries, setEntries] = useState<ArchiveEntry[]>([]);
  const [archiveName, setArchiveName] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set());
  const [selectedFile, setSelectedFile] = useState<ArchiveEntry | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    setSelectedFile(null);
    apiFetch(`${API_BASE}/drive/archive/${outerItemId}/nested-list?path=${encodeURIComponent(archivePath)}`)
      .then(r => verboseCheck(r, "fetch")).then(r => r.json())
      .then(data => {
        setArchiveName(data.archive_name ?? "");
        setEntries(data.entries ?? []);
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [outerItemId, archivePath]);

  const toggleDir = useCallback((path: string) => {
    setExpandedDirs(prev => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path); else next.add(path);
      return next;
    });
  }, []);

  if (loading) return <div className="flex items-center justify-center h-full text-muted-foreground text-sm">Loading nested archive...</div>;
  if (error) return <div className="flex items-center justify-center h-full text-destructive text-sm">Error: {error}</div>;

  const roots: ArchiveEntry[] = [];
  const children: Record<string, ArchiveEntry[]> = {};
  for (const entry of entries) {
    const parts = entry.path.replace(/\/$/, "").split("/");
    if (parts.length <= 1) {
      roots.push(entry);
    } else {
      const parentPath = parts.slice(0, -1).join("/");
      if (!children[parentPath]) children[parentPath] = [];
      children[parentPath].push(entry);
    }
  }

  const topDirs = roots.filter(e => e.is_dir);
  const showRoots = topDirs.length === 1 && roots.length === 1
    ? (children[topDirs[0].path.replace(/\/$/, "")] ?? [])
    : roots;

  function renderEntry(entry: ArchiveEntry, depth: number) {
    const key = entry.path;
    const isDir = entry.is_dir;
    const expanded = expandedDirs.has(key.replace(/\/$/, ""));
    const kids = children[key.replace(/\/$/, "")] ?? [];
    const isSelected = !isDir && selectedFile?.path === key;
    const previewable = !isDir && archiveFileKind(entry) !== "none" && archiveFileKind(entry) !== "archive";
    const icon = archiveEntryIcon(entry, expanded);

    return (
      <div key={key}>
        <div
          className={cn(
            "flex items-center gap-1.5 py-0.5 px-1 rounded text-xs transition-colors",
            isDir && "cursor-pointer hover:bg-muted/30",
            !isDir && previewable && "cursor-pointer hover:bg-muted/30",
            isSelected && "bg-muted/50 font-medium"
          )}
          style={{ paddingLeft: `${depth * 16 + 4}px` }}
          onClick={() => {
            if (isDir) toggleDir(key.replace(/\/$/, ""));
            else if (previewable) setSelectedFile(entry);
          }}
        >
          <span className="text-[11px] shrink-0">{icon}</span>
          <span className={cn("truncate flex-1", isSelected ? "text-foreground" : "text-foreground/80")}>{entry.name || entry.path}</span>
          {!isDir && (
            <span className="text-[10px] text-muted-foreground/60 shrink-0 tabular-nums">{formatBytes(entry.size)}</span>
          )}
        </div>
        {isDir && expanded && kids
          .sort((a, b) => (a.is_dir === b.is_dir ? a.name.localeCompare(b.name) : a.is_dir ? -1 : 1))
          .map(child => renderEntry(child, depth + 1))}
      </div>
    );
  }

  const fileCount = entries.filter(e => !e.is_dir).length;
  const dirCount = entries.filter(e => e.is_dir).length;
  const totalSize = entries.filter(e => !e.is_dir).reduce((s, e) => s + e.size, 0);

  return (
    <div className="h-full flex flex-col">
      <div className="px-3 py-2 border-b border-border flex items-center gap-2 shrink-0">
        <span className="text-sm">{"\uD83D\uDCE6"}</span>
        <span className="text-xs font-medium truncate flex-1">{archiveName}</span>
        <span className="text-[10px] text-muted-foreground/60">{fileCount} files, {dirCount} dirs -- {formatBytes(totalSize)}</span>
      </div>
      <div className="flex-1 flex flex-col min-h-0">
        <div className="overflow-auto p-1" style={{ height: selectedFile ? "30%" : "100%", minHeight: "80px" }}>
          {showRoots
            .sort((a, b) => (a.is_dir === b.is_dir ? a.name.localeCompare(b.name) : a.is_dir ? -1 : 1))
            .map(entry => renderEntry(entry, 0))}
        </div>
        {selectedFile && (
          <>
            <div className="border-t border-border shrink-0" />
            <div className="overflow-auto" style={{ height: "70%", minHeight: "100px" }}>
              <NestedArchiveFilePreview outerItemId={outerItemId} archivePath={archivePath} entry={selectedFile} />
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function NestedArchiveFilePreview({ outerItemId, archivePath, entry }: { outerItemId: string; archivePath: string; entry: ArchiveEntry }) {
  const kind = archiveFileKind(entry);
  const fileUrl = `${API_BASE}/drive/archive/${outerItemId}/nested-file?archive_path=${encodeURIComponent(archivePath)}&file_path=${encodeURIComponent(entry.path)}`;
  const needsBlob = kind === "image" || kind === "pdf";
  const blobUrl = useBlobUrl(needsBlob ? fileUrl : null);
  const [textContent, setTextContent] = useState<string | null>(null);
  const [textErr, setTextErr] = useState<string | null>(null);

  useEffect(() => {
    if (kind !== "text" && kind !== "code") return;
    setTextContent(null);
    setTextErr(null);
    const ctrl = new AbortController();
    apiFetch(fileUrl, { signal: ctrl.signal })
      .then(r => verboseCheck(r, "fetch")).then(r => r.text())
      .then(setTextContent)
      .catch(e => { if (e.name !== "AbortError") setTextErr(e.message); });
    return () => ctrl.abort();
  }, [fileUrl, kind]);

  if (kind === "image") {
    if (!blobUrl) return <div className="h-full flex items-center justify-center text-muted-foreground text-xs">Loading...</div>;
    return <div className="h-full flex items-center justify-center p-2"><img src={blobUrl} alt={entry.name} className="max-w-full max-h-full object-contain rounded" /></div>;
  }
  if (kind === "pdf") {
    if (!blobUrl) return <div className="h-full flex items-center justify-center text-muted-foreground text-xs">Loading PDF…</div>;
    return <iframe src={blobUrl} className="w-full h-full border-0 bg-white rounded" title={entry.name} />;
  }
  if (kind === "code" || kind === "text") {
    if (textErr) return <div className="flex items-center justify-center h-full text-destructive text-xs">{textErr}</div>;
    if (textContent === null) return <div className="flex items-center justify-center h-full text-muted-foreground text-xs">Loading...</div>;
    return <pre className="overflow-auto p-3 text-xs font-mono text-foreground/80 whitespace-pre-wrap break-words h-full">{textContent}</pre>;
  }
  return (
    <div className="h-full flex flex-col items-center justify-center gap-2 text-muted-foreground/50">
      <span className="text-2xl">{"\uD83D\uDCC4"}</span>
      <span className="text-xs">No preview for this file type</span>
      <span className="text-[10px] font-mono">{entry.name} -- {formatBytes(entry.size)}</span>
    </div>
  );
}

function ArchivePreviewPane({ itemId }: { itemId: string }) {
  const [entries, setEntries] = useState<ArchiveEntry[]>([]);
  const [archiveName, setArchiveName] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set());
  const [selectedFile, setSelectedFile] = useState<ArchiveEntry | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    setSelectedFile(null);
    apiFetch(`${API_BASE}/drive/archive/${itemId}/list`)
      .then(r => verboseCheck(r, "fetch")).then(r => r.json())
      .then(data => {
        setArchiveName(data.archive_name ?? "");
        setEntries(data.entries ?? []);
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [itemId]);

  const toggleDir = useCallback((path: string) => {
    setExpandedDirs(prev => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path); else next.add(path);
      return next;
    });
  }, []);

  if (loading) return <div className="flex items-center justify-center h-full text-muted-foreground text-sm">Loading archive...</div>;
  if (error) return <div className="flex items-center justify-center h-full text-destructive text-sm">Error: {error}</div>;

  // Build tree structure
  const roots: ArchiveEntry[] = [];
  const children: Record<string, ArchiveEntry[]> = {};
  for (const entry of entries) {
    const parts = entry.path.replace(/\/$/, "").split("/");
    if (parts.length <= 1) {
      roots.push(entry);
    } else {
      const parentPath = parts.slice(0, -1).join("/");
      if (!children[parentPath]) children[parentPath] = [];
      children[parentPath].push(entry);
    }
  }

  // If all roots share a common top-level folder, skip it
  const topDirs = roots.filter(e => e.is_dir);
  const showRoots = topDirs.length === 1 && roots.length === 1
    ? (children[topDirs[0].path.replace(/\/$/, "")] ?? [])
    : roots;

  function renderEntry(entry: ArchiveEntry, depth: number) {
    const key = entry.path;
    const isDir = entry.is_dir;
    const expanded = expandedDirs.has(key.replace(/\/$/, ""));
    const kids = children[key.replace(/\/$/, "")] ?? [];
    const isSelected = !isDir && selectedFile?.path === key;
    const previewable = !isDir && archiveFileKind(entry) !== "none";
    const icon = archiveEntryIcon(entry, expanded);

    return (
      <div key={key}>
        <div
          className={cn(
            "flex items-center gap-1.5 py-0.5 px-1 rounded text-xs transition-colors",
            isDir && "cursor-pointer hover:bg-muted/30",
            !isDir && previewable && "cursor-pointer hover:bg-muted/30",
            isSelected && "bg-muted/50 font-medium"
          )}
          style={{ paddingLeft: `${depth * 16 + 4}px` }}
          onClick={() => {
            if (isDir) toggleDir(key.replace(/\/$/, ""));
            else if (previewable) setSelectedFile(entry);
          }}
        >
          <span className="text-[11px] shrink-0">{icon}</span>
          <span className={cn("truncate flex-1", isSelected ? "text-foreground" : "text-foreground/80")}>{entry.name || entry.path}</span>
          {!isDir && (
            <span className="text-[10px] text-muted-foreground/60 shrink-0 tabular-nums">{formatBytes(entry.size)}</span>
          )}
          {isDir && kids.length > 0 && (
            <span className="text-[10px] text-muted-foreground/50 shrink-0">{expanded ? "\u25BE" : "\u25B8"}</span>
          )}
        </div>
        {isDir && expanded && kids
          .sort((a, b) => (a.is_dir === b.is_dir ? a.name.localeCompare(b.name) : a.is_dir ? -1 : 1))
          .map(child => renderEntry(child, depth + 1))}
      </div>
    );
  }

  const totalSize = entries.filter(e => !e.is_dir).reduce((s, e) => s + e.size, 0);
  const fileCount = entries.filter(e => !e.is_dir).length;
  const dirCount = entries.filter(e => e.is_dir).length;

  return (
    <div className="h-full flex flex-col">
      {/* Split: file list + preview */}
      <div className="flex-1 flex flex-col min-h-0">
        {/* Top: file tree (30%) */}
        <div className="overflow-auto p-1" style={{ height: "30%", minHeight: "80px" }}>
          <div className="px-1 py-0.5 text-[10px] text-muted-foreground/50">{fileCount} files, {dirCount} dirs — {formatBytes(totalSize)}</div>
          {showRoots
            .sort((a, b) => (a.is_dir === b.is_dir ? a.name.localeCompare(b.name) : a.is_dir ? -1 : 1))
            .map(entry => renderEntry(entry, 0))}
        </div>
        {/* Divider */}
        <div className="border-t border-border shrink-0" />
        {/* Bottom: file preview (70%) */}
        <div className="overflow-auto" style={{ height: "70%", minHeight: "100px" }}>
          {selectedFile ? (
            <ArchiveFilePreview itemId={itemId} entry={selectedFile} />
          ) : (
            <div className="h-full flex items-center justify-center text-muted-foreground/40 text-xs">
              Select a file above to preview
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function TextPreviewInline({ url }: { url: string }) {
  const [content, setContent] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    apiFetch(url, { signal: ctrl.signal })
      .then(r => verboseCheck(r, "fetch")).then(r => r.text())
      .then(setContent)
      .catch(e => { if (e.name !== "AbortError") setErr(e.message); });
    return () => ctrl.abort();
  }, [url]);

  if (err) return <div className="flex items-center justify-center text-danger text-xs p-4">{err}</div>;
  if (content === null) return <div className="flex items-center justify-center text-muted-foreground text-xs p-4">Loading...</div>;

  return (
    <pre className="overflow-auto p-3 text-xs font-mono text-foreground bg-card rounded-lg border border-border whitespace-pre-wrap break-words h-full">
      {content}
    </pre>
  );
}

function _officeColor(name: string): { icon: string; label: string; color: string } {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  if (["ppt", "pptx", "pptm", "odp"].includes(ext)) return { icon: "P", label: "PowerPoint", color: "#d04423" };
  if (["xls", "xlsx", "ods", "csv"].includes(ext)) return { icon: "X", label: "Excel", color: "#1d7044" };
  return { icon: "W", label: "Word", color: "#2b579a" };
}

function OfficePreviewPane({ itemId, name }: { itemId: string; name: string }) {
  const info = _officeColor(name);
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch(`${API_BASE}/drive/office/${itemId}/preview`)
      .then(r => verboseCheck(r, "fetch")).then(r => r.json())
      .then(d => { if (!cancelled) setData(d); })
      .catch(e => { if (!cancelled) setErr(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [itemId]);

  if (loading) return <div className="flex items-center justify-center text-muted-foreground text-xs p-4">Loading preview...</div>;
  if (err) return <div className="flex items-center justify-center text-danger text-xs p-4">{err}</div>;
  if (!data) return null;

  if (data.type === "pptx") {
    return (
      <div className="overflow-auto max-h-full p-3 space-y-4">
        {data.slides.map((s: any) => (
          <div key={s.slide} className="rounded-lg border border-border p-3 bg-card">
            <div className="text-[10px] font-semibold mb-2 opacity-60" style={{ color: info.color }}>Slide {s.slide}</div>
            {s.lines.length > 0 ? s.lines.map((l: string, i: number) => (
              <p key={i} className={cn("text-sm leading-relaxed", i === 0 ? "font-semibold text-foreground" : "text-foreground/70")}>{l}</p>
            )) : (
              <p className="text-xs text-muted-foreground/40 italic">( no text )</p>
            )}
          </div>
        ))}
      </div>
    );
  }

  if (data.type === "docx") {
    return (
      <div className="overflow-auto max-h-full p-3">
        <div className="rounded-lg border border-border p-4 bg-card space-y-2">
          {data.paragraphs.map((p: string, i: number) => (
            <p key={i} className="text-sm leading-relaxed text-foreground/80">{p}</p>
          ))}
        </div>
      </div>
    );
  }

  if (data.type === "xlsx") {
    return (
      <div className="overflow-auto max-h-full p-3 space-y-4">
        {data.sheets.map((sh: any) => (
          <div key={sh.sheet} className="rounded-lg border border-border bg-card overflow-hidden">
            <div className="px-3 py-1.5 text-[10px] font-semibold border-b border-border" style={{ color: info.color }}>{sh.sheet}</div>
            <table className="w-full text-xs border-collapse">
              <tbody>
                {sh.rows.map((row: string[], ri: number) => (
                  <tr key={ri} className={ri === 0 ? "bg-muted/30 font-semibold" : ""}>
                    {row.map((c: string, ci: number) => (
                      <td key={ci} className="px-2 py-1 border-b border-border/30 truncate max-w-[150px] text-foreground/70">{c}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    );
  }

  if (data.type === "legacy") {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-8 text-muted-foreground h-full">
        <div className="flex h-14 w-14 items-center justify-center rounded-xl text-white text-2xl font-bold" style={{ background: info.color }}>{info.icon}</div>
        <span className="text-sm font-medium text-foreground/60">{name}</span>
        <span className="text-xs text-muted-foreground/60">{data.message}</span>
      </div>
    );
  }

  return null;
}

function EmptyDetailPane({ folderName, itemCount }: { folderName: string; itemCount: number }) {
  return (
    <div className="h-full flex flex-col items-center justify-center gap-3 text-muted-foreground px-6">
      <span className="text-4xl opacity-40">{"\uD83D\uDCC1"}</span>
      <div className="text-sm font-medium text-foreground/60">{folderName || "Drive"}</div>
      <div className="text-xs text-muted-foreground/60">{itemCount} item{itemCount !== 1 ? "s" : ""}</div>
      <div className="text-xs text-muted-foreground/40 mt-2">Select a file to preview</div>
    </div>
  );
}

/** Enhanced video player with resume, skip ±30s, speed control, transcript overlay. */
function VideoPlayerEnhanced({
  src, itemId, className, autoPlay,
}: {
  src: string; itemId: string; className?: string; autoPlay?: boolean;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [showTranscript, setShowTranscript] = useState(false);
  const transcript = useTranscript(itemId);
  const { speed, cycleSpeed, applySpeed } = usePlaybackSpeed(videoRef);
  const skip = useVideoSkip(videoRef);

  useVideoResume(videoRef, itemId, !!src);

  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <div className="relative flex-1 flex items-center justify-center min-h-0">
        <video
          ref={videoRef}
          src={src}
          controls
          autoPlay={autoPlay}
          className="w-full max-h-full rounded-lg"
          onLoadedMetadata={applySpeed}
        />
        {showTranscript && transcript && (
          <div className="absolute bottom-14 left-2 right-2 bg-black/75 text-white text-xs p-2 rounded-lg max-h-28 overflow-y-auto backdrop-blur-sm">
            {transcript}
          </div>
        )}
      </div>
      <div className="flex items-center justify-center gap-1 text-[10px] shrink-0 px-1">
        <button onClick={() => skip(-30)} className="px-1.5 py-0.5 rounded bg-muted hover:bg-muted/80 transition-colors cursor-pointer" title="Rewind 30s">-30s</button>
        <button onClick={() => skip(30)} className="px-1.5 py-0.5 rounded bg-muted hover:bg-muted/80 transition-colors cursor-pointer" title="Forward 30s">+30s</button>
        <button onClick={cycleSpeed} className="px-1.5 py-0.5 rounded bg-muted hover:bg-muted/80 transition-colors cursor-pointer font-mono min-w-[2.5rem] text-center" title="Playback speed">{speed}x</button>
        {transcript && (
          <button
            onClick={() => setShowTranscript(s => !s)}
            className={cn("px-1.5 py-0.5 rounded transition-colors cursor-pointer", showTranscript ? "text-white" : "bg-muted hover:bg-muted/80")}
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

function FileDetailPane({ item, onFullscreen, version }: { item: DriveEntry; onFullscreen?: (item: DriveEntry) => void; version?: number }) {
  const kind = detectPreviewKind(item);
  const cacheBust = version ? `?v=${version}` : "";
  const previewApiUrl = item.kind === "file"
    ? ((item as DriveFile).previewUrl ?? `${API_BASE}/drive/preview/${item.id}`) + cacheBust
    : null;
  const downloadApiUrl = item.kind === "file"
    ? ((item as DriveFile).downloadUrl || `${API_BASE}/drive/download/${item.id}`) + cacheBust
    : null;
  const pdfApiUrl = (kind === "pdf" && item.kind === "file")
    ? `${API_BASE}/drive/preview/${item.id}` + cacheBust
    : null;
  // Blob URLs for binary previews (Authorization header, no ?token=)
  const blobUrl = useBlobUrl(kind === "image" ? previewApiUrl : null);
  const pdfBlobUrl = useBlobUrl(pdfApiUrl);
  // Streaming fetch with progress for large video/audio (download URL)
  const media = useMediaUrl((kind === "video" || kind === "audio") ? downloadApiUrl : null);

  const canFullscreen = kind === "image" || kind === "pdf" || kind === "video" || kind === "archive";

  if (item.uploadStatus === "uploading") {
    return (
      <div className="h-full flex flex-col bg-background border-l border-border overflow-hidden opacity-40">
        <div className="flex-1 flex flex-col items-center justify-center gap-3 text-muted-foreground">
          <span className="text-4xl">{fileIcon(item)}</span>
          <span className="text-sm font-medium text-foreground/80 text-center px-4 break-all">{item.name}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-background border-l border-border overflow-hidden">
      {/* Preview area — takes all space, no wrapper padding (each child manages its own) */}
      <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
        {kind === "image" && blobUrl && (
          <div
            className="flex-1 flex items-center justify-center p-2 min-h-0 cursor-pointer"
            onClick={() => onFullscreen?.(item)}
            title="Click to view fullscreen"
          >
            <img src={blobUrl} alt={item.name} className="max-w-full max-h-full object-contain rounded-lg" draggable={false} />
          </div>
        )}
        {kind === "image" && !blobUrl && previewApiUrl && (
          <div className="flex-1 flex items-center justify-center text-muted-foreground text-xs">Loading...</div>
        )}
        {kind === "video" && media.url && (
          <VideoPlayerEnhanced src={media.url} itemId={item.id} className="flex-1 p-2 min-h-0" />
        )}
        {kind === "video" && !media.url && !media.error && downloadApiUrl && (
          <div className="flex-1 flex flex-col items-center justify-center gap-3 text-muted-foreground">
            <span className="text-3xl opacity-60">{"\uD83C\uDFAC"}</span>
            <div className="w-48 h-1.5 rounded-full bg-muted overflow-hidden">
              <div className="h-full rounded-full transition-all duration-150" style={{ width: `${media.progress}%`, background: DRIVE_COLOR }} />
            </div>
            <span className="text-xs">{media.progress > 0 ? `Loading ${media.progress}%` : "Loading…"}</span>
          </div>
        )}
        {kind === "video" && media.error && (
          <div className="flex-1 flex items-center justify-center text-destructive text-xs">{media.error}</div>
        )}
        {kind === "audio" && media.url && (
          <div className="flex flex-col items-center gap-3 py-4 px-2">
            <span className="text-3xl">{"\uD83C\uDFB5"}</span>
            <audio src={media.url} controls className="w-full" />
          </div>
        )}
        {kind === "audio" && !media.url && !media.error && downloadApiUrl && (
          <div className="flex-1 flex flex-col items-center justify-center gap-3 text-muted-foreground">
            <span className="text-3xl opacity-60">{"\uD83C\uDFB5"}</span>
            <div className="w-48 h-1.5 rounded-full bg-muted overflow-hidden">
              <div className="h-full rounded-full transition-all duration-150" style={{ width: `${media.progress}%`, background: DRIVE_COLOR }} />
            </div>
            <span className="text-xs">{media.progress > 0 ? `Loading ${media.progress}%` : "Loading…"}</span>
          </div>
        )}
        {kind === "audio" && media.error && (
          <div className="flex-1 flex items-center justify-center text-destructive text-xs">{media.error}</div>
        )}
        {kind === "pdf" && (
          <div
            className="flex-1 min-h-0 relative cursor-pointer group"
            onClick={() => onFullscreen?.(item)}
            title="Click to view fullscreen"
          >
            {!pdfBlobUrl && (
              <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 bg-white rounded-lg">
                <div className="w-8 h-8 border-2 border-muted-foreground/30 border-t-muted-foreground rounded-full animate-spin" />
                <span className="text-xs text-muted-foreground">Loading PDF…</span>
              </div>
            )}
            {pdfBlobUrl && (
              <iframe src={pdfBlobUrl} className="w-full h-full border-0 rounded-lg bg-white pointer-events-none" title="PDF Preview" />
            )}
            <div className="absolute inset-0 rounded-lg group-hover:bg-black/5 transition-colors" />
          </div>
        )}
        {kind === "archive" && (
          <div className="flex-1 min-h-0">
            <ArchivePreviewPane itemId={item.id} />
          </div>
        )}
        {(kind === "text" || kind === "code") && previewApiUrl && (
          <div className="flex-1 min-h-0 overflow-auto p-2">
            <TextPreviewInline url={previewApiUrl} />
          </div>
        )}
        {kind === "office" && (
          <div className="flex-1 min-h-0 overflow-auto p-2">
            <OfficePreviewPane itemId={item.id} name={item.name} />
          </div>
        )}
        {kind === "unsupported" && (
          <div className="flex-1 flex flex-col items-center justify-center gap-3 py-8 text-muted-foreground">
            <span className="text-4xl">{fileIcon(item)}</span>
            <span className="text-sm font-medium text-foreground/80 text-center px-4 break-all">{item.name}</span>
            <span className="text-xs font-mono">{item.kind === "file" ? formatBytes((item as DriveFile).size) : ""}</span>
            <span className="text-[10px]">.{item.kind === "file" ? (item as DriveFile).extension : "folder"} — no preview available</span>
            {item.kind === "file" && (
              <a
                href={`${API_BASE}/drive/download/${item.id}`}
                download={item.name}
                className="mt-2 px-3 py-1.5 rounded text-xs font-medium cursor-pointer transition-colors text-muted-foreground hover:text-foreground hover:bg-muted/30"
              >
                {"\u2B07"} Download
              </a>
            )}
          </div>
        )}
      </div>
      {/* Fullscreen hint */}
    </div>
  );
}

/* Fullscreen lightbox overlay for images & PDFs */
function FullscreenPreview({ item, onClose }: { item: DriveEntry; onClose: () => void }) {
  const kind = detectPreviewKind(item);
  const previewApiUrl = item.kind === "file"
    ? (item as DriveFile).previewUrl ?? `${API_BASE}/drive/preview/${item.id}`
    : null;
  const downloadApiUrl = item.kind === "file"
    ? ((item as DriveFile).downloadUrl || `${API_BASE}/drive/download/${item.id}`)
    : null;
  const pdfApiUrl = (kind === "pdf" && item.kind === "file")
    ? `${API_BASE}/drive/preview/${item.id}`
    : null;
  const blobUrl = useBlobUrl(kind === "image" ? previewApiUrl : null);
  const pdfBlobUrl = useBlobUrl(pdfApiUrl);
  const media = useMediaUrl(kind === "video" ? downloadApiUrl : null);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  if (!previewApiUrl) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      {/* Close button */}
      <button
        onClick={onClose}
        className="absolute top-4 right-4 z-10 w-10 h-10 rounded-full flex items-center justify-center bg-black/50 text-white hover:bg-black/70 transition-colors cursor-pointer text-lg"
        title="Close (Esc)"
      >
        {"\u2715"}
      </button>

      {/* File name */}
      <div className="absolute top-4 left-4 z-10 text-white/80 text-sm font-medium truncate max-w-[60%]">
        {item.name}
      </div>

      {/* Content */}
      <div className="w-full h-full p-12" onClick={e => e.stopPropagation()}>
        {kind === "image" && blobUrl && (
          <div className="w-full h-full flex items-center justify-center" onClick={onClose}>
            <img
              src={blobUrl}
              alt={item.name}
              className="max-w-full max-h-full object-contain rounded-lg shadow-2xl"
              draggable={false}
              onClick={e => e.stopPropagation()}
            />
          </div>
        )}
        {kind === "image" && !blobUrl && (
          <div className="w-full h-full flex items-center justify-center">
            <div className="w-10 h-10 border-2 border-white/30 border-t-white rounded-full animate-spin" />
          </div>
        )}
        {kind === "pdf" && (
          <div className="w-full h-full relative">
            {!pdfBlobUrl && (
              <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 bg-white rounded-lg shadow-2xl">
                <div className="w-10 h-10 border-2 border-muted-foreground/30 border-t-muted-foreground rounded-full animate-spin" />
                <span className="text-sm text-muted-foreground">Loading PDF…</span>
              </div>
            )}
            {pdfBlobUrl && (
              <iframe
                src={pdfBlobUrl}
                className="w-full h-full border-0 rounded-lg bg-white shadow-2xl"
                title={`PDF: ${item.name}`}
              />
            )}
          </div>
        )}
        {kind === "video" && media.url && (
          <VideoPlayerEnhanced src={media.url} itemId={item.id} autoPlay className="w-full h-full" />
        )}
        {kind === "video" && !media.url && !media.error && (
          <div className="w-full h-full flex flex-col items-center justify-center gap-4">
            <div className="w-64 h-2 rounded-full bg-white/20 overflow-hidden">
              <div className="h-full rounded-full bg-white/80 transition-all duration-150" style={{ width: `${media.progress}%` }} />
            </div>
            <span className="text-white/60 text-sm">{media.progress > 0 ? `Loading ${media.progress}%` : "Loading…"}</span>
          </div>
        )}
        {kind === "archive" && (
          <div className="w-full max-w-2xl mx-auto h-full rounded-lg shadow-2xl overflow-hidden" style={{ background: "var(--color-bg, #1a1a2e)" }}>
            <ArchivePreviewPane itemId={item.id} />
          </div>
        )}
      </div>
    </div>
  );
}

// =======================================
//  DRIVE PANEL — MAIN EXPORT
// =======================================

interface DrivePanelProps {
  activeTab: number;
  tabs: string[];
}

const TAB_MAP: Record<number, DriveViewTab> = {
  0: "files",
  1: "shared",
  2: "recent",
  3: "trash",
  4: "albums",
};

export default function DrivePanel({ activeTab, tabs: _tabs }: DrivePanelProps) {
  const driveTab = TAB_MAP[activeTab] ?? "files";
  const drive = useDrive({ initialTab: driveTab });
  const [selectedItem, setSelectedItem] = useState<DriveEntry | null>(null);
  const [shareTarget, setShareTarget] = useState<DriveEntry | null>(null);
  const [showNewFolder, setShowNewFolder] = useState(false);
  const [renamingFolder, setRenamingFolder] = useState(false);
  const [renameFolderName, setRenameFolderName] = useState("");
  const [newFolderName, setNewFolderName] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dropRef = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState(false);

  // -- New file creation state machine --
  const [newFilePhase, setNewFilePhase] = useState<NewFilePhase>("idle");
  const [newFileType, setNewFileType] = useState("");
  const [newFileName, setNewFileName] = useState("");
  const [newFileContent, setNewFileContent] = useState("");
  const [newFileTmpId, setNewFileTmpId] = useState("");
  const [editingFileId, setEditingFileId] = useState<string | null>(null);
  const [previewVersion, setPreviewVersion] = useState(0);
  const newFileContentRef = useRef(newFileContent);
  newFileContentRef.current = newFileContent;

  // -- New states for Drive features integration --
  const [viewMode, setViewMode] = useState<"list" | "gallery">("list");
  const [commanderOpen, setCommanderOpen] = useState(false);
  const commanderRef = useRef<CommanderActions>(null);
  const [rightFolderId, setRightFolderId] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState<string | null>(null);
  const [selectionMode, setSelectionMode] = useState(false);
  const [typeFilter, setTypeFilter] = useState<string | null>(null);
  const [siblingFolders, setSiblingFolders] = useState<{ id: string; name: string }[]>([]);
  const [hoveredFolder, setHoveredFolder] = useState<string | null>(null);
  const navCooldownRef = useRef(0);
  const [siblingIndex, setSiblingIndex] = useState(-1);
  const [copyTarget, setCopyTarget] = useState<string[] | null>(null);
  const [moveTarget, setMoveTarget] = useState<string[] | null>(null);
  const [versionTarget, setVersionTarget] = useState<string | null>(null);
  const [fullscreenItem, setFullscreenItem] = useState<DriveEntry | null>(null);
  const [fullscreenEdit, setFullscreenEdit] = useState(false);
  const download = useDownload();

  // BUG-2 FIX: useEffect for side-effect (sync tab prop with hook)
  useEffect(() => {
    if (driveTab !== drive.tab) drive.setTab(driveTab);
  }, [driveTab, drive.tab, drive.setTab]);

  // -- Sibling folder navigation (← →) --
  useEffect(() => {
    if (!drive.currentFolderId) {
      setSiblingFolders([]);
      setSiblingIndex(-1);
      return;
    }
    const parentId = drive.breadcrumbs.length >= 2
      ? drive.breadcrumbs[drive.breadcrumbs.length - 2].id
      : null;
    const params = new URLSearchParams();
    if (parentId) params.set("parent_id", parentId);
    params.set("view", "files");
    params.set("sort", drive.sort.field);
    params.set("dir", drive.sort.dir);
    apiFetch(`${API_BASE}/drive/list?${params}`)
      .then(res => res.ok ? res.json() : null)
      .then(data => {
        if (!data) return;
        const folders = data.items
          .filter((i: { kind: string }) => i.kind === "folder")
          .map((f: { id: string; name: string; size?: number; updatedAt?: string }) => ({ id: f.id, name: f.name, size: f.size ?? 0, updatedAt: f.updatedAt ?? f.updated_at ?? "" }));
        // Sort client-side to match the visual order in sortedItems (localeCompare)
        const sf = drive.sort.field;
        const sd = drive.sort.dir;
        folders.sort((a: { name: string; size: number; updatedAt: string }, b: { name: string; size: number; updatedAt: string }) => {
          let cmp = 0;
          if (sf === "name") cmp = a.name.localeCompare(b.name);
          else if (sf === "size") cmp = (a.size || 0) - (b.size || 0);
          else cmp = new Date(a.updatedAt || 0).getTime() - new Date(b.updatedAt || 0).getTime();
          return sd === "asc" ? cmp : -cmp;
        });
        setSiblingFolders(folders);
        setSiblingIndex(folders.findIndex((f: { id: string }) => f.id === drive.currentFolderId));
      })
      .catch(() => {});
  }, [drive.currentFolderId, drive.breadcrumbs, drive.sort.field, drive.sort.dir]);

  // -- Drag & drop --
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!dropRef.current?.contains(e.relatedTarget as Node)) {
      setDragging(false);
    }
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(false);
    if (e.dataTransfer.files.length > 0) {
      drive.uploadFiles(e.dataTransfer.files);
    }
  }, [drive.uploadFiles]);

  // -- Sort handler --
  const handleSort = useCallback((field: DriveSortField) => {
    drive.setSort({
      field,
      dir: drive.sort.field === field && drive.sort.dir === "asc" ? "desc" : "asc",
    });
  }, [drive.sort, drive.setSort]);

  // -- Create folder --
  const handleCreateFolder = useCallback(async () => {
    if (!newFolderName.trim()) return;
    await drive.createFolder(newFolderName.trim());
    setNewFolderName("");
    setShowNewFolder(false);
  }, [newFolderName, drive.createFolder]);

  const handleRenameFolder = useCallback(async () => {
    const trimmed = renameFolderName.trim();
    if (!trimmed) return;
    const r = commanderRef.current;
    const rd = r?.rightDrive;
    const folderId = rd?.currentFolderId || (rd && rd.breadcrumbs.length > 0 ? rd.breadcrumbs[rd.breadcrumbs.length - 1].id : null);
    if (!folderId || !rd) return;
    const oldName = rd.breadcrumbs.length > 0 ? rd.breadcrumbs[rd.breadcrumbs.length - 1].name : "";
    if (trimmed === oldName) { setRenamingFolder(false); setRenameFolderName(""); return; }
    try {
      await rd.renameItem(folderId, trimmed);
      log.info("drive", `Renamed folder: ${oldName} -> ${trimmed}`);
    } catch (e) { log.error("drive", `Rename failed: ${(e as Error).message}`); }
    setRenamingFolder(false);
    setRenameFolderName("");
  }, [renameFolderName]);

  // -- New file: autosave effect --
  useEffect(() => {
    if (newFilePhase !== "editing" || !newFileTmpId) return;
    const iv = setInterval(() => {
      apiFetch(`${FILES_API}/autosave/${newFileTmpId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: newFileContentRef.current }),
      }).catch(() => {});
    }, 5000);
    return () => clearInterval(iv);
  }, [newFilePhase, newFileTmpId]);

  // -- New file: handlers --
  const handleNewFileClick = useCallback(() => setNewFilePhase("pick-type"), []);

  const handlePickFileType = useCallback((filename: string) => {
    const dot = filename.lastIndexOf(".");
    const ext = dot > 0 ? filename.slice(dot + 1).toLowerCase() : "txt";
    setNewFileType(ext);
    setNewFileName(filename);
    setNewFileContent("");
    setEditingFileId(null);
    setNewFileTmpId(crypto.randomUUID());
    setNewFilePhase("editing");
  }, []);

  const handleEditorSave = useCallback(async () => {
    if (editingFileId) {
      // Updating an existing file
      const format = newFileType === "pdf" ? "pdf" : "auto";
      try {
        const res = await apiFetch(`${FILES_API}/write/${editingFileId}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content: newFileContent, format }),
        });
        await verboseCheck(res, "fetch");
      } catch (err) {
        console.error("Failed to update file:", err);
      }
    } else {
      // New file — save with the filename from the picker
      await handleSaveNewFile(newFileName);
      return; // handleSaveNewFile already resets state
    }
    // Cleanup
    if (newFileTmpId) {
      apiFetch(`${FILES_API}/autosave/${newFileTmpId}`, { method: "DELETE" }).catch(() => {});
    }
    setNewFilePhase("idle");
    setNewFileType("");
    setNewFileName("");
    setNewFileContent("");
    setNewFileTmpId("");
    setEditingFileId(null);
    setFullscreenEdit(false);
    setPreviewVersion(v => v + 1);
    drive.refresh();
  }, [editingFileId, newFileType, newFileContent, newFileName, newFileTmpId, drive.refresh]);

  const handleEditorCancel = useCallback(async () => {
    if (newFileTmpId) {
      apiFetch(`${FILES_API}/autosave/${newFileTmpId}`, { method: "DELETE" }).catch(() => {});
    }
    setNewFilePhase("idle");
    setNewFileType("");
    setNewFileName("");
    setNewFileContent("");
    setNewFileTmpId("");
    setEditingFileId(null);
    setFullscreenEdit(false);
  }, [newFileTmpId]);

  const handleSaveNewFile = useCallback(async (name: string) => {
    const format = newFileType === "pdf" ? "pdf" : "auto";
    const parentFolderId = drive.currentFolderId ?? "root";
    try {
      const res = await apiFetch(`${FILES_API}/write`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, content: newFileContent, parent_folder_id: parentFolderId, format }),
      });
      await verboseCheck(res, "fetch");
    } catch (err) {
      console.error("Failed to save file:", err);
    }
    // Cleanup autosave
    if (newFileTmpId) {
      apiFetch(`${FILES_API}/autosave/${newFileTmpId}`, { method: "DELETE" }).catch(() => {});
    }
    setNewFilePhase("idle");
    setNewFileType("");
    setNewFileName("");
    setNewFileContent("");
    setNewFileTmpId("");
    setEditingFileId(null);
    drive.refresh();
  }, [newFileType, newFileContent, newFileTmpId, drive.currentFolderId, drive.refresh]);

  // -- Edit existing file handler --
  const handleEditFile = useCallback(async (item: DriveEntry) => {
    try {
      const res = await apiFetch(`${FILES_API}/read/${item.id}`);
      await verboseCheck(res, "fetch");
      const data = await res.json();
      const ext = (item as DriveFile).extension?.toLowerCase() ?? "txt";
      setNewFileContent(data.content ?? "");
      setNewFileType(ext);
      setNewFileName(item.name);
      setEditingFileId(item.id);
      setNewFileTmpId(crypto.randomUUID());
      setNewFilePhase("editing");
    } catch (err) {
      console.error("Failed to read file:", err);
    }
  }, []);

  // -- Commander: get source IDs (checkboxes or clicked item) --
  const getCommanderSourceIds = useCallback((): string[] => {
    if (drive.selectedIds.size > 0) return [...drive.selectedIds];
    if (selectedItem) return [selectedItem.id];
    return [];
  }, [drive.selectedIds, selectedItem]);

  // -- Click handler --
  const handleItemClick = useCallback((item: DriveEntry) => {
    if (editingFileId) return; // block clicks while editing
    if (selectionMode || drive.selectedIds.size > 0) {
      if (item.kind === "file") drive.toggleSelect(item.id);
      return;
    }
    if (item.kind === "folder") {
      drive.navigateTo(item.id);
    } else {
      setSelectedItem(prev => prev?.id === item.id ? null : item);
    }
  }, [drive.navigateTo, drive.toggleSelect, drive.selectedIds.size, editingFileId, selectionMode]);

  // -- Sorted items (pure derivation — useMemo is correct here) --
  const sortedItems = useMemo(() => {
    const folders = drive.items.filter(i => i.kind === "folder");
    const files = drive.items.filter(i => i.kind === "file");

    const compare = (a: DriveEntry, b: DriveEntry) => {
      const { field, dir } = drive.sort;
      let cmp = 0;
      if (field === "name") cmp = a.name.localeCompare(b.name);
      else if (field === "size") cmp = a.size - b.size;
      else cmp = new Date(a.updatedAt).getTime() - new Date(b.updatedAt).getTime();
      return dir === "asc" ? cmp : -cmp;
    };

    return [...folders.sort(compare), ...files.sort(compare)];
  }, [drive.items, drive.sort]);

  // Top 5 file type badges for filter chips
  const topTypeBadges = useMemo(() => {
    const files = sortedItems.filter(i => i.kind === "file");
    const counts = new Map<string, { label: string; color: string; count: number }>();
    for (const f of files) {
      const b = fileTypeBadge(f);
      const existing = counts.get(b.label);
      if (existing) existing.count++;
      else counts.set(b.label, { label: b.label, color: b.color, count: 1 });
    }
    return [...counts.values()].sort((a, b) => b.count - a.count).slice(0, 5);
  }, [sortedItems]);

  // Reset filter when navigating to a different folder
  useEffect(() => { setTypeFilter(null); }, [drive.currentFolderId]);

  // Filtered file list (respects typeFilter)
  const filteredFiles = useMemo(() => {
    const files = sortedItems.filter(i => i.kind === "file");
    if (!typeFilter) return files;
    return files.filter(i => fileTypeBadge(i).label === typeFilter);
  }, [sortedItems, typeFilter]);

  // -- Drag-to-select (must be AFTER sortedItems) --
  // All mutable state in refs to avoid stale closures in rAF / event listeners.
  const dragRef = useRef<{ active: boolean; startIdx: number; prevIdx: number; baseSelection: Set<string>; mode: "select" | "deselect"; handled: boolean; dragType: "file" | "folder" }>({
    active: false, startIdx: -1, prevIdx: -1, baseSelection: new Set(), mode: "select", handled: false, dragType: "file",
  });
  const fileListRef = useRef<HTMLDivElement>(null);
  const folderListRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const autoScrollRef = useRef<{ raf: number; lastY: number }>({ raf: 0, lastY: 0 });

  // Refs that always mirror latest values — so rAF/listeners never have stale closures
  const sortedItemsRef = useRef(sortedItems);
  sortedItemsRef.current = sortedItems;
  const filteredFilesRef = useRef(filteredFiles);
  filteredFilesRef.current = filteredFiles;
  const driveRef = useRef(drive);
  driveRef.current = drive;

  const getFileIdxFromY = useCallback((y: number): number => {
    const container = fileListRef.current;
    if (!container) return -1;
    const rows = container.querySelectorAll<HTMLElement>("[data-file-idx]");
    if (rows.length === 0) return -1;
    for (let i = 0; i < rows.length; i++) {
      const rect = rows[i].getBoundingClientRect();
      if (y >= rect.top && y <= rect.bottom) return i;
    }
    const firstRect = rows[0].getBoundingClientRect();
    if (y < firstRect.top) return 0;
    const lastRect = rows[rows.length - 1].getBoundingClientRect();
    if (y > lastRect.bottom) return rows.length - 1;
    return -1;
  }, []);

  // Apply selection range — reads drive from ref, no stale closure
  const applySelection = useCallback((startIdx: number, endIdx: number) => {
    const d = dragRef.current;
    const files = filteredFilesRef.current;
    const lo = Math.min(startIdx, endIdx);
    const hi = Math.max(startIdx, endIdx);
    const next = new Set(d.baseSelection);
    if (d.mode === "select") {
      for (let i = lo; i <= hi; i++) {
        if (i >= 0 && i < files.length) next.add(files[i].id);
      }
      for (let i = 0; i < files.length; i++) {
        if ((i < lo || i > hi) && !d.baseSelection.has(files[i].id)) next.delete(files[i].id);
      }
    } else {
      for (let i = lo; i <= hi; i++) {
        if (i >= 0 && i < files.length) next.delete(files[i].id);
      }
      for (let i = 0; i < files.length; i++) {
        if ((i < lo || i > hi) && d.baseSelection.has(files[i].id)) next.add(files[i].id);
      }
    }
    driveRef.current.clearSelection();
    next.forEach(id => driveRef.current.toggleSelect(id));
  }, []); // stable — reads everything from refs

  const getFolderIdxFromPoint = useCallback((x: number, y: number): number => {
    const container = folderListRef.current;
    if (!container) return -1;
    const cards = container.querySelectorAll<HTMLElement>("[data-folder-idx]");
    for (let i = 0; i < cards.length; i++) {
      const rect = cards[i].getBoundingClientRect();
      if (x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom) return i;
    }
    return -1;
  }, []);

  const applyFolderSelection = useCallback((startIdx: number, endIdx: number) => {
    const d = dragRef.current;
    const folders = sortedItemsRef.current.filter(i => i.kind === "folder");
    const lo = Math.min(startIdx, endIdx);
    const hi = Math.max(startIdx, endIdx);
    const next = new Set(d.baseSelection);
    if (d.mode === "select") {
      for (let i = lo; i <= hi; i++) { if (i >= 0 && i < folders.length) next.add(folders[i].id); }
      for (let i = 0; i < folders.length; i++) { if ((i < lo || i > hi) && !d.baseSelection.has(folders[i].id)) next.delete(folders[i].id); }
    } else {
      for (let i = lo; i <= hi; i++) { if (i >= 0 && i < folders.length) next.delete(folders[i].id); }
      for (let i = 0; i < folders.length; i++) { if ((i < lo || i > hi) && d.baseSelection.has(folders[i].id)) next.add(folders[i].id); }
    }
    driveRef.current.clearSelection();
    next.forEach(id => driveRef.current.toggleSelect(id));
  }, []);

  // rAF tick — stable function, reads all data from refs
  const EDGE_ZONE = 40;
  const MAX_SPEED = 14;

  const tickRef = useRef<() => void>();
  tickRef.current = () => {
    const sc = scrollContainerRef.current;
    const as = autoScrollRef.current;
    const d = dragRef.current;
    if (!sc || !d.active) { as.raf = 0; return; }

    const rect = sc.getBoundingClientRect();
    let speed = 0;
    if (as.lastY >= rect.bottom) speed = MAX_SPEED;
    else if (as.lastY <= rect.top) speed = -MAX_SPEED;
    else if (as.lastY > rect.bottom - EDGE_ZONE) {
      speed = Math.ceil(MAX_SPEED * (1 - (rect.bottom - as.lastY) / EDGE_ZONE));
    } else if (as.lastY < rect.top + EDGE_ZONE) {
      speed = -Math.ceil(MAX_SPEED * (1 - (as.lastY - rect.top) / EDGE_ZONE));
    }

    if (speed !== 0) {
      sc.scrollTop += speed;
    }

    // Always update selection (scroll may have revealed new rows)
    const idx = getFileIdxFromY(as.lastY);
    if (idx !== -1 && idx !== d.prevIdx) {
      d.prevIdx = idx;
      applySelection(d.startIdx, idx);
    }

    as.raf = requestAnimationFrame(() => tickRef.current!());
  };

  // Stable mouse listeners — mounted once, never re-created
  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      const d = dragRef.current;
      if (!d.active) return;
      autoScrollRef.current.lastY = e.clientY;

      if (d.dragType === "folder") {
        const idx = getFolderIdxFromPoint(e.clientX, e.clientY);
        if (idx !== -1 && idx !== d.prevIdx) {
          d.prevIdx = idx;
          applyFolderSelection(d.startIdx, idx);
        }
      } else {
        const idx = getFileIdxFromY(e.clientY);
        if (idx !== -1 && idx !== d.prevIdx) {
          d.prevIdx = idx;
          applySelection(d.startIdx, idx);
        }
      }
    };

    const onMouseUp = () => {
      dragRef.current.active = false;
      const as = autoScrollRef.current;
      if (as.raf) { cancelAnimationFrame(as.raf); as.raf = 0; }
    };

    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
    return () => {
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
      const as = autoScrollRef.current;
      if (as.raf) { cancelAnimationFrame(as.raf); as.raf = 0; }
    };
  }, [getFileIdxFromY, getFolderIdxFromPoint, applySelection, applyFolderSelection]); // all stable ([] deps)

  const handleFileDragStart = useCallback((idx: number, startY: number) => {
    const files = filteredFilesRef.current;
    const clickedId = idx >= 0 && idx < files.length ? files[idx].id : null;
    const wasSelected = clickedId ? driveRef.current.selectedIds.has(clickedId) : false;
    dragRef.current = {
      active: true,
      startIdx: idx,
      prevIdx: idx,
      baseSelection: new Set(driveRef.current.selectedIds),
      mode: wasSelected ? "deselect" : "select",
      handled: true,
      dragType: "file",
    };
    if (clickedId) {
      if (wasSelected) {
        driveRef.current.toggleSelect(clickedId);
        dragRef.current.baseSelection = new Set([...driveRef.current.selectedIds].filter(id => id !== clickedId));
      } else {
        driveRef.current.toggleSelect(clickedId);
        dragRef.current.baseSelection = new Set([...driveRef.current.selectedIds, clickedId]);
      }
    }
    // Start rAF loop with correct initial cursor position
    const as = autoScrollRef.current;
    as.lastY = startY;
    if (!as.raf) as.raf = requestAnimationFrame(() => tickRef.current!());
  }, []); // stable — reads from refs

  const handleFolderDragStart = useCallback((idx: number) => {
    const folders = sortedItemsRef.current.filter(i => i.kind === "folder");
    const clickedId = idx >= 0 && idx < folders.length ? folders[idx].id : null;
    const wasSelected = clickedId ? driveRef.current.selectedIds.has(clickedId) : false;
    dragRef.current = {
      active: true, startIdx: idx, prevIdx: idx,
      baseSelection: new Set(driveRef.current.selectedIds),
      mode: wasSelected ? "deselect" : "select",
      handled: true, dragType: "folder",
    };
    if (clickedId) {
      driveRef.current.toggleSelect(clickedId);
      if (wasSelected) {
        dragRef.current.baseSelection = new Set([...driveRef.current.selectedIds].filter(id => id !== clickedId));
      } else {
        dragRef.current.baseSelection = new Set([...driveRef.current.selectedIds, clickedId]);
      }
    }
  }, []); // stable — reads from refs

  // -- Clear selection on folder navigation or tab change --
  useEffect(() => {
    setSelectedItem(null);
    setSelectionMode(false);
    drive.clearSelection();
  }, [drive.currentFolderId, driveTab]);

  // -- Close commander on tab change --
  useEffect(() => {
    setCommanderOpen(false);
  }, [driveTab]);

  // -- Sync selectedItem with drive.items (handles delete/rename/move) --
  useEffect(() => {
    if (!selectedItem) return;
    const updated = drive.items.find(i => i.id === selectedItem.id);
    if (!updated) setSelectedItem(null);
    else if (updated !== selectedItem) setSelectedItem(updated);
  }, [drive.items, selectedItem]);

  const isTrash = driveTab === "trash";
  const showSplitPane = (selectedItem !== null || commanderOpen) && !(driveTab === "albums" || (driveTab === "files" && viewMode === "gallery"));

  return (
    <div
      ref={dropRef}
      className={cn(
        "flex-1 min-h-0 flex flex-col bg-background relative overflow-hidden",
        dragging && "ring-2 ring-inset"
      )}
      style={dragging ? { "--tw-ring-color": driveAlpha(0.5) } as React.CSSProperties : undefined}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* Share dialog */}
      {shareTarget && (
        <ShareDialog
          item={shareTarget}
          onClose={() => setShareTarget(null)}
          onShare={drive.shareItem}
          onGetShares={drive.getShareInfo}
          onRevoke={drive.revokeShare}
        />
      )}

      {/* Drag overlay */}
      {dragging && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm">
          <div className="flex flex-col items-center gap-2">
            <span className="text-5xl">\uD83D\uDCE4</span>
            <span className="text-base font-medium" style={{ color: DRIVE_COLOR }}>Drop files to upload</span>
          </div>
        </div>
      )}

      {/* Toolbar — split 30/70 aligned with content pane */}
      <div className="h-10 border-b border-border flex items-center shrink-0">
        {/* Left: breadcrumbs + buttons */}
        <div
          className="h-full px-3 flex items-center gap-2 shrink-0"
          style={{ width: showSplitPane ? "30%" : "100%", transition: "width 0.2s ease" }}
        >
          <Breadcrumbs
            crumbs={drive.breadcrumbs}
            onNavigate={drive.navigateTo}
            hoverName={hoveredFolder}
            siblingIndex={siblingIndex}
            siblingCount={siblingFolders.length}
            onPrev={() => { if (siblingIndex > 0) drive.navigateTo(siblingFolders[siblingIndex - 1].id); }}
            onNext={() => { if (siblingIndex < siblingFolders.length - 1) drive.navigateTo(siblingFolders[siblingIndex + 1].id); }}
          />
          {showNewFolder && (
            <span
              className="inline-flex items-center"
              onBlur={e => { if (!e.currentTarget.contains(e.relatedTarget as Node)) { setShowNewFolder(false); setNewFolderName(""); } }}
            >
              <span className="text-xs text-muted-foreground mx-1">/</span>
              <input
                value={newFolderName}
                onChange={e => setNewFolderName(e.target.value)}
                onKeyDown={e => {
                  if (e.key === "Enter") handleCreateFolder();
                  if (e.key === "Escape") { setShowNewFolder(false); setNewFolderName(""); }
                }}
                placeholder="folder name"
                className="text-xs font-medium bg-transparent text-foreground outline-none min-w-[120px]"
                style={{ borderBottom: `1px solid ${DRIVE_COLOR}`, width: `${Math.max(newFolderName.length, 12)}ch` }}
                autoFocus
              />
              <button onClick={handleCreateFolder} className="text-[10px] font-medium cursor-pointer ml-3" style={{ color: DRIVE_COLOR }}>Save</button>
              <button onClick={() => { setShowNewFolder(false); setNewFolderName(""); }} className="w-5 h-5 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors cursor-pointer shrink-0 text-[10px] ml-1" title="Cancel">{"\u2715"}</button>
            </span>
          )}
          <div className="flex-1" />

          {!isTrash && (
            <>
              <button
                onClick={handleNewFileClick}
                className="px-2 py-1 rounded text-[11px] font-medium cursor-pointer transition-colors text-muted-foreground hover:text-foreground hover:bg-muted/50 shrink-0 whitespace-nowrap"
                title="New file"
              >
                + File
              </button>
              <button
                onClick={() => setShowNewFolder(true)}
                className="px-2 py-1 rounded text-[11px] font-medium cursor-pointer transition-colors text-muted-foreground hover:text-foreground hover:bg-muted/50 shrink-0 whitespace-nowrap"
                title="New folder"
              >
                + Folder
              </button>
              <button
                onClick={() => fileInputRef.current?.click()}
                className="px-2 py-1 rounded text-[11px] font-medium cursor-pointer transition-colors text-muted-foreground hover:text-foreground hover:bg-muted/50 shrink-0 whitespace-nowrap"
                title="Upload files"
              >
                Upload
              </button>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                className="hidden"
                onChange={e => {
                  if (e.target.files && e.target.files.length > 0) {
                    drive.uploadFiles(e.target.files);
                    e.target.value = "";
                  }
                }}
              />
              <button
                onClick={() => {
                  if (commanderOpen) setCommanderOpen(false);
                  else { setSelectedItem(null); setCommanderOpen(true); }
                }}
                className={cn(
                  "px-2 py-1 rounded text-[11px] font-medium cursor-pointer transition-colors shrink-0 whitespace-nowrap",
                  commanderOpen
                    ? "border"
                    : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
                )}
                style={commanderOpen ? { background: driveAlpha(0.09), borderColor: driveAlpha(0.25), color: DRIVE_COLOR } : undefined}
                title="Commander (dual-pane file manager)"
              >
                Commander{commanderOpen ? " \u2715" : ""}
              </button>
            </>
          )}

          {isTrash && drive.items.length > 0 && (
            <button
              onClick={() => drive.emptyTrash()}
              className="px-2 py-1 rounded text-[11px] font-medium cursor-pointer transition-colors border border-danger/40 text-danger bg-danger/10 hover:bg-danger/20"
            >
              Empty Trash ({drive.totalItems})
            </button>
          )}

          {/* List / Gallery toggle (only on files tab) */}
          {driveTab === "files" && !showSplitPane && (
            <button
              onClick={() => setViewMode(viewMode === "gallery" ? "list" : "gallery")}
              className="w-6 h-6 flex items-center justify-center text-xs cursor-pointer transition-colors rounded border border-border"
              style={viewMode === "gallery" ? { background: driveAlpha(0.15), color: DRIVE_COLOR } : { color: "var(--muted-foreground)" }}
              title={viewMode === "gallery" ? "Gallery ON" : "Gallery OFF"}
            >
              {"\u25A6"}
            </button>
          )}

          {!showSplitPane && (
            <button
              onClick={drive.refresh}
              className="w-6 h-6 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors cursor-pointer text-xs"
              title="Refresh"
            >
              {"\u21BB"}
            </button>
          )}
        </div>

        {/* Right: commander header or file info + actions */}
        {showSplitPane && selectedItem && !commanderOpen && !editingFileId && (
          <div
            className="h-full px-3 flex items-center gap-1 border-l border-border overflow-hidden"
            style={{ width: "70%", transition: "width 0.2s ease" }}
          >
            <span className="text-xs font-medium truncate text-foreground mr-1">{selectedItem.name}</span>
            <span className="text-[10px] text-muted-foreground font-mono shrink-0 mr-1">
              {selectedItem.uploadStatus === "uploading" ? "--" : formatBytes(selectedItem.size)}
            </span>
            {selectedItem.uploadStatus !== "uploading" && (<>
            <span className="w-px h-4 bg-border mx-1 shrink-0" />
            <button
              onClick={() => {
                if (selectedItem.kind === "folder") download.downloadFolderZip(selectedItem.id);
                else download.downloadFile(selectedItem.id);
              }}
              className="px-1.5 py-1 rounded text-[11px] font-medium cursor-pointer transition-colors text-muted-foreground hover:text-foreground hover:bg-muted/30 whitespace-nowrap"
            >
              Download
            </button>
            {selectedItem && isEditable(selectedItem) && (
              <button
                onClick={() => handleEditFile(selectedItem)}
                className="px-1.5 py-1 rounded text-[11px] font-medium cursor-pointer transition-colors text-muted-foreground hover:text-foreground hover:bg-muted/30 whitespace-nowrap"
              >
                Edit
              </button>
            )}
            <button onClick={() => drive.toggleStar(selectedItem.id)} className="px-1.5 py-1 rounded text-[11px] font-medium cursor-pointer transition-colors text-muted-foreground hover:text-foreground hover:bg-muted/30 whitespace-nowrap">
              {selectedItem.starred ? "\u2605" : "\u2606"}
            </button>
            <button onClick={() => setShareTarget(selectedItem)} className="px-1.5 py-1 rounded text-[11px] font-medium cursor-pointer transition-colors text-muted-foreground hover:text-foreground hover:bg-muted/30 whitespace-nowrap">
              Share
            </button>
            <button onClick={() => { setSelectedItem(null); setCommanderOpen(true); }} className="px-1.5 py-1 rounded text-[11px] font-medium cursor-pointer transition-colors text-muted-foreground hover:text-foreground hover:bg-muted/30 whitespace-nowrap">
              Commander
            </button>
            {selectedItem.kind === "file" && (
              <button onClick={() => setVersionTarget(selectedItem.id)} className="px-1.5 py-1 rounded text-[11px] font-medium cursor-pointer transition-colors text-muted-foreground hover:text-foreground hover:bg-muted/30 whitespace-nowrap">
                Versions
              </button>
            )}
            <span className="w-px h-4 bg-border mx-1 shrink-0" />
            <button
              onClick={() => { drive.deleteItems([selectedItem.id]); log.info("drive", `Trashed: ${selectedItem.name}`); setSelectedItem(null); }}
              className="px-1.5 py-1 rounded text-[11px] font-medium cursor-pointer transition-colors text-muted-foreground hover:text-foreground hover:bg-muted/30 whitespace-nowrap"
            >
              Delete
            </button>
            </>)}
            <div className="flex-1" />
            {(() => { const k = detectPreviewKind(selectedItem); return (k === "image" || k === "pdf" || k === "video" || k === "archive") ? (
              <button onClick={() => setFullscreenItem(selectedItem)} className="px-1.5 py-1 rounded text-[11px] font-medium cursor-pointer transition-colors text-muted-foreground hover:text-foreground hover:bg-muted/30 whitespace-nowrap">Fullscreen</button>
            ) : null; })()}
            <button
              onClick={() => setSelectedItem(null)}
              className="w-6 h-6 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors cursor-pointer shrink-0"
              title="Close preview"
            >
              {"\u2715"}
            </button>
          </div>
        )}
        {showSplitPane && editingFileId && (
          <div
            className="h-full px-3 flex items-center gap-2 border-l border-border overflow-hidden"
            style={{ width: "70%", transition: "width 0.2s ease" }}
          >
            <span className="text-[11px] font-medium text-muted-foreground truncate">{newFileName}</span>
            <button onClick={handleEditorSave} className="px-1.5 py-1 rounded text-[11px] font-medium cursor-pointer ml-1" style={{ color: DRIVE_COLOR }}>Save</button>
            <button onClick={handleEditorCancel} className="w-5 h-5 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors cursor-pointer shrink-0 text-[10px] ml-1" title="Cancel">{"\u2715"}</button>
            <div className="flex-1" />
            <button onClick={() => setFullscreenEdit(true)} className="px-1.5 py-1 rounded text-[11px] font-medium cursor-pointer transition-colors text-muted-foreground hover:text-foreground hover:bg-muted/30 whitespace-nowrap" title="Edit fullscreen">Fullscreen</button>
          </div>
        )}
      </div>

      {/* Selection bar + sort — split aligned with content */}
      <div className="h-8 border-b border-border/50 flex items-center bg-card/30 shrink-0">
        <div
          className="h-full px-4 flex items-center gap-2"
          style={{ width: showSplitPane ? "30%" : "100%", transition: "width 0.2s ease" }}
        >
          {drive.selectedIds.size > 0 ? (
            <>
              <span className="text-xs text-muted-foreground font-mono">
                {drive.selectedIds.size} selected
              </span>
              {!isTrash && (
                <button
                  onClick={() => download.downloadBatch([...drive.selectedIds])}
                  className="text-xs hover:underline cursor-pointer text-foreground"
                >
                  Download
                </button>
              )}
              <button
                onClick={() => { const ids = [...drive.selectedIds]; if (isTrash) { drive.purgeItems(ids); log.info("drive", `Purged ${ids.length} item(s)`); } else { drive.deleteItems(ids); log.info("drive", `Trashed ${ids.length} item(s)`); } }}
                className="text-xs text-danger hover:underline cursor-pointer"
              >
                {isTrash ? "Vider Trash" : "Trash"}
              </button>
              <button
                onClick={() => { drive.clearSelection(); setSelectionMode(false); }}
                className="text-xs text-muted-foreground hover:text-foreground cursor-pointer"
              >
                Clear
              </button>
            </>
          ) : (
            <button
              onClick={() => setSelectionMode(m => !m)}
              className="text-xs text-muted-foreground hover:text-foreground cursor-pointer"
              style={selectionMode ? { color: DRIVE_COLOR } : undefined}
            >
              {selectionMode ? "Annuler" : "Sélectionner"}
            </button>
          )}
          {/* Type filter chips — always visible when >= 2 types */}
          {topTypeBadges.length >= 2 && (
            <div className="flex items-center gap-1 ml-1">
              {topTypeBadges.map(b => (
                <button
                  key={b.label}
                  onClick={() => setTypeFilter(f => f === b.label ? null : b.label)}
                  className="px-1.5 py-0.5 rounded text-[10px] font-bold cursor-pointer transition-all"
                  style={{
                    background: typeFilter === b.label ? b.color : "transparent",
                    color: typeFilter === b.label ? "#fff" : b.color,
                    border: `1px solid ${typeFilter === b.label ? b.color : "rgba(255,255,255,0.15)"}`,
                    opacity: typeFilter && typeFilter !== b.label ? 0.4 : 1,
                  }}
                >
                  {b.label}
                </button>
              ))}
              {typeFilter && (
                <button
                  onClick={() => setTypeFilter(null)}
                  className="w-4 h-4 rounded flex items-center justify-center text-[10px] text-muted-foreground hover:text-foreground cursor-pointer"
                >
                  {"\u2715"}
                </button>
              )}
            </div>
          )}
          <div className="flex-1" />
          <SortButton field="name" label="Name" currentSort={drive.sort} onSort={handleSort} />
          <SortButton field="size" label="Size" currentSort={drive.sort} onSort={handleSort} />
          <SortButton field="updatedAt" label="Modified" currentSort={drive.sort} onSort={handleSort} />
        </div>
      </div>

      {/* Error */}
      {drive.error && (
        <div className="px-4 py-2 bg-danger/10 border-b border-danger/30 text-danger text-xs font-mono">
          {drive.error}
          <button onClick={drive.refresh} className="ml-2 underline cursor-pointer">Retry</button>
        </div>
      )}

      {/* Folders grid — uniform cards, 10 per row, back first, (+) create last */}
      {driveTab === "files" && (
        <div
          ref={folderListRef}
          className="px-3 py-2 border-b border-border/40 bg-card/20 shrink-0 overflow-y-auto"
          style={{ display: "flex", flexWrap: "wrap", gap: "6px", maxHeight: "140px" }}
        >
          {/* Back + New — together = 1 folder card width */}
          <div style={{ width: "10ch", height: "3.2em", display: "flex", gap: "10%" }}>
            <button
              className="flex items-center justify-center rounded transition-all hover:shadow-md cursor-pointer"
              style={{
                background: drive.currentFolderId ? "rgba(255,255,255,0.08)" : "rgba(255,255,255,0.04)",
                border: "1px solid rgba(255,255,255,0.18)",
                width: "45%",
                height: "100%",
              }}
              onClick={() => {
                if (drive.currentFolderId) {
                  navCooldownRef.current = Date.now();
                  const parentId = drive.breadcrumbs.length >= 2 ? drive.breadcrumbs[drive.breadcrumbs.length - 2].id : null;
                  drive.navigateTo(parentId);
                }
              }}
              aria-label={drive.currentFolderId ? "Go back" : "Root"}
            >
              <span className="text-[10px] font-medium text-foreground">{drive.currentFolderId ? "<" : "o"}</span>
            </button>
            <button
              className="flex items-center justify-center rounded transition-all hover:shadow-md cursor-pointer"
              style={{
                background: "rgba(255,255,255,0.04)",
                border: "1px dashed rgba(255,255,255,0.3)",
                width: "45%",
                height: "100%",
              }}
              onClick={() => setShowNewFolder(true)}
              aria-label="New folder"
            >
              <span className="text-[10px] font-medium text-foreground">+</span>
            </button>
          </div>
          {drive.currentFolderId && sortedItems.length === 0 && (
            <button
              className="flex items-center justify-center rounded transition-all hover:shadow-md cursor-pointer"
              style={{
                background: "rgba(239,68,68,0.08)",
                border: "1px dashed rgba(239,68,68,0.3)",
                width: "10ch",
                height: "3.2em",
              }}
              onClick={async () => {
                const fid = drive.currentFolderId;
                if (!fid) return;
                const name = drive.breadcrumbs.length > 0 ? drive.breadcrumbs[drive.breadcrumbs.length - 1].name : "folder";
                const parentId = drive.breadcrumbs.length >= 2 ? drive.breadcrumbs[drive.breadcrumbs.length - 2].id : null;
                try {
                  await drive.deleteItems([fid]);
                  drive.navigateTo(parentId);
                  log.info("drive", `Trashed folder: ${name}`);
                } catch (e) { log.error("drive", `Delete folder failed: ${(e as Error).message}`); }
              }}
              title={`Delete ${drive.breadcrumbs.length > 0 ? drive.breadcrumbs[drive.breadcrumbs.length - 1].name : "folder"}`}
              aria-label="Delete current folder"
            >
              <span className="text-[10px] font-medium text-foreground">- Remove</span>
            </button>
          )}
          {sortedItems.filter(i => i.kind === "folder").map((f, fi) => {
            const folderSelMode = selectionMode || drive.selectedIds.size > 0;
            const folderSel = drive.selectedIds.has(f.id);
            return (
            <button
              key={f.id}
              data-folder-idx={fi}
              className="flex flex-col items-center justify-center rounded transition-all hover:shadow-md cursor-pointer select-none"
              style={{
                background: folderSel ? driveAlpha(0.18) : "rgba(255,255,255,0.08)",
                border: folderSel ? `1px solid ${DRIVE_COLOR}` : "1px solid rgba(255,255,255,0.18)",
                width: "10ch",
                height: "3.2em",
              }}
              onClick={() => {
                if (Date.now() - navCooldownRef.current < 400) return;
                if (folderSelMode) { /* handled by mouseDown */ }
                else { navCooldownRef.current = Date.now(); setHoveredFolder(null); drive.navigateTo(f.id); }
              }}
              onMouseDown={(e) => { if (e.button === 0 && folderSelMode) { e.preventDefault(); handleFolderDragStart(fi); } }}
              onMouseEnter={() => setHoveredFolder(f.name)}
              onMouseLeave={() => setHoveredFolder(null)}
              title={f.name}
              aria-label={f.name}
            >
              <span
                className="text-[10px] font-medium leading-tight text-center px-1"
                style={{ wordBreak: "break-all", display: "-webkit-box", WebkitLineClamp: folderSelMode ? 1 : 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}
              >{truncFolderName(f.name)}</span>
              {folderSelMode && (
                <input
                  type="checkbox"
                  checked={folderSel}
                  readOnly
                  className="w-3.5 h-3.5 rounded cursor-pointer pointer-events-none mt-0.5"
                  style={{ accentColor: DRIVE_COLOR }}
                />
              )}
            </button>
            );
          })}
        </div>
      )}

      {/* File list, Gallery, Albums, or New File Editor */}
      {newFilePhase === "editing" && !editingFileId ? (
        <NewFileEditor
          ext={newFileType}
          content={newFileContent}
          onChange={setNewFileContent}
          onSave={handleEditorSave}
          onCancel={handleEditorCancel}
          fileName={newFileName}
        />
      ) : driveTab === "albums" ? (
        <div className="flex-1 overflow-auto">
          <AlbumsPanel />
        </div>
      ) : driveTab === "files" && viewMode === "gallery" ? (
        <div className="flex-1 overflow-auto">
          <Suspense fallback={<div className="flex items-center justify-center py-16 text-xs text-muted-foreground">Loading gallery...</div>}>
            <GalleryViewPanel folderId={drive.currentFolderId ?? "root"} />
          </Suspense>
        </div>
      ) : (
      <div style={{ flex: 1, display: "flex", overflow: "hidden", minHeight: 0 }}>
        {/* Left: file list (30% detail / 50% commander / 100% normal) */}
        <div ref={scrollContainerRef} style={{ width: showSplitPane ? "30%" : "100%", height: "100%", transition: "width 0.2s ease", overflow: "auto" }}>
          {drive.loading && drive.items.length === 0 ? (
            <div className="flex-1 flex items-center justify-center py-16">
              <div className="flex flex-col items-center gap-2">
                <div
                  className="w-6 h-6 border-2 border-t-transparent rounded-full animate-spin"
                  style={{ borderColor: DRIVE_COLOR, borderTopColor: "transparent" }}
                />
                <span className="text-xs text-muted-foreground">Loading files...</span>
              </div>
            </div>
          ) : sortedItems.filter(i => i.kind === "file").length === 0 && sortedItems.filter(i => i.kind === "folder").length === 0 ? (
            <EmptyState tab={driveTab} onUpload={() => fileInputRef.current?.click()} />
          ) : (
            <div className="divide-y divide-border/30 pb-8 select-none" ref={fileListRef}>
              {filteredFiles.map((item, idx) => (
                <div key={item.id} data-file-idx={idx}>
                  <FileRow
                    item={item}
                    selected={drive.selectedIds.has(item.id)}
                    active={selectedItem?.id === item.id}
                    compact={false}
                    showCheckbox={selectionMode || drive.selectedIds.size > 0}
                    onSelect={() => drive.toggleSelect(item.id)}
                    onClick={() => handleItemClick(item)}
                    onDragStart={(y) => handleFileDragStart(idx, y)}
                    onStar={() => drive.toggleStar(item.id)}
                    onDelete={() => { drive.deleteItems([item.id]); log.info("drive", `Trashed: ${item.name}`); }}
                    onRename={(newName) => { drive.renameItem(item.id, newName); log.info("drive", `Renamed: ${item.name} -> ${newName}`); }}
                    onShare={() => setShareTarget(item)}
                    onDownload={() => {
                      if (item.kind === "folder") download.downloadFolderZip(item.id);
                      else download.downloadFile(item.id);
                    }}
                    onCopy={() => setCopyTarget([item.id])}
                    onMove={() => setMoveTarget([item.id])}
                    onVersionHistory={() => setVersionTarget(item.id)}
                    onEdit={isEditable(item) ? () => handleEditFile(item) : undefined}
                    onRestore={isTrash ? () => drive.restoreItem(item.id) : undefined}
                    isTrash={isTrash}
                    menuOpen={menuOpen === item.id}
                    onMenuToggle={() => setMenuOpen(menuOpen === item.id ? null : item.id)}
                  />
                </div>
              ))}
            </div>
          )}
        </div>
        {/* Center: vertical action bar (commander only) */}
        {commanderOpen && (
          <div
            className="flex flex-col items-center py-3 gap-4 shrink-0 border-x border-border/50"
            style={{ width: "52px", background: driveAlpha(0.03) }}
          >
            {/* Flip left<->right */}
            <button
              onClick={() => {
                const r = commanderRef.current;
                if (!r) return;
                const leftId = drive.currentFolderId;
                const rightId = r.rightDrive.currentFolderId;
                drive.navigateTo(rightId);
                r.rightDrive.navigateTo(leftId);
              }}
              className="w-10 h-8 rounded flex flex-col items-center justify-center text-[10px] font-medium cursor-pointer transition-colors hover:bg-muted/50"
              style={{ color: "var(--foreground)" }}
              title="Swap left and right folders"
            >
              <span>&lt;-&gt;</span>
              <span>Flip</span>
            </button>

            <div className="w-8 border-t border-border/50" />

            {/* Folder section */}
            <span className="text-[9px] text-muted-foreground uppercase tracking-wider">Folder</span>
            <button
              onClick={() => {
                const r = commanderRef.current;
                if (!r) return;
                const crumbs = r.rightDrive.breadcrumbs;
                if (crumbs.length > 0) {
                  setRenameFolderName(crumbs[crumbs.length - 1].name);
                  setRenamingFolder(true);
                }
              }}
              className="w-10 h-8 rounded flex flex-col items-center justify-center text-[10px] font-medium cursor-pointer transition-colors hover:bg-muted/50"
              style={{ color: "var(--foreground)", visibility: rightFolderId ? "visible" : "hidden", pointerEvents: rightFolderId ? "auto" : "none" }}
              title="Rename current folder (right pane)"
            >
              <span>{"\u270E"}</span>
              <span>Ren</span>
            </button>
            <button
              onClick={async () => {
                const r = commanderRef.current;
                if (!r || !rightFolderId) return;
                const crumbs = r.rightDrive.breadcrumbs;
                const name = crumbs.length > 0 ? crumbs[crumbs.length - 1].name : "folder";
                const parentId = crumbs.length >= 2 ? crumbs[crumbs.length - 2].id : null;
                try {
                  await r.rightDrive.deleteItems([rightFolderId]);
                  r.rightDrive.navigateTo(parentId);
                  log.info("drive", `Trashed folder: ${name}`);
                } catch (e) { log.error("drive", `Delete folder failed: ${(e as Error).message}`); }
              }}
              className="w-10 h-8 rounded flex flex-col items-center justify-center text-[10px] font-medium cursor-pointer transition-colors hover:bg-muted/50 text-danger"
              style={{ visibility: (rightFolderId && commanderRef.current?.rightDrive.items.length === 0) ? "visible" : "hidden", pointerEvents: (rightFolderId && commanderRef.current?.rightDrive.items.length === 0) ? "auto" : "none" }}
              title="Delete current folder (right pane, empty only)"
            >
              <span>{"\u2715"}</span>
              <span>Del</span>
            </button>

            <div className="w-8 border-t border-border/50" />

            {/* File section — hidden when no selection */}
            {(() => { const hasSel = drive.selectedIds.size > 0; const vis = hasSel ? "visible" : "hidden"; return (<>
            <span className="text-[9px] text-muted-foreground uppercase tracking-wider" style={{ visibility: vis }}>File</span>
            <button
              onClick={async () => {
                const ids = Array.from(drive.selectedIds);
                const r = commanderRef.current;
                if (!ids.length || !r) return;
                try {
                  await drive.copyItems(ids, r.rightDrive.currentFolderId);
                  r.rightDrive.refresh();
                  drive.clearSelection();
                  log.info("drive", `Copied ${ids.length} item(s)`);
                } catch (e) { log.error("drive", `Copy failed: ${(e as Error).message}`); }
              }}
              className="w-10 h-8 rounded flex flex-col items-center justify-center text-[10px] font-medium cursor-pointer transition-colors hover:bg-muted/50"
              style={{ color: "var(--foreground)", visibility: vis, pointerEvents: hasSel ? "auto" : "none" }}
              title="Copy selected files to right pane"
            >
              <span>{"\u2192"}</span>
              <span>Copy</span>
            </button>
            <button
              onClick={async () => {
                const ids = Array.from(drive.selectedIds);
                const r = commanderRef.current;
                if (!ids.length || !r) return;
                try {
                  await drive.moveItems(ids, r.rightDrive.currentFolderId);
                  await r.rightDrive.refresh();
                  drive.clearSelection();
                  log.info("drive", `Moved ${ids.length} item(s)`);
                } catch (e) { log.error("drive", `Move failed: ${(e as Error).message}`); }
              }}
              className="w-10 h-8 rounded flex flex-col items-center justify-center text-[10px] font-medium cursor-pointer transition-colors hover:bg-muted/50"
              style={{ color: "var(--foreground)", visibility: vis, pointerEvents: hasSel ? "auto" : "none" }}
              title="Move selected files to right pane"
            >
              <span>{"\u21E8"}</span>
              <span>Move</span>
            </button>
            <button
              onClick={() => {
                const ids = Array.from(drive.selectedIds);
                if (!ids.length) return;
                drive.deleteItems(ids);
                drive.clearSelection();
              }}
              className="w-10 h-8 rounded flex flex-col items-center justify-center text-[10px] font-medium cursor-pointer transition-colors hover:bg-muted/50 text-danger"
              style={{ visibility: vis, pointerEvents: hasSel ? "auto" : "none" }}
              title="Delete selected files"
            >
              <span>{"\u2715"}</span>
              <span>Del</span>
            </button>
            </>); })()}
            <button
              onClick={() => {
                const ids = Array.from(drive.selectedIds);
                if (!ids.length) return;
                drive.deleteItems(ids);
                drive.clearSelection();
              }}
              className="w-10 h-8 rounded flex flex-col items-center justify-center text-[10px] font-medium cursor-pointer transition-colors hover:bg-muted/50 text-danger"
              style={{ visibility: drive.selectedIds.size > 0 ? "visible" : "hidden", pointerEvents: drive.selectedIds.size > 0 ? "auto" : "none" }}
              title="Delete selected items"
            >
              <span>{"\u2715"}</span>
              <span>Del</span>
            </button>

          </div>
        )}

        {/* Right: detail pane or commander */}
        {showSplitPane && (
          <div style={{ flex: commanderOpen ? 1 : undefined, width: commanderOpen ? undefined : "70%", transition: "width 0.2s ease", overflow: "hidden", display: "flex", flexDirection: "column" }}>
            {commanderOpen ? (
              <Suspense fallback={<div className="flex items-center justify-center py-16 text-xs text-muted-foreground">Loading commander...</div>}>
                <CommanderMode
                  ref={commanderRef}
                  leftDrive={drive}
                  onClose={() => setCommanderOpen(false)}
                  onNewFile={handleNewFileClick}
                  onRightFolderChange={setRightFolderId}
                  renamingFolder={renamingFolder}
                  renameFolderName={renameFolderName}
                  onRenameFolderNameChange={setRenameFolderName}
                  onRenameFolderCommit={handleRenameFolder}
                  onRenameFolderCancel={() => { setRenamingFolder(false); setRenameFolderName(""); }}
                />
              </Suspense>
            ) : editingFileId && selectedItem ? (
              <div className="h-full flex flex-col bg-background border-l border-border overflow-hidden">
                <textarea
                  className="flex-1 min-h-0 p-4 bg-background text-foreground font-mono text-sm resize-none focus:outline-none border-none"
                  value={newFileContent}
                  onChange={(e) => setNewFileContent(e.target.value)}
                  placeholder={`Editing ${newFileName}...`}
                  autoFocus
                />
                <div className="px-3 pb-2 text-center">
                  <button
                    onClick={() => setFullscreenEdit(true)}
                    className="text-[10px] text-muted-foreground/50 hover:text-foreground/70 transition-colors cursor-pointer"
                  >
                    Click here to edit fullscreen
                  </button>
                </div>
              </div>
            ) : selectedItem ? (
              <FileDetailPane key={`detail-${selectedItem.id}-v${previewVersion}`} item={selectedItem} onFullscreen={setFullscreenItem} version={previewVersion} />
            ) : null}
          </div>
        )}
      </div>
      )}

      {/* Upload progress removed — files appear as grey placeholders in the list */}


      {/* Copy dialog */}
      {copyTarget && (
        <Suspense fallback={null}>
          <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={() => setCopyTarget(null)}>
            <div className="absolute inset-0 bg-background/60 backdrop-blur-sm" />
            <div className="relative w-full max-w-lg mx-4" onClick={e => e.stopPropagation()}>
              <CopyFilesPanel
                itemIds={copyTarget}
                onClose={() => setCopyTarget(null)}
                onCopyDone={() => { setCopyTarget(null); drive.refresh(); }}
              />
            </div>
          </div>
        </Suspense>
      )}

      {/* Move dialog */}
      {moveTarget && (
        <Suspense fallback={null}>
          <LazyMoveDialog
            itemIds={moveTarget}
            onClose={() => { setMoveTarget(null); drive.refresh(); }}
          />
        </Suspense>
      )}

      {/* Version History dialog */}
      {versionTarget && (
        <Suspense fallback={null}>
          <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={() => setVersionTarget(null)}>
            <div className="absolute inset-0 bg-background/60 backdrop-blur-sm" />
            <div className="relative w-full max-w-lg mx-4" onClick={e => e.stopPropagation()}>
              <VersionHistoryPanel />
              <button
                onClick={() => setVersionTarget(null)}
                className="absolute top-2 right-2 w-7 h-7 rounded-lg flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors cursor-pointer"
              >
                {"\u2715"}
              </button>
            </div>
          </div>
        </Suspense>
      )}

      {/* Fullscreen preview overlay */}
      {fullscreenItem && (
        <FullscreenPreview item={fullscreenItem} onClose={() => setFullscreenItem(null)} />
      )}

      {/* Fullscreen edit overlay */}
      {fullscreenEdit && editingFileId && (
        <div className="fixed inset-0 z-50 flex flex-col bg-background">
          <div className="h-10 flex items-center px-4 border-b border-border shrink-0 gap-2">
            <span className="text-[11px] font-medium text-muted-foreground truncate">{newFileName}</span>
            <button onClick={handleEditorSave} className="px-1.5 py-1 rounded text-[11px] font-medium cursor-pointer ml-1" style={{ color: DRIVE_COLOR }}>Save</button>
            <button onClick={handleEditorCancel} className="w-5 h-5 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors cursor-pointer shrink-0 text-[10px] ml-1" title="Cancel">{"\u2715"}</button>
            <div className="flex-1" />
            <button onClick={() => setFullscreenEdit(false)} className="px-1.5 py-1 rounded text-[11px] font-medium cursor-pointer transition-colors text-muted-foreground hover:text-foreground hover:bg-muted/30 whitespace-nowrap" title="Back to split view">Split view</button>
          </div>
          <textarea
            className="flex-1 min-h-0 p-6 bg-background text-foreground font-mono text-sm resize-none focus:outline-none border-none"
            value={newFileContent}
            onChange={(e) => setNewFileContent(e.target.value)}
            placeholder={`Editing ${newFileName}...`}
            autoFocus
          />
        </div>
      )}

      {/* New file modals */}
      {newFilePhase === "pick-type" && (
        <NewFileTypePicker onPick={handlePickFileType} onCancel={() => setNewFilePhase("idle")} />
      )}
      {/* Save dialog removed — filename set in type picker */}
    </div>
  );
}
