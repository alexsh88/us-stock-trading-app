"use client";

import { useState, useCallback, useRef } from "react";
import { useTradingStore } from "@/store/trading-store";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const POLL_INTERVAL_MS = 3_000;

export function useAnalysisRun() {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { setCurrentRun, setSignals } = useTradingStore();
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const pollRunStatus = useCallback(
    async (runId: string) => {
      try {
        const res = await fetch(`${API_URL}/api/v1/analysis/${runId}`);
        if (!res.ok) return;
        const run = await res.json();
        setCurrentRun(run);

        if (run.status === "completed") {
          stopPolling();
          setIsLoading(false);
          // Fetch signals
          const sigRes = await fetch(`${API_URL}/api/v1/analysis/${runId}/signals`);
          if (sigRes.ok) {
            setSignals(await sigRes.json());
          }
        } else if (run.status === "failed") {
          stopPolling();
          setIsLoading(false);
          setError(run.error_message ?? "Analysis failed");
        }
      } catch (e) {
        // Network error — keep polling
      }
    },
    [setCurrentRun, setSignals, stopPolling]
  );

  const triggerAnalysis = useCallback(
    async (topN: number = 5, mode: string = "swing") => {
      setIsLoading(true);
      setError(null);
      stopPolling();

      try {
        const res = await fetch(`${API_URL}/api/v1/analysis/run`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ top_n: topN, mode }),
        });

        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }

        const run = await res.json();
        setCurrentRun(run);

        // Start polling
        pollRef.current = setInterval(() => pollRunStatus(run.id), POLL_INTERVAL_MS);
      } catch (e) {
        setIsLoading(false);
        setError(e instanceof Error ? e.message : "Failed to start analysis");
      }
    },
    [setCurrentRun, stopPolling, pollRunStatus]
  );

  return { triggerAnalysis, isLoading, error };
}
