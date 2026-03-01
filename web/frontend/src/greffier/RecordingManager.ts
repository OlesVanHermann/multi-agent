// ============================================
//  RecordingManager — Pure TS singleton engine
//  Owns MediaRecorder, WebSocket, AudioContext,
//  WakeLock. Survives React unmounts.
// ============================================

import type { RecordingPhase, RecordingState, RecordingResult } from "./recording-types";

const HEARTBEAT_MS = 5000;
const ELAPSED_MS = 1000;
const POLL_MS = 1500;
const VOLUME_THROTTLE_MS = 100;
const NOTIFY_THROTTLE_MS = 80;

function initialState(): RecordingState {
  return {
    phase: "idle",
    elapsed: 0,
    bytesRecorded: 0,
    volume: 0,
    fileId: null,
    error: null,
    warning: null,
    wavBlobUrl: null,
    taskId: null,
    status: "",
    progressMsg: "",
    stepInfo: null,
    result: null,
  };
}

class RecordingManager {
  private _state: RecordingState = initialState();
  private _listeners = new Set<(s: RecordingState) => void>();
  private _notifyTimeout: ReturnType<typeof setTimeout> | null = null;

  // Resources
  private _mediaRecorder: MediaRecorder | null = null;
  private _mediaStream: MediaStream | null = null;
  private _ws: WebSocket | null = null;
  private _audioCtx: AudioContext | null = null;
  private _analyser: AnalyserNode | null = null;
  private _scriptProcessor: ScriptProcessorNode | null = null;
  private _wakeLock: WakeLockSentinel | null = null;

  // Intervals / timers
  private _elapsedInterval: ReturnType<typeof setInterval> | null = null;
  private _heartbeatInterval: ReturnType<typeof setInterval> | null = null;
  private _pollInterval: ReturnType<typeof setInterval> | null = null;
  private _rafId: number | null = null;
  private _lastVolumeNotify = 0;

  // PCM chunks for WAV encoding
  private _pcmChunks: Float32Array[] = [];
  private _sampleRate = 8000;

  // Config for current recording
  private _useCase = "meeting";
  private _lang = "fr";

  // ---- Public API ----

  getState(): RecordingState {
    return { ...this._state };
  }

  subscribe(listener: (s: RecordingState) => void): () => void {
    this._listeners.add(listener);
    return () => this._listeners.delete(listener);
  }

