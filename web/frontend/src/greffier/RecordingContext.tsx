// ============================================
//  RecordingContext — React Context + Provider
//  Wraps RecordingManager singleton
// ============================================

import { createContext, useContext, useState, useEffect, useCallback, useRef } from "react";
import type { ReactNode } from "react";
import { getRecordingManager } from "./RecordingManager";
import type { RecordingState } from "./recording-types";

interface RecordingContextValue {
  state: RecordingState;
  startRecording: (useCase: string, lang: string) => Promise<void>;
  stopRecording: () => void;
  cancelRecording: () => void;
  reset: () => void;
}

const RecordingContext = createContext<RecordingContextValue | null>(null);

export function RecordingProvider({ children }: { children: ReactNode }) {
  const mgr = useRef(getRecordingManager());
  const [state, setState] = useState<RecordingState>(() => mgr.current.getState());

  useEffect(() => {
    return mgr.current.subscribe((s) => setState(s));
  }, []);

  const startRecording = useCallback(
    (useCase: string, lang: string) => mgr.current.startRecording(useCase, lang),
    [],
  );
  const stopRecording = useCallback(() => mgr.current.stopRecording(), []);
  const cancelRecording = useCallback(() => mgr.current.cancelRecording(), []);
  const reset = useCallback(() => mgr.current.reset(), []);

  return (
    <RecordingContext.Provider value={{ state, startRecording, stopRecording, cancelRecording, reset }}>
      {children}
    </RecordingContext.Provider>
  );
}

export function useRecording(): RecordingContextValue {
  const ctx = useContext(RecordingContext);
  if (!ctx) throw new Error("useRecording must be used within a RecordingProvider");
  return ctx;
}
