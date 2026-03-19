"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Briefcase, TrendingUp, TrendingDown, Target, ShieldAlert,
  RefreshCw, CheckCircle2, XCircle, Clock,
} from "lucide-react";

interface Position {
  id: string;
  ticker: string;
  quantity: number;
  entry_price: number;
  current_price?: number;
  stop_loss_price?: number;
  take_profit_price?: number;
  exit_price?: number;
  close_reason?: string;
  status: string;
  unrealized_pnl?: number;
  realized_pnl?: number;
  opened_at: string;
  closed_at?: string;
}

interface Summary {
  open_positions: number;
  closed_positions: number;
  total_realized_pnl: number;
  total_unrealized_pnl: number;
  win_rate: number;
  avg_r_multiple: number | null;
  stop_loss_hits: number;
  take_profit_hits: number;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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

function CloseReasonBadge({ reason }: { reason?: string }) {
  if (!reason || reason === "manual") {
    return <span className="text-xs bg-secondary text-muted-foreground px-1.5 py-0.5 rounded">Manual</span>;
  }
  if (reason === "take_profit") {
    return (
      <span className="text-xs bg-green-500/15 text-green-400 border border-green-500/25 px-1.5 py-0.5 rounded flex items-center gap-1 w-fit">
        <Target className="h-3 w-3" /> TP Hit
      </span>
    );
  }
  return (
    <span className="text-xs bg-red-500/15 text-red-400 border border-red-500/25 px-1.5 py-0.5 rounded flex items-center gap-1 w-fit">
      <ShieldAlert className="h-3 w-3" /> SL Hit
    </span>
  );
}

function PnlBadge({ pnl }: { pnl: number }) {
  const positive = pnl >= 0;
  return (
    <span className={`font-semibold ${positive ? "text-green-500" : "text-red-500"}`}>
      {positive ? "+" : ""}${pnl.toFixed(2)}
    </span>
  );
}

function RProgress({ current, entry, stop, target }: {
  current?: number; entry: number; stop?: number; target?: number;
}) {
  if (!current || !stop || !target) return null;
  const risk = entry - stop;
  const reward = target - entry;
  if (risk <= 0 || reward <= 0) return null;
  // Position of current price within [stop, target] range
  const range = target - stop;
  const pct = Math.max(0, Math.min(100, ((current - stop) / range) * 100));
  const entryPct = ((entry - stop) / range) * 100;

  return (
    <div className="mt-2">
      <div className="relative h-1.5 bg-secondary rounded-full">
        {/* SL zone (red) */}
        <div className="absolute left-0 top-0 h-full rounded-l-full bg-red-500/40" style={{ width: `${entryPct}%` }} />
        {/* Reward zone (green) */}
        <div className="absolute top-0 h-full rounded-r-full bg-green-500/30" style={{ left: `${entryPct}%`, right: 0 }} />
        {/* Entry line */}
        <div className="absolute top-0 h-full w-0.5 bg-foreground/40" style={{ left: `${entryPct}%` }} />
        {/* Current price dot */}
        <div
          className={`absolute top-1/2 -translate-y-1/2 w-2.5 h-2.5 rounded-full border-2 border-background shadow ${current >= entry ? "bg-green-500" : "bg-red-500"}`}
          style={{ left: `calc(${pct}% - 5px)` }}
        />
      </div>
      <div className="flex justify-between text-xs text-muted-foreground mt-0.5">
        <span className="text-red-400">${stop.toFixed(0)} SL</span>
        <span>${entry.toFixed(0)} Entry</span>
        <span className="text-green-400">${target.toFixed(0)} TP</span>
      </div>
    </div>
  );
}

export default function PortfolioPage() {
  const [positions, setPositions] = useState<Position[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [tab, setTab] = useState<"open" | "closed">("open");

  const fetchData = useCallback(async () => {
    try {
      // Fetch all paper trades (no portfolio filter — single paper account)
      const [tradesRes, portfoliosRes] = await Promise.all([
        fetch(`${API_URL}/api/v1/trades/paper`),
        fetch(`${API_URL}/api/v1/portfolio/`),
      ]);

      if (tradesRes.ok) setPositions(await tradesRes.json());

      // Get summary from the first portfolio if it exists
      if (portfoliosRes.ok) {
        const portfolios = await portfoliosRes.json();
        if (portfolios.length > 0) {
          const sumRes = await fetch(`${API_URL}/api/v1/portfolio/${portfolios[0].id}/summary`);
          if (sumRes.ok) setSummary(await sumRes.json());
        }
      }
    } catch {
      // ignore
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30_000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const openPositions = positions.filter((p) => p.status === "open");
  const closedPositions = positions.filter((p) => p.status === "closed")
    .sort((a, b) => new Date(b.closed_at ?? b.opened_at).getTime() - new Date(a.closed_at ?? a.opened_at).getTime());

  // Compute metrics from positions if no portfolio summary
  const totalUnrealized = openPositions.reduce((s, p) => s + (p.unrealized_pnl ?? 0), 0);
  const totalRealized = summary?.total_realized_pnl
    ?? closedPositions.reduce((s, p) => s + (p.realized_pnl ?? 0), 0);
  const winRate = summary?.win_rate
    ?? (closedPositions.length > 0
      ? closedPositions.filter(p => (p.realized_pnl ?? 0) > 0).length / closedPositions.length
      : 0);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Briefcase className="h-6 w-6" />
          <h1 className="text-2xl font-bold">Paper Portfolio</h1>
        </div>
        <button
          onClick={fetchData}
          className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard
          label="Open Positions"
          value={openPositions.length}
          sub={`${totalUnrealized >= 0 ? "+" : ""}$${totalUnrealized.toFixed(0)} unrealized`}
          color={totalUnrealized >= 0 ? "text-green-500" : "text-red-500"}
        />
        <StatCard
          label="Realized P&L"
          value={`${totalRealized >= 0 ? "+" : ""}$${totalRealized.toFixed(2)}`}
          sub={`${closedPositions.length} closed trade${closedPositions.length !== 1 ? "s" : ""}`}
          color={totalRealized >= 0 ? "text-green-500" : "text-red-500"}
        />
        <StatCard
          label="Win Rate"
          value={`${(winRate * 100).toFixed(0)}%`}
          sub={
            summary
              ? `${summary.take_profit_hits} TP / ${summary.stop_loss_hits} SL`
              : `${closedPositions.filter(p => (p.realized_pnl ?? 0) > 0).length} wins`
          }
        />
        <StatCard
          label="Avg R-Multiple"
          value={summary?.avg_r_multiple != null ? `${summary.avg_r_multiple > 0 ? "+" : ""}${summary.avg_r_multiple}R` : "—"}
          sub="risk-adjusted return"
          color={
            summary?.avg_r_multiple != null
              ? summary.avg_r_multiple >= 1 ? "text-green-500" : "text-red-500"
              : ""
          }
        />
      </div>

      {/* Tabs */}
      <div className="flex border-b border-border">
        {(["open", "closed"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === t
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {t === "open" ? `Open (${openPositions.length})` : `History (${closedPositions.length})`}
          </button>
        ))}
      </div>

      {/* Open positions tab */}
      {tab === "open" && (
        isLoading ? (
          <div className="space-y-2">
            {[1, 2, 3].map((i) => <div key={i} className="h-24 bg-secondary rounded-lg animate-pulse" />)}
          </div>
        ) : openPositions.length === 0 ? (
          <div className="text-center py-16 text-muted-foreground text-sm">
            <Briefcase className="h-10 w-10 mx-auto mb-3 opacity-20" />
            No open positions. Go to the dashboard and click <strong>Paper Trade</strong> on a signal.
          </div>
        ) : (
          <div className="space-y-3">
            {openPositions.map((pos) => {
              const pnl = pos.unrealized_pnl ?? 0;
              const pnlPct = pos.current_price
                ? ((pos.current_price - pos.entry_price) / pos.entry_price * 100)
                : 0;
              return (
                <div key={pos.id} className="bg-card border border-border rounded-lg p-4 space-y-2">
                  <div className="flex items-start justify-between">
                    <div>
                      <span className="font-bold text-lg">{pos.ticker}</span>
                      <span className="text-muted-foreground text-sm ml-2">
                        {pos.quantity} shares @ ${pos.entry_price.toFixed(2)}
                      </span>
                    </div>
                    <div className="text-right">
                      <PnlBadge pnl={pnl} />
                      <p className={`text-xs ${pnlPct >= 0 ? "text-green-400" : "text-red-400"}`}>
                        {pnlPct >= 0 ? "+" : ""}{pnlPct.toFixed(2)}%
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-4 text-xs text-muted-foreground">
                    <span>Current: <strong className="text-foreground">${(pos.current_price ?? pos.entry_price).toFixed(2)}</strong></span>
                    {pos.stop_loss_price && <span className="text-red-400">SL: ${pos.stop_loss_price.toFixed(2)}</span>}
                    {pos.take_profit_price && <span className="text-green-400">TP: ${pos.take_profit_price.toFixed(2)}</span>}
                  </div>
                  <RProgress
                    current={pos.current_price}
                    entry={pos.entry_price}
                    stop={pos.stop_loss_price}
                    target={pos.take_profit_price}
                  />
                </div>
              );
            })}
          </div>
        )
      )}

      {/* Closed / history tab */}
      {tab === "closed" && (
        closedPositions.length === 0 ? (
          <div className="text-center py-16 text-muted-foreground text-sm">
            <Clock className="h-10 w-10 mx-auto mb-3 opacity-20" />
            No closed trades yet. The monitor checks open positions every 5 minutes.
          </div>
        ) : (
          <div className="space-y-2">
            {closedPositions.map((pos) => {
              const pnl = pos.realized_pnl ?? 0;
              const win = pnl > 0;
              return (
                <div key={pos.id} className="bg-card border border-border rounded-lg p-4 flex items-center justify-between gap-4">
                  <div className="flex items-center gap-3 min-w-0">
                    {win
                      ? <CheckCircle2 className="h-4 w-4 text-green-500 flex-shrink-0" />
                      : <XCircle className="h-4 w-4 text-red-500 flex-shrink-0" />
                    }
                    <div className="min-w-0">
                      <span className="font-semibold">{pos.ticker}</span>
                      <span className="text-muted-foreground text-xs ml-2">
                        {pos.quantity}sh @ ${pos.entry_price.toFixed(2)} → ${(pos.exit_price ?? pos.entry_price).toFixed(2)}
                      </span>
                      <div className="mt-0.5">
                        <CloseReasonBadge reason={pos.close_reason} />
                      </div>
                    </div>
                  </div>
                  <div className="text-right flex-shrink-0">
                    <PnlBadge pnl={pnl} />
                    {pos.closed_at && (
                      <p className="text-xs text-muted-foreground mt-0.5">
                        {new Date(pos.closed_at).toLocaleDateString()}
                      </p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )
      )}
    </div>
  );
}
