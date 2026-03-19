"use client";

import { useState, useEffect } from "react";
import { TrendingUp, RefreshCw, AlertCircle, History } from "lucide-react";
import { SignalCard } from "@/components/signals/SignalCard";
import { useAnalysisRun } from "@/hooks/useAnalysisRun";
import { useTradingStore } from "@/store/trading-store";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface RunSummary {
  id: string;
  status: string;
  signals_generated: number | null;
  tickers_screened: number | null;
  mode: string;
  created_at: string;
}

export default function DashboardPage() {
  const { signals, currentRun, setSignals, setCurrentRun } = useTradingStore();
  const { triggerAnalysis, isLoading, error } = useAnalysisRun();
  const [topN, setTopN] = useState(5);
  const [history, setHistory] = useState<RunSummary[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  // Auto-load latest signals on mount
  useEffect(() => {
    fetch(`${API_URL}/api/v1/analysis/latest`)
      .then((r) => r.ok ? r.json() : null)
      .then(async (run) => {
        if (!run || run.status !== "completed") return;
        setCurrentRun(run);
        setSelectedRunId(run.id);
        const sigRes = await fetch(`${API_URL}/api/v1/analysis/${run.id}/signals`);
        if (sigRes.ok) setSignals(await sigRes.json());
      })
      .catch(() => {});
  }, [setSignals, setCurrentRun]);

  // Load run history
  useEffect(() => {
    fetch(`${API_URL}/api/v1/analysis/history?limit=10`)
      .then((r) => r.ok ? r.json() : [])
      .then(setHistory)
      .catch(() => {});
  }, [currentRun]); // refresh when a new run completes

  const loadRun = async (runId: string) => {
    setSelectedRunId(runId);
    const [runRes, sigRes] = await Promise.all([
      fetch(`${API_URL}/api/v1/analysis/${runId}`),
      fetch(`${API_URL}/api/v1/analysis/${runId}/signals`),
    ]);
    if (runRes.ok) setCurrentRun(await runRes.json());
    if (sigRes.ok) setSignals(await sigRes.json());
  };

  const formatDate = (iso: string) => {
    const d = new Date(iso);
    return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  };

  const completedHistory = history.filter((r) => r.status === "completed");

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <TrendingUp className="h-6 w-6 text-primary" />
            Today&apos;s Top Picks
          </h1>
          <p className="text-muted-foreground text-sm mt-1">
            AI-powered trading signals updated daily at 9:00 AM ET
          </p>
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          {/* Run history selector */}
          {completedHistory.length > 1 && (
            <div className="flex items-center gap-2">
              <History className="h-4 w-4 text-muted-foreground" />
              <select
                value={selectedRunId ?? ""}
                onChange={(e) => loadRun(e.target.value)}
                className="bg-secondary text-foreground rounded-md px-3 py-2 text-sm border border-border"
              >
                {completedHistory.map((r) => (
                  <option key={r.id} value={r.id}>
                    {formatDate(r.created_at)} — {r.signals_generated ?? 0} signals ({r.mode})
                  </option>
                ))}
              </select>
            </div>
          )}

          <select
            value={topN}
            onChange={(e) => setTopN(Number(e.target.value))}
            className="bg-secondary text-foreground rounded-md px-3 py-2 text-sm border border-border"
          >
            {[3, 5, 10, 15, 20].map((n) => (
              <option key={n} value={n}>Top {n}</option>
            ))}
          </select>

          <button
            onClick={() => triggerAnalysis(topN)}
            disabled={isLoading}
            className="flex items-center gap-2 bg-primary text-primary-foreground px-4 py-2 rounded-md text-sm font-medium hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <RefreshCw className={`h-4 w-4 ${isLoading ? "animate-spin" : ""}`} />
            {isLoading ? "Analyzing..." : "Run Analysis"}
          </button>
        </div>
      </div>

      {/* Status banner */}
      {currentRun && (
        <div className="bg-secondary rounded-lg p-3 flex items-center gap-3 text-sm">
          {currentRun.status === "running" && (
            <>
              <RefreshCw className="h-4 w-4 animate-spin text-primary" />
              <span>Analysis running — screened {currentRun.tickers_screened ?? 0} tickers...</span>
            </>
          )}
          {currentRun.status === "completed" && (
            <>
              <TrendingUp className="h-4 w-4 text-green-500" />
              <span>
                {formatDate(currentRun.created_at)} — {currentRun.signals_generated ?? 0} signals from {currentRun.tickers_screened ?? 0} screened ({currentRun.mode})
              </span>
            </>
          )}
          {currentRun.status === "failed" && (
            <>
              <AlertCircle className="h-4 w-4 text-destructive" />
              <span className="text-destructive">{currentRun.error_message ?? "Analysis failed"}</span>
            </>
          )}
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="bg-destructive/10 border border-destructive/20 rounded-lg p-3 text-sm text-destructive flex items-center gap-2">
          <AlertCircle className="h-4 w-4" />
          {error}
        </div>
      )}

      {/* Signal cards */}
      {signals.length > 0 ? (
        <div className="grid gap-4 sm:grid-cols-1 lg:grid-cols-2 xl:grid-cols-3">
          {signals.map((signal) => (
            <SignalCard key={signal.id} signal={signal} />
          ))}
        </div>
      ) : (
        <div className="text-center py-20 text-muted-foreground">
          <TrendingUp className="h-12 w-12 mx-auto mb-4 opacity-20" />
          <p className="text-lg font-medium">No signals yet</p>
          <p className="text-sm mt-1">Click &quot;Run Analysis&quot; to generate today&apos;s trading picks</p>
        </div>
      )}
    </div>
  );
}
