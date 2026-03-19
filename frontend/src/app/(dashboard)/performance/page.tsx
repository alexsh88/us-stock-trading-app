"use client";

import { useState, useEffect, useCallback } from "react";
import {
  BarChart3, Target, TrendingUp, TrendingDown, Activity,
  RefreshCw, AlertCircle, CheckCircle2, XCircle, Info,
} from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface BacktestSummary {
  total_signals: number;
  complete_evaluations: number;
  tp_hit_rate: number;
  sl_hit_rate: number;
  avg_r_multiple: number | null;
  direction_accuracy_1d: number | null;
  direction_accuracy_5d: number | null;
  avg_return_5d: number | null;
  message?: string;
}

interface FactorRow {
  factor: string;
  horizon_days: number;
  ic: number;
  ic_mean_30d: number | null;
  ic_ir: number | null;
  n_signals: number;
  date: string;
}

interface Outcome {
  ticker: string;
  signal_date: string;
  confidence_score: number;
  return_1d: number | null;
  return_3d: number | null;
  return_5d: number | null;
  sl_hit: boolean | null;
  tp_hit: boolean | null;
  r_multiple: number | null;
  correct_direction_1d: boolean | null;
  correct_direction_5d: boolean | null;
  is_complete: boolean;
}

function StatCard({ label, value, sub, color = "" }: {
  label: string; value: React.ReactNode; sub?: string; color?: string;
}) {
  return (
    <div className="bg-card border border-border rounded-lg p-4">
      <p className="text-xs text-muted-foreground uppercase tracking-wide mb-1">{label}</p>
      <p className={`text-2xl font-bold ${color}`}>{value}</p>
      {sub && <p className="text-xs text-muted-foreground mt-0.5">{sub}</p>}
    </div>
  );
}

function IcBar({ value, label }: { value: number | null; label: string }) {
  if (value === null) return <span className="text-muted-foreground">—</span>;
  const pct = Math.max(0, Math.min(100, ((value + 1) / 2) * 100)); // map [-1,1] to [0,100]
  const color = value > 0.05 ? "bg-green-500" : value < -0.05 ? "bg-red-500" : "bg-yellow-500";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-secondary rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className={`text-xs font-mono w-12 text-right ${value > 0 ? "text-green-400" : "text-red-400"}`}>
        {value > 0 ? "+" : ""}{(value * 100).toFixed(1)}%
      </span>
    </div>
  );
}

const FACTOR_LABELS: Record<string, string> = {
  technical_score: "Technical",
  fundamental_score: "Fundamental",
  sentiment_score: "Sentiment",
  catalyst_score: "Catalyst",
  confidence_score: "Confidence",
};