  async startRecording(useCase: string, lang: string): Promise<void> {
    if (this._state.phase !== "idle" && this._state.phase !== "error" && this._state.phase !== "done") {
      return;
    }

    this._useCase = useCase;
    this._lang = lang;
    this._state = { ...initialState(), phase: "requesting" };
    this._pcmChunks = [];
    this._notifyImmediate();

    try {
      // 1. WakeLock
      await this._acquireWakeLock();

      // 2. getUserMedia
      this._mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: { sampleRate: 8000, channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });

      // 3. AudioContext (8kHz) + AnalyserNode + ScriptProcessor for PCM capture
      this._audioCtx = new AudioContext({ sampleRate: 8000 });
      this._sampleRate = this._audioCtx.sampleRate;
      const source = this._audioCtx.createMediaStreamSource(this._mediaStream);

      this._analyser = this._audioCtx.createAnalyser();
      this._analyser.fftSize = 256;
      source.connect(this._analyser);

      // ScriptProcessor for PCM capture (buffer size 4096)
      this._scriptProcessor = this._audioCtx.createScriptProcessor(4096, 1, 1);
      this._scriptProcessor.onaudioprocess = (e) => {
        const input = e.inputBuffer.getChannelData(0);
        this._pcmChunks.push(new Float32Array(input));
      };
      source.connect(this._scriptProcessor);
      this._scriptProcessor.connect(this._audioCtx.destination);

      // 4. WebSocket
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const wsUrl = `${protocol}//${window.location.host}/ws/greffier/record?use_case=${encodeURIComponent(useCase)}&lang=${encodeURIComponent(lang)}`;
      this._ws = new WebSocket(wsUrl);

      await new Promise<void>((resolve, reject) => {
        const ws = this._ws!;
        ws.onopen = () => resolve();
        ws.onerror = () => reject(new Error("WebSocket connection failed"));
        // Timeout after 10s
        setTimeout(() => reject(new Error("WebSocket connection timeout")), 10000);
      });

      this._ws.onmessage = (ev) => this._handleWsMessage(ev);
      this._ws.onclose = () => this._handleWsClose();
      this._ws.onerror = () => this._handleWsError();

      // 5. MediaRecorder — send audio chunks via WS
      this._mediaRecorder = new MediaRecorder(this._mediaStream, {
        mimeType: this._getPreferredMimeType(),
      });

      this._mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0 && this._ws?.readyState === WebSocket.OPEN) {
          this._ws.send(e.data);
          this._state.bytesRecorded += e.data.size;
        }
      };

      this._mediaRecorder.start(1000); // 1s chunks

      // 6. Start timers
      this._state.phase = "recording";
      this._startElapsedTimer();
      this._startHeartbeat();
      this._startVolumeLoop();
      this._notifyImmediate();
    } catch (err) {
      this._cleanup();
      this._state.phase = "error";
      this._state.error = err instanceof Error ? err.message : "Failed to start recording";
      this._notifyImmediate();
    }
  }

  stopRecording(): void {
    if (this._state.phase !== "recording") return;

    this._state.phase = "stopping";
    this._notifyImmediate();

    // Release WakeLock
    this._releaseWakeLock();

    // Stop timers
    this._stopElapsedTimer();
    this._stopHeartbeat();
    this._stopVolumeLoop();

    // Encode WAV from PCM chunks
    const wavBlob = this._encodeWAV();
    if (wavBlob) {
      if (this._state.wavBlobUrl) URL.revokeObjectURL(this._state.wavBlobUrl);
      this._state.wavBlobUrl = URL.createObjectURL(wavBlob);
    }

    // Disconnect audio
    if (this._scriptProcessor) {
      this._scriptProcessor.disconnect();
      this._scriptProcessor = null;
    }
    if (this._analyser) {
      this._analyser.disconnect();
      this._analyser = null;
    }
    if (this._audioCtx) {
      this._audioCtx.close().catch(() => {});
      this._audioCtx = null;
    }

    // Stop MediaRecorder
    if (this._mediaRecorder && this._mediaRecorder.state !== "inactive") {
      this._mediaRecorder.stop();
    }
    this._mediaRecorder = null;

    // Stop tracks
    if (this._mediaStream) {
      this._mediaStream.getTracks().forEach((t) => t.stop());
      this._mediaStream = null;
    }

    // Send stop to WS
    if (this._ws?.readyState === WebSocket.OPEN) {
      this._ws.send(JSON.stringify({ action: "stop" }));
    }

    this._notifyImmediate();
  }

  cancelRecording(): void {
    if (this._state.phase !== "recording" && this._state.phase !== "requesting") return;

    // Same cleanup as stop but send cancel
    this._releaseWakeLock();
    this._stopElapsedTimer();
    this._stopHeartbeat();
    this._stopVolumeLoop();

    if (this._scriptProcessor) {
      this._scriptProcessor.disconnect();
      this._scriptProcessor = null;
    }
    if (this._analyser) {
      this._analyser.disconnect();
      this._analyser = null;
    }
    if (this._audioCtx) {
      this._audioCtx.close().catch(() => {});
      this._audioCtx = null;
    }

    if (this._mediaRecorder && this._mediaRecorder.state !== "inactive") {
      this._mediaRecorder.stop();
    }
    this._mediaRecorder = null;

    if (this._mediaStream) {
      this._mediaStream.getTracks().forEach((t) => t.stop());
      this._mediaStream = null;
    }

    if (this._ws?.readyState === WebSocket.OPEN) {
      this._ws.send(JSON.stringify({ action: "cancel" }));
      this._ws.close();
    }
    this._ws = null;

    this._pcmChunks = [];
    this._state = initialState();
    this._notifyImmediate();
  }

  reset(): void {
    if (this._state.phase === "recording" || this._state.phase === "requesting") {
      this.cancelRecording();
      return;
    }

    this._stopPollInterval();

    if (this._ws) {
      this._ws.close();
      this._ws = null;
    }

    if (this._state.wavBlobUrl) {
      URL.revokeObjectURL(this._state.wavBlobUrl);
    }

    this._pcmChunks = [];
    this._state = initialState();
    this._notifyImmediate();
  }

  // ---- WebSocket handlers ----

  private _handleWsMessage(ev: MessageEvent): void {
    try {
      const data = JSON.parse(ev.data);

      if (data.bytes_recorded != null) {
        this._state.bytesRecorded = data.bytes_recorded;
      }

      if (data.warning) {
        this._state.warning = data.warning;
      }

      if (data.status === "processing" && data.file_id) {
        this._state.fileId = data.file_id;
        this._state.phase = "processing";
        this._state.status = "processing";
        this._state.progressMsg = "Processing audio...";

        // Close WS — backend will process independently
        if (this._ws) {
          this._ws.close();
          this._ws = null;
        }

        // Create unified task
        this._createTask(data.file_id);

        // Start polling for processing status
        this._startPollInterval(data.file_id);
        this._notifyImmediate();
      }

      if (data.error) {
        this._state.phase = "error";
        this._state.error = data.error;
        this._cleanup();
        this._notifyImmediate();
      }
    } catch {
      // Binary data or non-JSON — ignore
    }
  }

  private _handleWsClose(): void {
    // If we're still recording, this is unexpected
    if (this._state.phase === "recording") {
      this._state.phase = "error";
      this._state.error = "WebSocket connection lost during recording";
      this._cleanup();
      this._notifyImmediate();
    }
  }

  private _handleWsError(): void {
    if (this._state.phase === "recording" || this._state.phase === "requesting") {
      this._state.phase = "error";
      this._state.error = "WebSocket error";
      this._cleanup();
      this._notifyImmediate();
    }
  }

  // ---- Processing poll ----

  private _startPollInterval(fileId: string): void {
    this._stopPollInterval();
    this._pollInterval = setInterval(() => this._pollStatus(fileId), POLL_MS);
  }

  private _stopPollInterval(): void {
    if (this._pollInterval) {
      clearInterval(this._pollInterval);
      this._pollInterval = null;
    }
  }

  private async _pollStatus(fileId: string): Promise<void> {
    try {
      const res = await fetch(`/api/greffier/status/${encodeURIComponent(fileId)}`);
      if (!res.ok) return;
      const data = await res.json();

      this._state.status = data.status || this._state.status;
      this._state.progressMsg = data.progress_msg || data.message || this._state.progressMsg;

      if (data.step != null && data.total != null) {
        this._state.stepInfo = {
          step: data.step,
          total: data.total,
          label: data.step_label || `Step ${data.step}/${data.total}`,
        };
      }

      if (data.status === "completed") {
        this._stopPollInterval();
        await this._fetchResult(fileId);
        this._state.phase = "done";
        this._notifyImmediate();
      } else if (data.status === "error") {
        this._stopPollInterval();
        this._state.phase = "error";
        this._state.error = data.error || data.message || "Processing failed";
        this._notifyImmediate();
      } else {
        this._notify();
      }
    } catch {
      // Network error during poll — will retry on next interval
    }
  }

  private async _fetchResult(fileId: string): Promise<void> {
    try {
      const res = await fetch(`/api/greffier/status/${encodeURIComponent(fileId)}`);
      if (!res.ok) return;
      const data = await res.json();

      this._state.result = {
        fileId,
        transcript: data.transcript || null,
        summary: data.summary || null,
        utterances: data.utterances || [],
        wavDriveId: data.wav_drive_id || null,
        summaryDriveId: data.summary_drive_id || null,
        transcriptDriveId: data.transcript_drive_id || null,
        fileMeta: data.file_meta || null,
      };
    } catch {
      // Keep result null on error
    }
  }

  private async _createTask(fileId: string): Promise<void> {
    try {
      const res = await fetch("/api/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          type: "greffier",
          label: `Greffier — ${this._useCase}`,
          fileId,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        this._state.taskId = data.task_id || data.id || null;
      }
    } catch {
      // Task creation is optional
    }
  }

  // ---- Timers ----

  private _startElapsedTimer(): void {
    this._stopElapsedTimer();
    this._elapsedInterval = setInterval(() => {
      this._state.elapsed += 1;
      this._notify();
    }, ELAPSED_MS);
  }

  private _stopElapsedTimer(): void {
    if (this._elapsedInterval) {
      clearInterval(this._elapsedInterval);
      this._elapsedInterval = null;
    }
  }

  private _startHeartbeat(): void {
    this._stopHeartbeat();
    this._heartbeatInterval = setInterval(() => {
      if (this._ws?.readyState === WebSocket.OPEN) {
        this._ws.send(JSON.stringify({ action: "heartbeat" }));
      }
    }, HEARTBEAT_MS);
  }

  private _stopHeartbeat(): void {
    if (this._heartbeatInterval) {
      clearInterval(this._heartbeatInterval);
      this._heartbeatInterval = null;
    }
  }

  // ---- Volume monitoring (rAF loop in singleton) ----

  private _startVolumeLoop(): void {
    this._stopVolumeLoop();
    const loop = () => {
      if (!this._analyser) return;
      const data = new Uint8Array(this._analyser.frequencyBinCount);
      this._analyser.getByteTimeDomainData(data);

      // RMS calculation
      let sum = 0;
      for (let i = 0; i < data.length; i++) {
        const v = (data[i] - 128) / 128;
        sum += v * v;
      }
      const rms = Math.sqrt(sum / data.length);
      this._state.volume = Math.min(255, Math.round(rms * 255 * 3));

      // Throttled notify for volume
      const now = Date.now();
      if (now - this._lastVolumeNotify > VOLUME_THROTTLE_MS) {
        this._lastVolumeNotify = now;
        this._notify();
      }

      this._rafId = requestAnimationFrame(loop);
    };
    this._rafId = requestAnimationFrame(loop);
  }

  private _stopVolumeLoop(): void {
    if (this._rafId != null) {
      cancelAnimationFrame(this._rafId);
      this._rafId = null;
    }
  }

  // ---- WakeLock ----

  private async _acquireWakeLock(): Promise<void> {
    try {
      if ("wakeLock" in navigator) {
        this._wakeLock = await navigator.wakeLock.request("screen");
      }
    } catch {
      // WakeLock not available — non-critical
    }
  }

  private _releaseWakeLock(): void {
    if (this._wakeLock) {
      this._wakeLock.release().catch(() => {});
      this._wakeLock = null;
    }
  }

  // ---- WAV encoding ----

  private _encodeWAV(): Blob | null {
    if (this._pcmChunks.length === 0) return null;

    const totalLength = this._pcmChunks.reduce((acc, c) => acc + c.length, 0);
    const merged = new Float32Array(totalLength);
    let offset = 0;
    for (const chunk of this._pcmChunks) {
      merged.set(chunk, offset);
      offset += chunk.length;
    }

    const numChannels = 1;
    const bitsPerSample = 16;
    const bytesPerSample = bitsPerSample / 8;
    const dataSize = merged.length * bytesPerSample;
    const buffer = new ArrayBuffer(44 + dataSize);
    const view = new DataView(buffer);

    // WAV header
    const writeStr = (off: number, str: string) => {
      for (let i = 0; i < str.length; i++) view.setUint8(off + i, str.charCodeAt(i));
    };

    writeStr(0, "RIFF");
    view.setUint32(4, 36 + dataSize, true);
    writeStr(8, "WAVE");
    writeStr(12, "fmt ");
    view.setUint32(16, 16, true);          // subchunk1 size
    view.setUint16(20, 1, true);           // PCM format
    view.setUint16(22, numChannels, true);
    view.setUint32(24, this._sampleRate, true);
    view.setUint32(28, this._sampleRate * numChannels * bytesPerSample, true);
    view.setUint16(32, numChannels * bytesPerSample, true);
    view.setUint16(34, bitsPerSample, true);
    writeStr(36, "data");
    view.setUint32(40, dataSize, true);

    // PCM data (float32 → int16)
    let pos = 44;
    for (let i = 0; i < merged.length; i++) {
      const s = Math.max(-1, Math.min(1, merged[i]));
      view.setInt16(pos, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
      pos += 2;
    }

    return new Blob([buffer], { type: "audio/wav" });
  }

  // ---- MIME type detection ----

  private _getPreferredMimeType(): string {
    const types = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
    for (const t of types) {
      if (MediaRecorder.isTypeSupported(t)) return t;
    }
    return "";
  }

  // ---- Cleanup ----

  private _cleanup(): void {
    this._releaseWakeLock();
    this._stopElapsedTimer();
    this._stopHeartbeat();
    this._stopVolumeLoop();
    this._stopPollInterval();

    if (this._scriptProcessor) {
      this._scriptProcessor.disconnect();
      this._scriptProcessor = null;
    }
    if (this._analyser) {
      this._analyser.disconnect();
      this._analyser = null;
    }
    if (this._audioCtx) {
      this._audioCtx.close().catch(() => {});
      this._audioCtx = null;
    }
    if (this._mediaRecorder && this._mediaRecorder.state !== "inactive") {
      try { this._mediaRecorder.stop(); } catch { /* ignore */ }
    }
    this._mediaRecorder = null;
    if (this._mediaStream) {
      this._mediaStream.getTracks().forEach((t) => t.stop());
      this._mediaStream = null;
    }
    if (this._ws) {
      this._ws.close();
      this._ws = null;
    }
  }

  // ---- Notify subscribers ----

  private _notify(): void {
    if (this._notifyTimeout) return;
    this._notifyTimeout = setTimeout(() => {
      this._notifyTimeout = null;
      const snap = this.getState();
      this._listeners.forEach((fn) => {
        try { fn(snap); } catch (e) { console.error("[RecordingManager] listener error:", e); }
      });
    }, NOTIFY_THROTTLE_MS);
  }

  private _notifyImmediate(): void {
    if (this._notifyTimeout) {
      clearTimeout(this._notifyTimeout);
      this._notifyTimeout = null;
    }
    const snap = this.getState();
    this._listeners.forEach((fn) => {
      try { fn(snap); } catch (e) { console.error("[RecordingManager] listener error:", e); }
    });
  }
}

// ---- Lazy singleton ----

let _instance: RecordingManager | null = null;

export function getRecordingManager(): RecordingManager {
  if (!_instance) {
    _instance = new RecordingManager();
  }
  return _instance;
}
