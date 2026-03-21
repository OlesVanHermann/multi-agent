import { useState, useCallback, useRef, useEffect } from "react";
import type {
  DriveEntry,
  DriveFile,
  DriveBreadcrumb,
  DriveViewTab,
  DriveSortState,
  DriveUploadProgress,
  DriveListResponse,
  DriveQuota,
  ShareInfo,
  SharePermission,
  ShareCreateResponse,
} from "./drive-types";

// =======================================
//  CONFIG
// =======================================
const API_BASE = import.meta.env.VITE_API_URL ?? "/api";
const DRIVE_API = `${API_BASE}/drive`;

// =======================================
//  HOOK — useDrive
// =======================================

interface UseDriveOptions {
  initialTab?: DriveViewTab;
}

interface UseDriveReturn {
  items: DriveEntry[];
  breadcrumbs: DriveBreadcrumb[];
  currentFolderId: string | null;
  loading: boolean;
  error: string | null;
  tab: DriveViewTab;
  sort: DriveSortState;
  uploads: DriveUploadProgress[];
  quota: DriveQuota | null;
  selectedIds: Set<string>;

  setTab: (tab: DriveViewTab) => void;
  setSort: (sort: DriveSortState) => void;
  navigateTo: (folderId: string | null) => void;
  refresh: () => void;
  uploadFiles: (files: FileList) => void;
  downloadFile: (file: DriveFile) => void;
  deleteItems: (ids: string[]) => void;
  renameItem: (id: string, newName: string) => Promise<void>;
  createFolder: (name: string) => Promise<void>;
  toggleStar: (id: string) => Promise<void>;
  restoreItem: (id: string) => Promise<void>;
  emptyTrash: () => Promise<void>;
  toggleSelect: (id: string) => void;
  selectAll: () => void;
  clearSelection: () => void;
  shareItem: (id: string, permission: SharePermission, recipientEmail?: string, expiresInDays?: number) => Promise<ShareCreateResponse>;
  getShareInfo: (id: string) => Promise<ShareInfo[]>;
  revokeShare: (shareId: string) => Promise<void>;
}

let _uploadId = 0;

