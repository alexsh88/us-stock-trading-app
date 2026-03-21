"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { Search, TrendingUp, TrendingDown, Minus, Info, AlertTriangle, RefreshCw, XCircle } from "lucide-react";
import dynamic from "next/dynamic";
import { AgentScoreBreakdown } from "@/components/signals/AgentScoreBreakdown";
import type { TradeSignal, TechnicalIndicators } from "@/store/trading-store";

const CandlestickChart = dynamic(
  () => import("@/components/charts/CandlestickChart"),
  { ssr: false, loading: () => <div className="h-96 bg-secondary rounded-lg animate-pulse" /> }
);

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const POLL_MS = 3_000;
const RECENT_KEY = "lookup_recent_tickers";

// ── helpers (copied from signal detail page) ─────────────────────────────────

function formatStopReason(method: string | null | undefined): { label: string; detail: string } {
  if (!method) return { label: "ATR-based", detail: "2× average daily range below entry" };
  if (method.startsWith("Fib")) {
    const level = method.match(/Fib(\d+\.?\d*)/)?.[1];
    const price = method.match(/\$([\d.]+)/)?.[1];
    return {
      label: `Fib ${level}% retracement`,
      detail: `Price is above the ${level}% retracement${price ? ` at $${price}` : ""} — stop just below this natural support zone`,
    };
  }
  if (method.startsWith("Chandelier")) {
    return { label: "Chandelier Exit", detail: "Highest close of last 10 bars minus 2.5× ATR — trails up with price automatically" };
  }
  if (method.startsWith("ATR")) {
    const mult = method.match(/ATR-([\d.]+)x/)?.[1] ?? "2";
    return { label: `ATR ${mult}× stop`, detail: `${mult}× the average true range below entry` };
  }
  if (method.startsWith("AVWAP")) {
    const price = method.match(/\$([\d.]+)/)?.[1];
    return { label: "Anchored VWAP", detail: `VWAP anchored to the most recent swing low${price ? ` at $${price}` : ""}` };
  }
  const patMatch = method.match(/^(.+)-invalidation\(str=([\d.]+)\)$/);
  if (patMatch) {
    const patName = patMatch[1].replace(/_/g, " ");
    const str = parseFloat(patMatch[2]);
    return { label: `${patName} invalidation`, detail: `Below the pattern lows (strength ${(str * 100).toFixed(0)}%)` };
  }
  return { label: method, detail: "" };
}

function formatTargetReason(method: string | null | undefined, rr: number | null | undefined): { label: string; detail: string } {
  const rrStr = rr?.toFixed(1) ?? "2.0";
  if (!method || method === "min_rr_floor") return { label: "R:R floor", detail: `No stronger level found — minimum ${rrStr}× reward-to-risk` };
  if (method.startsWith("pattern-")) {
    const name = method.replace("pattern-", "").replace(/_/g, " ");
    return { label: `${name} projection`, detail: "Classic measured move — pattern height projected above breakout" };
  }
  if (method === "Fib127") return { label: "Fib 1.272× extension", detail: "First Fibonacci extension — common institutional take-profit zone" };
  if (method === "Fib162") return { label: "Fib 1.618× extension", detail: "Golden ratio extension — strong institutional target" };
  if (method === "WeeklyR1") return { label: "Weekly R1 pivot", detail: "First weekly resistance pivot" };
  if (method === "WeeklyR2") return { label: "Weekly R2 pivot", detail: "Second weekly resistance — extended target for strong trends" };
  if (method === "VolumeProfileVAH") return { label: "Volume Profile VAH", detail: "Value Area High — upper boundary of 70% volume zone" };
  if (method === "ClusteredResist") return { label: "Clustered resistance", detail: "Multiple prior pivot highs in this zone" };
  if (method === "SwingResist") return { label: "Swing resistance", detail: "Most recent pivot high on the daily chart" };
  return { label: method, detail: "" };
}

// ── sub-components ────────────────────────────────────────────────────────────