export default function PerformancePage() {
  const [summary, setSummary] = useState<BacktestSummary | null>(null);
  const [factors, setFactors] = useState<FactorRow[]>([]);
  const [outcomes, setOutcomes] = useState<Outcome[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [horizon, setHorizon] = useState(3);

  const fetchData = useCallback(async () => {
    try {
      const [sumRes, icRes, outRes] = await Promise.all([
        fetch(`${API_URL}/api/v1/backtest/summary`),
        fetch(`${API_URL}/api/v1/backtest/factor-ic?horizon=${horizon}&days=60`),
        fetch(`${API_URL}/api/v1/backtest/outcomes?limit=30&complete_only=false`),
      ]);
      if (sumRes.ok) setSummary(await sumRes.json());
      if (icRes.ok) {
        const data = await icRes.json();
        setFactors(data.factors ?? []);
      }
      if (outRes.ok) setOutcomes(await outRes.json());
    } finally {
      setIsLoading(false);
    }
  }, [horizon]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const noData = !summary || summary.total_signals === 0;
  const pending = (summary?.total_signals ?? 0) > 0 && (summary?.complete_evaluations ?? 0) === 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BarChart3 className="h-6 w-6" />
          <h1 className="text-2xl font-bold">Signal Performance</h1>
        </div>
        <button
          onClick={fetchData}
          className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh
        </button>
      </div>

      {noData ? (
        <div className="text-center py-20 text-muted-foreground">
          <Activity className="h-12 w-12 mx-auto mb-3 opacity-20" />
          <p className="font-medium">No signals tracked yet</p>
          <p className="text-sm mt-1">Run an analysis to start tracking signal outcomes.</p>
        </div>
      ) : (
        <>
          {/* Pending banner */}
          {pending && (
            <div className="flex items-center gap-2 bg-yellow-500/10 border border-yellow-500/20 rounded-lg px-4 py-3 text-sm text-yellow-400">
              <RefreshCw className="h-4 w-4 flex-shrink-0" />
              <span>
                <strong>{summary?.total_signals}</strong> signal{(summary?.total_signals ?? 0) !== 1 ? "s" : ""} tracked —
                waiting for 5 trading days of data. The nightly backtest runs at 5:30 PM ET.
              </span>
            </div>
          )}

          {/* Summary stats */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <StatCard
              label="Signals Tracked"
              value={summary?.total_signals ?? "—"}
              sub={`${summary?.complete_evaluations ?? 0} fully evaluated`}
            />
            <StatCard
              label="TP Hit Rate"
              value={summary?.tp_hit_rate != null ? `${(summary.tp_hit_rate * 100).toFixed(0)}%` : "—"}
              sub="take profit reached"
              color={summary?.tp_hit_rate != null && summary.tp_hit_rate > 0.4 ? "text-green-500" : "text-muted-foreground"}
            />
            <StatCard
              label="Avg R-Multiple"
              value={summary?.avg_r_multiple != null ? `${summary.avg_r_multiple > 0 ? "+" : ""}${summary.avg_r_multiple}R` : "—"}
              sub="realized vs initial risk"
              color={summary?.avg_r_multiple != null
                ? summary.avg_r_multiple >= 1 ? "text-green-500" : "text-red-500"
                : ""}
            />
            <StatCard
              label="5-Day Direction"
              value={summary?.direction_accuracy_5d != null ? `${(summary.direction_accuracy_5d * 100).toFixed(0)}%` : "—"}
              sub="correct price direction"
              color={summary?.direction_accuracy_5d != null
                ? summary.direction_accuracy_5d >= 0.55 ? "text-green-500" : "text-red-500"
                : ""}
            />
          </div>

          {/* Factor IC */}
          <div className="bg-card border border-border rounded-lg p-5">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="font-semibold">Factor Information Coefficient</h2>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Spearman rank correlation between each agent&apos;s score and actual forward return.
                  Higher = more predictive.
                </p>
              </div>
              <select
                value={horizon}
                onChange={(e) => setHorizon(Number(e.target.value))}
                className="text-xs bg-secondary border border-border rounded px-2 py-1"
              >
                <option value={1}>1-day horizon</option>
                <option value={2}>2-day horizon</option>
                <option value={3}>3-day horizon</option>
                <option value={5}>5-day horizon</option>
              </select>
            </div>

            {factors.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-6">
                IC analysis requires at least 5 completed signal evaluations.
              </p>
            ) : (
              <div className="space-y-3">
                {factors.map((row) => (
                  <div key={row.factor} className="flex items-center gap-3">
                    <span className="text-sm w-28 flex-shrink-0 text-muted-foreground">
                      {FACTOR_LABELS[row.factor] ?? row.factor}
                    </span>
                    <div className="flex-1">
                      <IcBar value={row.ic_mean_30d ?? row.ic} label={row.factor} />
                    </div>
                    <div className="text-xs text-muted-foreground w-20 text-right flex-shrink-0">
                      {row.ic_ir != null && (
                        <span className={row.ic_ir > 0.5 ? "text-green-400" : ""}>
                          IR: {row.ic_ir.toFixed(2)}
                        </span>
                      )}
                    </div>
                    <span className="text-xs text-muted-foreground w-16 text-right flex-shrink-0">
                      n={row.n_signals}
                    </span>
                  </div>
                ))}
              </div>
            )}

            <div className="mt-4 flex items-start gap-2 text-xs text-muted-foreground bg-secondary/50 rounded p-2">
              <Info className="h-3.5 w-3.5 flex-shrink-0 mt-0.5" />
              <span>
                IC &gt; +5% = useful signal. IC &gt; +10% = strong signal. These weights update the composite scoring
                automatically each night via the backtest task.
              </span>
            </div>
          </div>

          {/* Recent outcomes table */}
          <div className="bg-card border border-border rounded-lg p-5">
            <h2 className="font-semibold mb-3">Recent Signal Outcomes</h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-muted-foreground border-b border-border">
                    <th className="text-left pb-2 font-medium">Ticker</th>
                    <th className="text-left pb-2 font-medium">Date</th>
                    <th className="text-right pb-2 font-medium">Conf.</th>
                    <th className="text-right pb-2 font-medium">1d</th>
                    <th className="text-right pb-2 font-medium">3d</th>
                    <th className="text-right pb-2 font-medium">5d</th>
                    <th className="text-center pb-2 font-medium">SL/TP</th>
                    <th className="text-right pb-2 font-medium">R</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {outcomes.map((o, i) => (
                    <tr key={i} className={`${!o.is_complete ? "opacity-50" : ""}`}>
                      <td className="py-2 font-semibold">{o.ticker}</td>
                      <td className="py-2 text-muted-foreground text-xs">
                        {new Date(o.signal_date).toLocaleDateString()}
                      </td>
                      <td className="py-2 text-right">{(o.confidence_score * 100).toFixed(0)}%</td>
                      <td className={`py-2 text-right font-mono text-xs ${o.return_1d != null ? (o.return_1d >= 0 ? "text-green-400" : "text-red-400") : "text-muted-foreground"}`}>
                        {o.return_1d != null ? `${o.return_1d >= 0 ? "+" : ""}${(o.return_1d * 100).toFixed(1)}%` : "—"}
                      </td>
                      <td className={`py-2 text-right font-mono text-xs ${o.return_3d != null ? (o.return_3d >= 0 ? "text-green-400" : "text-red-400") : "text-muted-foreground"}`}>
                        {o.return_3d != null ? `${o.return_3d >= 0 ? "+" : ""}${(o.return_3d * 100).toFixed(1)}%` : "—"}
                      </td>
                      <td className={`py-2 text-right font-mono text-xs ${o.return_5d != null ? (o.return_5d >= 0 ? "text-green-400" : "text-red-400") : "text-muted-foreground"}`}>
                        {o.return_5d != null ? `${o.return_5d >= 0 ? "+" : ""}${(o.return_5d * 100).toFixed(1)}%` : "—"}
                      </td>
                      <td className="py-2 text-center">
                        {o.tp_hit ? (
                          <span className="text-xs text-green-400 bg-green-500/15 px-1.5 py-0.5 rounded">TP</span>
                        ) : o.sl_hit ? (
                          <span className="text-xs text-red-400 bg-red-500/15 px-1.5 py-0.5 rounded">SL</span>
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </td>
                      <td className={`py-2 text-right font-mono text-xs ${o.r_multiple != null ? (o.r_multiple >= 0 ? "text-green-400" : "text-red-400") : "text-muted-foreground"}`}>
                        {o.r_multiple != null ? `${o.r_multiple >= 0 ? "+" : ""}${o.r_multiple.toFixed(2)}R` : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {outcomes.some(o => !o.is_complete) && (
              <p className="text-xs text-muted-foreground mt-2 opacity-60">
                Faded rows are pending — waiting for 5 trading days to elapse.
              </p>
            )}
          </div>
        </>
      )}
    </div>
  );
}