export function useDrive(options: UseDriveOptions = {}): UseDriveReturn {
  const [items, setItems] = useState<DriveEntry[]>([]);
  const [breadcrumbs, setBreadcrumbs] = useState<DriveBreadcrumb[]>([]);
  const [currentFolderId, setCurrentFolderId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<DriveViewTab>(options.initialTab ?? "files");
  const [sort, setSort] = useState<DriveSortState>({ field: "name", dir: "asc" });
  const [uploads, setUploads] = useState<DriveUploadProgress[]>([]);
  const [quota, setQuota] = useState<DriveQuota | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const abortRef = useRef<AbortController | null>(null);

  // -- Fetch items --
  const fetchItems = useCallback(async (folderId: string | null, viewTab: DriveViewTab) => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    setLoading(true);
    setError(null);
    setSelectedIds(new Set());

    try {
      const params = new URLSearchParams();
      if (folderId) params.set("parent_id", folderId);
      params.set("view", viewTab);
      params.set("sort", sort.field);
      params.set("dir", sort.dir);

      const res = await fetch(`${DRIVE_API}/list?${params}`, { signal: ctrl.signal });
      if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);

      const data: DriveListResponse = await res.json();
      setItems(data.items);
      setBreadcrumbs(data.breadcrumbs);
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setError((err as Error).message);
      }
    } finally {
      setLoading(false);
    }
  }, [sort]);

  // -- Fetch quota --
  const fetchQuota = useCallback(async () => {
    try {
      const res = await fetch(`${DRIVE_API}/quota`);
      if (res.ok) setQuota(await res.json());
    } catch (err) { console.warn("[Drive] fetchQuota failed:", err); }
  }, []);

  // -- Auto-fetch on nav/tab/sort change --
  useEffect(() => {
    fetchItems(currentFolderId, tab);
    fetchQuota();
    return () => abortRef.current?.abort();
  }, [currentFolderId, tab, sort, fetchItems, fetchQuota]);

  // -- Auto-refresh on server push events (SSE) --
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (detail?.type === "drive:changed") {
        fetchItems(currentFolderId, tab);
        fetchQuota();
      }
    };
    window.addEventListener("app:event", handler);
    return () => window.removeEventListener("app:event", handler);
  }, [currentFolderId, tab, fetchItems, fetchQuota]);

  // -- Navigate --
  const navigateTo = useCallback((folderId: string | null) => {
    setCurrentFolderId(folderId);
  }, []);

  const refresh = useCallback(() => {
    fetchItems(currentFolderId, tab);
    fetchQuota();
  }, [currentFolderId, tab, fetchItems, fetchQuota]);

  // -- Upload --
  const uploadFiles = useCallback((files: FileList) => {
    Array.from(files).forEach(async (file) => {
      const fileId = `upload_${++_uploadId}`;
      const entry: DriveUploadProgress = {
        fileId,
        fileName: file.name,
        progress: 0,
        status: "pending",
      };
      setUploads(prev => [...prev, entry]);

      try {
        setUploads(prev =>
          prev.map(u => u.fileId === fileId ? { ...u, status: "uploading" } : u)
        );

        const formData = new FormData();
        formData.append("file", file);
        if (currentFolderId) formData.append("parent_id", currentFolderId);

        const xhr = new XMLHttpRequest();
        xhr.open("POST", `${DRIVE_API}/upload`);

        xhr.upload.addEventListener("progress", (e) => {
          if (e.lengthComputable) {
            const progress = Math.round((e.loaded / e.total) * 100);
            setUploads(prev =>
              prev.map(u => u.fileId === fileId ? { ...u, progress } : u)
            );
          }
        });

        await new Promise<void>((resolve, reject) => {
          xhr.onload = () => {
            if (xhr.status >= 200 && xhr.status < 300) {
              setUploads(prev =>
                prev.map(u => u.fileId === fileId ? { ...u, status: "done", progress: 100 } : u)
              );
              resolve();
            } else {
              reject(new Error(`Upload failed: ${xhr.statusText}`));
            }
          };
          xhr.onerror = () => reject(new Error("Network error during upload"));
          xhr.send(formData);
        });

        refresh();
      } catch (err) {
        setUploads(prev =>
          prev.map(u => u.fileId === fileId
            ? { ...u, status: "error", error: (err as Error).message }
            : u
          )
        );
      }
    });
  }, [currentFolderId, refresh]);

  // -- Download --
  const downloadFile = useCallback((file: DriveFile) => {
    const a = document.createElement("a");
    a.href = file.downloadUrl || `${DRIVE_API}/download/${file.id}`;
    a.download = file.name;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }, []);

  // -- Delete / Trash --
  const deleteItems = useCallback(async (ids: string[]) => {
    try {
      const res = await fetch(`${DRIVE_API}/trash`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids }),
      });
      if (!res.ok) throw new Error(`Trash failed: ${res.statusText}`);
      refresh();
    } catch (err) {
      setError((err as Error).message);
    }
  }, [refresh]);

  // -- Rename --
  const renameItem = useCallback(async (id: string, newName: string) => {
    const res = await fetch(`${DRIVE_API}/rename`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, name: newName }),
    });
    if (!res.ok) throw new Error(`Rename failed: ${res.statusText}`);
    refresh();
  }, [refresh]);

  // -- Create folder --
  const createFolder = useCallback(async (name: string) => {
    const res = await fetch(`${DRIVE_API}/folder`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, parent_id: currentFolderId }),
    });
    if (!res.ok) throw new Error(`Create folder failed: ${res.statusText}`);
    refresh();
  }, [currentFolderId, refresh]);

  // -- Star --
  const toggleStar = useCallback(async (id: string) => {
    const res = await fetch(`${DRIVE_API}/star/${id}`, { method: "POST" });
    if (!res.ok) throw new Error(`Star failed: ${res.statusText}`);
    setItems(prev => prev.map(item =>
      item.id === id ? { ...item, starred: !item.starred } : item
    ));
  }, []);

  // -- Restore from trash --
  const restoreItem = useCallback(async (id: string) => {
    const res = await fetch(`${DRIVE_API}/restore/${id}`, { method: "POST" });
    if (!res.ok) throw new Error(`Restore failed: ${res.statusText}`);
    refresh();
  }, [refresh]);

  // -- Empty trash --
  const emptyTrash = useCallback(async () => {
    const res = await fetch(`${DRIVE_API}/trash/empty`, { method: "POST" });
    if (!res.ok) throw new Error(`Empty trash failed: ${res.statusText}`);
    refresh();
  }, [refresh]);

  // -- Share --
  const shareItem = useCallback(async (
    id: string,
    permission: SharePermission,
    recipientEmail?: string,
    expiresInDays?: number,
  ): Promise<ShareCreateResponse> => {
    const res = await fetch(`${DRIVE_API}/share`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ itemId: id, permission, recipientEmail, expiresInDays }),
    });
    if (!res.ok) throw new Error(`Share failed: ${res.statusText}`);
    const data: ShareCreateResponse = await res.json();
    setItems(prev => prev.map(item =>
      item.id === id ? { ...item, shared: true } : item
    ));
    return data;
  }, []);

  const getShareInfo = useCallback(async (id: string): Promise<ShareInfo[]> => {
    const res = await fetch(`${DRIVE_API}/share/${id}`);
    if (!res.ok) throw new Error(`Get shares failed: ${res.statusText}`);
    return res.json();
  }, []);

  const revokeShare = useCallback(async (shareId: string) => {
    const res = await fetch(`${DRIVE_API}/share/${shareId}`, { method: "DELETE" });
    if (!res.ok) throw new Error(`Revoke share failed: ${res.statusText}`);
    refresh();
  }, [refresh]);

  // -- Selection --
  const toggleSelect = useCallback((id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const selectAll = useCallback(() => {
    setSelectedIds(new Set(items.map(i => i.id)));
  }, [items]);

  const clearSelection = useCallback(() => {
    setSelectedIds(new Set());
  }, []);

  return {
    items, breadcrumbs, currentFolderId, loading, error, tab, sort, uploads, quota, selectedIds,
    setTab, setSort, navigateTo, refresh, uploadFiles, downloadFile, deleteItems,
    renameItem, createFolder, toggleStar, restoreItem, emptyTrash,
    toggleSelect, selectAll, clearSelection,
    shareItem, getShareInfo, revokeShare,
  };
}