function LevelCard({
  label, price, subLabel, reason, colorClass, borderClass, dimmed,
}: {
  label: string; price: string; subLabel: string;
  reason: { label: string; detail: string };
  colorClass: string; borderClass: string;
  dimmed?: boolean;
}) {
  return (
    <div className={`bg-card ${borderClass} rounded-lg p-4 ${dimmed ? "opacity-60" : ""}`}>
      <p className={`text-xs uppercase tracking-wide mb-1 ${colorClass}`}>{label}</p>
      <p className={`text-xl font-bold mb-1 ${colorClass}`}>{price}</p>
      <p className="text-xs text-muted-foreground mb-2">{subLabel}</p>
      <div className="border-t border-border pt-2 space-y-1">
        <div className="flex items-center gap-1">
          <Info className="h-3 w-3 text-muted-foreground shrink-0" />
          <span className="text-xs font-medium text-foreground">{reason.label}</span>
        </div>
        {reason.detail && (
          <p className="text-xs text-muted-foreground leading-relaxed pl-4">{reason.detail}</p>
        )}
      </div>
    </div>
  );
}

function IndicatorPill({ label, value, positive }: { label: string; value: string; positive?: boolean | null }) {
  const color = positive === true
    ? "bg-green-500/10 border-green-500/20 text-green-400"
    : positive === false
    ? "bg-red-500/10 border-red-500/20 text-red-400"
    : "bg-secondary border-border text-muted-foreground";
  return (
    <div className={`border rounded-lg px-3 py-2 text-center ${color}`}>
      <p className="text-xs opacity-70 mb-0.5">{label}</p>
      <p className="text-sm font-semibold">{value}</p>
    </div>
  );
}

function RegimeBadge({ regime }: { regime: string | null | undefined }) {
  if (!regime) return null;
  const styles: Record<string, string> = {
    trending: "bg-green-500/20 text-green-400 border border-green-500/30",
    neutral:  "bg-yellow-500/20 text-yellow-400 border border-yellow-500/30",
    choppy:   "bg-red-500/20 text-red-400 border border-red-500/30",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded font-medium ${styles[regime] ?? "bg-secondary text-muted-foreground"}`}>
      {regime}
    </span>
  );
}

function IndicatorsPanel({ ind }: { ind: TechnicalIndicators }) {
  return (
    <div className="bg-card border border-border rounded-lg p-4 space-y-4">
      <h2 className="font-semibold">Technical Indicators</h2>
      <div className="flex flex-wrap gap-2 items-center">
        {ind.adx != null && (
          <span className="text-sm text-muted-foreground">
            ADX <span className="text-foreground font-medium">{ind.adx.toFixed(1)}</span>
          </span>
        )}
        <RegimeBadge regime={ind.regime} />
        {ind.mtf_aligned != null && (
          <span className={`text-xs px-2 py-0.5 rounded font-medium border ${ind.mtf_aligned ? "bg-green-500/20 text-green-400 border-green-500/30" : "bg-secondary text-muted-foreground border-border"}`}>
            MTF {ind.mtf_aligned ? "aligned ✓" : "misaligned"}
          </span>
        )}
        {ind.bb_squeeze != null && (
          <span className={`text-xs px-2 py-0.5 rounded font-medium border ${
            ind.squeeze_released ? "bg-green-500/20 text-green-400 border-green-500/30"
            : ind.bb_squeeze ? "bg-yellow-500/20 text-yellow-400 border-yellow-500/30"
            : "bg-secondary text-muted-foreground border-border"
          }`}>
            {ind.squeeze_released ? "Squeeze released ⚡" : ind.bb_squeeze ? "BB Squeeze 🔄" : "No squeeze"}
          </span>
        )}
      </div>
      <div className="grid grid-cols-3 sm:grid-cols-5 gap-2">
        {ind.rsi != null && (
          <IndicatorPill label="RSI" value={ind.rsi.toFixed(1)}
            positive={ind.rsi < 70 && ind.rsi > 30 ? null : ind.rsi <= 30 ? true : false} />
        )}
        {ind.macd_signal && (
          <IndicatorPill label="MACD" value={ind.macd_signal} positive={ind.macd_signal === "bullish"} />
        )}
        {ind.vwap_relation && (
          <IndicatorPill label="VWAP" value={ind.vwap_relation} positive={ind.vwap_relation === "above"} />
        )}
        {ind.vol_ratio != null && (
          <IndicatorPill label="Vol Ratio" value={`${ind.vol_ratio.toFixed(1)}×`}
            positive={ind.vol_ratio >= 1.5 ? true : ind.vol_ratio < 0.7 ? false : null} />
        )}
        {ind.breakout_score != null && (
          <IndicatorPill label="Breakout" value={`${ind.breakout_score}/3`}
            positive={ind.breakout_score >= 2 ? true : ind.breakout_score === 0 ? false : null} />
        )}
      </div>
    </div>
  );
}

function WhyNotCard({ signal }: { signal: TradeSignal }) {
  const scores = signal.agent_scores;
  const weak: string[] = [];
  if (scores.technical != null && scores.technical < 0.55) weak.push(`Technical: ${(scores.technical * 100).toFixed(0)}% — ${signal.indicators?.regime === "choppy" ? "choppy regime, no breakout confirmation" : "below technical threshold"}`);
  if (scores.fundamental != null && scores.fundamental < 0.55) weak.push(`Fundamental: ${(scores.fundamental * 100).toFixed(0)}% — weak fundamentals or missing data`);
  if (scores.sentiment != null && scores.sentiment < 0.55) weak.push(`Sentiment: ${(scores.sentiment * 100).toFixed(0)}% — negative or neutral news/Reddit sentiment`);
  if (scores.catalyst != null && scores.catalyst < 0.55) weak.push(`Catalyst: ${(scores.catalyst * 100).toFixed(0)}% — no upcoming catalyst or recent negative events`);
  if (weak.length === 0) weak.push("Confidence below the minimum threshold (60%) — setup not strong enough for a trade");

  const lowestEntry = scores.technical ?? scores.fundamental ?? scores.sentiment ?? scores.catalyst;
  const wouldChange = lowestEntry != null && lowestEntry < 0.4 ? "A meaningful catalyst, volume expansion, or regime shift toward trending would be needed." : "A few more confirming signals (volume, MTF alignment, or catalyst) could push this over the threshold.";

  return (
    <div className="space-y-4">
      <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-4 space-y-3">
        <div className="flex items-center gap-2 font-medium text-yellow-400">
          <AlertTriangle className="h-4 w-4 flex-shrink-0" />
          Why not a trade right now?
        </div>
        {signal.reasoning && (
          <p className="text-sm text-foreground border-l-2 border-yellow-500/40 pl-3 italic">
            {signal.reasoning}
          </p>
        )}
        <ul className="space-y-1.5">
          {weak.map((w, i) => (
            <li key={i} className="flex items-start gap-2 text-sm text-foreground">
              <span className="text-yellow-400 mt-0.5 shrink-0">•</span>
              {w}
            </li>
          ))}
        </ul>
      </div>

      <div className="bg-card border border-border rounded-lg p-4 text-sm text-muted-foreground">
        <span className="font-medium text-foreground">What would need to change: </span>
        {wouldChange}
      </div>

      {signal.entry_price && signal.stop_loss_price && signal.take_profit_price && (
        <div className="bg-card border border-border rounded-lg p-4 opacity-60">
          <div className="flex items-center gap-2 text-xs text-muted-foreground mb-3">
            <AlertTriangle className="h-3 w-3 text-yellow-400" />
            Hypothetical levels if you were to trade anyway (not a recommendation)
          </div>
          <div className="grid grid-cols-3 gap-3 text-sm">
            <div>
              <p className="text-xs text-muted-foreground mb-0.5">Entry</p>
              <p className="font-bold">${signal.entry_price.toFixed(2)}</p>
            </div>
            <div>
              <p className="text-xs text-red-400 mb-0.5">Stop</p>
              <p className="font-bold text-red-400">${signal.stop_loss_price.toFixed(2)}</p>
            </div>
            <div>
              <p className="text-xs text-green-400 mb-0.5">Target</p>
              <p className="font-bold text-green-400">${signal.take_profit_price.toFixed(2)}</p>
            </div>
          </div>
          {signal.risk_reward_ratio != null && (
            <p className="text-xs text-muted-foreground mt-2">
              R:R {signal.risk_reward_ratio.toFixed(1)}× — {signal.risk_reward_ratio < 2 ? "below minimum 2:1 required" : "acceptable ratio but setup too weak"}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ── state types ───────────────────────────────────────────────────────────────

type PageState = "idle" | "running" | "done" | "error";

// ── main page ─────────────────────────────────────────────────────────────────

export default function LookupPage() {
  const [pageState, setPageState] = useState<PageState>("idle");
  const [ticker, setTicker] = useState("");
  const [mode, setMode] = useState<"swing" | "intraday">("swing");
  const [signal, setSignal] = useState<TradeSignal | null>(null);
  const [noSignalTicker, setNoSignalTicker] = useState<string>("");
  const [errorMsg, setErrorMsg] = useState<string>("");
  const [recent, setRecent] = useState<string[]>([]);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(RECENT_KEY);
      if (stored) setRecent(JSON.parse(stored));
    } catch {}
  }, []);

  const saveRecent = useCallback((t: string) => {
    setRecent((prev) => {
      const next = [t, ...prev.filter((x) => x !== t)].slice(0, 5);
      try { localStorage.setItem(RECENT_KEY, JSON.stringify(next)); } catch {}
      return next;
    });
  }, []);

  const stopPolling = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }, []);

  const handleAnalyze = useCallback(async (tickerOverride?: string) => {
    const t = (tickerOverride ?? ticker).toUpperCase().trim();
    if (!t || !/^[A-Z]{1,6}$/.test(t)) return;

    setPageState("running");
    setSignal(null);
    setNoSignalTicker("");
    setErrorMsg("");
    stopPolling();
    saveRecent(t);

    try {
      const res = await fetch(`${API_URL}/api/v1/analysis/single`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker: t, mode }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const run = await res.json();

      pollRef.current = setInterval(async () => {
        try {
          const statusRes = await fetch(`${API_URL}/api/v1/analysis/${run.id}`);
          if (!statusRes.ok) return;
          const updated = await statusRes.json();

          if (updated.status.toLowerCase() === "completed") {
            stopPolling();
            const sigRes = await fetch(`${API_URL}/api/v1/analysis/${run.id}/signals`);
            if (sigRes.ok) {
              const signals: TradeSignal[] = await sigRes.json();
              if (signals.length > 0) {
                setSignal(signals[0]);
              } else {
                setNoSignalTicker(t);
              }
            } else {
              setNoSignalTicker(t);
            }
            setPageState("done");
          } else if (updated.status.toLowerCase() === "failed") {
            stopPolling();
            setErrorMsg(updated.error_message ?? "Analysis failed");
            setPageState("error");
          }
        } catch {}
      }, POLL_MS);
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : "Failed to start analysis");
      setPageState("error");
    }
  }, [ticker, mode, stopPolling, saveRecent]);

  const reset = useCallback(() => {
    stopPolling();
    setPageState("idle");
    setSignal(null);
    setNoSignalTicker("");
    setErrorMsg("");
  }, [stopPolling]);

  // ── idle ──────────────────────────────────────────────────────────────────

  if (pageState === "idle") {
    return (
      <div className="max-w-xl mx-auto pt-12 space-y-6">
        <div className="text-center space-y-2">
          <div className="inline-flex items-center justify-center h-12 w-12 rounded-full bg-primary/10 text-primary mb-2">
            <Search className="h-6 w-6" />
          </div>
          <h1 className="text-2xl font-bold">Quick Analysis</h1>
          <p className="text-muted-foreground text-sm">Enter any ticker to get a full AI breakdown — buy, skip, or sell — independent of the batch pipeline.</p>
        </div>

        <div className="bg-card border border-border rounded-xl p-6 space-y-4">
          <div className="space-y-2">
            <label className="text-xs text-muted-foreground uppercase tracking-wide">Ticker</label>
            <input
              className="w-full bg-secondary border border-border rounded-lg px-4 py-3 text-xl font-bold tracking-widest uppercase placeholder:text-muted-foreground/50 focus:outline-none focus:ring-2 focus:ring-primary/40"
              placeholder="NVDA"
              maxLength={6}
              value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
              onKeyDown={(e) => e.key === "Enter" && handleAnalyze()}
            />
          </div>

          <div className="space-y-2">
            <label className="text-xs text-muted-foreground uppercase tracking-wide">Mode</label>
            <div className="flex gap-2">
              {(["swing", "intraday"] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => setMode(m)}
                  className={`flex-1 py-2 rounded-lg text-sm font-medium border transition-colors ${
                    mode === m
                      ? "bg-primary text-primary-foreground border-primary"
                      : "bg-secondary text-muted-foreground border-border hover:text-foreground"
                  }`}
                >
                  {m.charAt(0).toUpperCase() + m.slice(1)}
                </button>
              ))}
            </div>
          </div>

          <button
            onClick={() => handleAnalyze()}
            disabled={!ticker.trim()}
            className="w-full py-3 rounded-lg bg-primary text-primary-foreground font-semibold hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Analyze
          </button>
        </div>

        {recent.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Recent</p>
            <div className="flex flex-wrap gap-2">
              {recent.map((t) => (
                <button
                  key={t}
                  onClick={() => { setTicker(t); handleAnalyze(t); }}
                  className="px-3 py-1.5 rounded-full bg-secondary border border-border text-sm font-mono font-medium hover:bg-primary/10 hover:border-primary/30 transition-colors"
                >
                  {t}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  }

  // ── running ───────────────────────────────────────────────────────────────

  if (pageState === "running") {
    return (
      <div className="max-w-xl mx-auto pt-24 text-center space-y-6">
        <div className="inline-flex items-center justify-center h-16 w-16 rounded-full bg-primary/10 text-primary">
          <RefreshCw className="h-8 w-8 animate-spin" />
        </div>
        <div>
          <p className="text-xl font-bold">Analyzing {ticker || "…"}</p>
          <p className="text-muted-foreground text-sm mt-1">Running full AI pipeline (~60–90 seconds)</p>
        </div>
        <div className="flex justify-center gap-2 text-sm text-muted-foreground">
          <span className="animate-pulse">Screening → Agents → Synthesis</span>
        </div>
        <button onClick={reset} className="text-xs text-muted-foreground hover:text-foreground underline">Cancel</button>
      </div>
    );
  }

  // ── error ─────────────────────────────────────────────────────────────────

  if (pageState === "error") {
    return (
      <div className="max-w-xl mx-auto pt-24 text-center space-y-6">
        <div className="inline-flex items-center justify-center h-16 w-16 rounded-full bg-red-500/10 text-red-400">
          <XCircle className="h-8 w-8" />
        </div>
        <div>
          <p className="text-xl font-bold text-red-400">Analysis Failed</p>
          {errorMsg && <p className="text-muted-foreground text-sm mt-1">{errorMsg}</p>}
        </div>
        <div className="flex gap-3 justify-center">
          <button onClick={() => handleAnalyze()} className="px-5 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90">
            Retry
          </button>
          <button onClick={reset} className="px-5 py-2 rounded-lg bg-secondary border border-border text-sm font-medium hover:bg-secondary/80">
            Back
          </button>
        </div>
      </div>
    );
  }

  // ── done ──────────────────────────────────────────────────────────────────

  const displayTicker = signal?.ticker ?? noSignalTicker;
  const decision = signal?.decision ?? "SKIP";
  const isBuy = decision === "BUY";
  const isSell = decision === "SELL";
  const isSkip = !isBuy && !isSell;

  const decisionColor = isBuy ? "text-green-500" : isSell ? "text-red-500" : "text-yellow-500";
  const DecisionIcon = isBuy ? TrendingUp : isSell ? TrendingDown : Minus;
  const badgeBg = isBuy ? "bg-green-500/20 text-green-400 border-green-500/30"
    : isSell ? "bg-red-500/20 text-red-400 border-red-500/30"
    : "bg-yellow-500/20 text-yellow-400 border-yellow-500/30";
  const decisionLabel = isBuy ? "BUY" : isSell ? "SELL" : "NOT NOW";

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-3">
            {displayTicker}
            <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-semibold border ${badgeBg}`}>
              <DecisionIcon className={`h-4 w-4 ${decisionColor}`} />
              {decisionLabel}
            </span>
          </h1>
          {signal && (
            <p className="text-muted-foreground text-sm mt-1">
              Confidence: {(signal.confidence_score * 100).toFixed(0)}% · {signal.trading_mode} mode
            </p>
          )}
          {!signal && (
            <p className="text-muted-foreground text-sm mt-1">
              Pipeline ran but this ticker did not meet the signal threshold
            </p>
          )}
        </div>
        <button
          onClick={reset}
          className="shrink-0 px-4 py-2 rounded-lg bg-secondary border border-border text-sm font-medium hover:bg-secondary/80 transition-colors"
        >
          Analyze another
        </button>
      </div>

      {/* Confidence bar */}
      {signal && (
        <div className="bg-card border border-border rounded-lg p-4">
          <div className="flex justify-between text-sm mb-2">
            <span className="text-muted-foreground">Overall confidence</span>
            <span className="font-semibold">{(signal.confidence_score * 100).toFixed(0)}%</span>
          </div>
          <div className="h-2 bg-secondary rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full ${isBuy ? "bg-green-500" : isSell ? "bg-red-500" : "bg-yellow-500"}`}
              style={{ width: `${(signal.confidence_score * 100).toFixed(0)}%` }}
            />
          </div>
          <p className="text-xs text-muted-foreground mt-1.5">Threshold: 60% · Signals above 70% are highest conviction</p>
        </div>
      )}

      {/* Chart — always shown */}
      <div className="bg-card border border-border rounded-lg p-4">
        <CandlestickChart
          ticker={displayTicker}
          entryPrice={isBuy && signal ? signal.entry_price : undefined}
          stopLossPrice={isBuy && signal ? signal.stop_loss_price : undefined}
          takeProfitPrice={isBuy && signal ? signal.take_profit_price : undefined}
        />
      </div>

      {/* BUY: price levels */}
      {isBuy && signal && (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="bg-card border border-border rounded-lg p-4">
              <p className="text-xs text-muted-foreground uppercase tracking-wide mb-1">Entry</p>
              <p className="text-xl font-bold text-foreground">${signal.entry_price?.toFixed(2)}</p>
              <p className="text-xs text-muted-foreground mt-1">{signal.trading_mode} trade</p>
            </div>
            <LevelCard
              label="Stop Loss"
              price={`$${signal.stop_loss_price?.toFixed(2)}`}
              subLabel={`−${signal.stop_loss_price && signal.entry_price ? ((signal.entry_price - signal.stop_loss_price) / signal.entry_price * 100).toFixed(1) : "?"}% from entry`}
              reason={formatStopReason(signal.indicators?.stop_loss_method ?? signal.stop_loss_method)}
              colorClass="text-red-400"
              borderClass="border border-red-500/20"
            />
            <LevelCard
              label="Target 1 (T1)"
              price={`$${signal.take_profit_price?.toFixed(2)}`}
              subLabel={`R:R ${signal.risk_reward_ratio?.toFixed(1)}× · close 50%`}
              reason={formatTargetReason(signal.indicators?.target_method, signal.risk_reward_ratio)}
              colorClass="text-green-400"
              borderClass="border border-green-500/20"
            />
          </div>

          {signal.take_profit_price_2 && (
            <div className="bg-card border border-green-500/10 rounded-lg p-4 flex items-center justify-between">
              <div>
                <p className="text-xs text-muted-foreground uppercase tracking-wide mb-0.5">Target 2 (T2) — trail 25%</p>
                <p className="text-lg font-bold text-green-300">${signal.take_profit_price_2.toFixed(2)}</p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  +{signal.entry_price ? ((signal.take_profit_price_2 - signal.entry_price) / signal.entry_price * 100).toFixed(1) : "?"}% from entry
                </p>
              </div>
              <div className="text-xs text-muted-foreground text-right max-w-[55%]">
                After T1 is hit, 50% position remains with stop moved to breakeven. T2 exits another 25%.
              </div>
            </div>
          )}
        </>
      )}

      {/* SKIP: why not section */}
      {isSkip && signal && <WhyNotCard signal={signal} />}

      {/* No signal returned at all */}
      {isSkip && !signal && (
        <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-4">
          <div className="flex items-center gap-2 font-medium text-yellow-400 mb-2">
            <AlertTriangle className="h-4 w-4" />
            No signal generated
          </div>
          <p className="text-sm text-foreground">
            The pipeline ran but returned no signal for <strong>{displayTicker}</strong>. This usually means the ticker failed data validation (e.g. not enough history, suspended trading, or no OHLCV data available from the data provider).
          </p>
        </div>
      )}

      {/* Agent scores — always shown when we have a signal */}
      {signal && (
        <div className="bg-card border border-border rounded-lg p-4">
          <h2 className="font-semibold mb-4">Agent Analysis Scores</h2>
          <AgentScoreBreakdown scores={signal.agent_scores} />
        </div>
      )}

      {/* Technical indicators */}
      {signal?.indicators && <IndicatorsPanel ind={signal.indicators} />}

      {/* Key risks */}
      {signal?.key_risks && signal.key_risks.length > 0 && (
        <div className="bg-card border border-yellow-500/20 rounded-lg p-4">
          <h2 className="font-semibold mb-3 text-yellow-400">Key Risks</h2>
          <ul className="space-y-2">
            {signal.key_risks.map((risk, i) => (
              <li key={i} className="flex items-start gap-2 text-sm">
                <span className="text-yellow-400 mt-0.5">•</span>
                <span className="text-muted-foreground">{risk}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* AI reasoning */}
      {signal?.reasoning && (
        <div className="bg-card border border-border rounded-lg p-4">
          <h2 className="font-semibold mb-2">AI Reasoning</h2>
          <p className="text-sm text-muted-foreground leading-relaxed">{signal.reasoning}</p>
        </div>
      )}
    </div>
  );
}
