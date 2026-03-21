"use client";

import { useParams } from "next/navigation";
import { useState, useCallback, useEffect } from "react";
import { ArrowLeft, TrendingUp, TrendingDown, Minus, Info, Send, CheckCircle2, RefreshCw } from "lucide-react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { useTradingStore, TechnicalIndicators } from "@/store/trading-store";
import { AgentScoreBreakdown } from "@/components/signals/AgentScoreBreakdown";

const CandlestickChart = dynamic(
  () => import("@/components/charts/CandlestickChart"),
  { ssr: false, loading: () => <div className="h-96 bg-secondary rounded-lg animate-pulse" /> }
);

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
    return { label: `ATR ${mult}× stop`, detail: `${mult}× the average true range below entry — widens in volatile markets, tightens in calm ones` };
  }
  // AVWAP: "AVWAP($261.39)"
  if (method.startsWith("AVWAP")) {
    const price = method.match(/\$([\d.]+)/)?.[1];
    return {
      label: "Anchored VWAP",
      detail: `VWAP anchored to the most recent swing low${price ? ` at $${price}` : ""} — price above AVWAP = bullish structure intact; stop just below it`,
    };
  }
  // Pattern invalidation: "double_bottom-invalidation(str=0.72)"
  const patMatch = method.match(/^(.+)-invalidation\(str=([\d.]+)\)$/);
  if (patMatch) {
    const patName = patMatch[1].replace(/_/g, " ");
    const str = parseFloat(patMatch[2]);
    return {
      label: `${patName} invalidation`,
      detail: `Below the pattern lows (strength ${(str * 100).toFixed(0)}%) — if price returns here the setup has failed`,
    };
  }
  return { label: method, detail: "" };
}

function formatTargetReason(method: string | null | undefined, rr: number | null | undefined): { label: string; detail: string } {
  const rrStr = rr?.toFixed(1) ?? "2.0";
  if (!method || method === "min_rr_floor") return { label: "R:R floor", detail: `No stronger level found — target set at the minimum ${rrStr}× reward-to-risk` };
  if (method.startsWith("pattern-")) {
    const name = method.replace("pattern-", "").replace(/_/g, " ");
    return { label: `${name} projection`, detail: "Classic measured move — pattern height projected above the breakout level" };
  }
  if (method === "Fib127") return { label: "Fib 1.272× extension", detail: "First Fibonacci extension above the prior swing — common first institutional take-profit zone" };
  if (method === "Fib162") return { label: "Fib 1.618× extension", detail: "Golden ratio extension — strong institutional target, often marks end of an impulsive move" };
  if (method === "WeeklyR1") return { label: "Weekly R1 pivot", detail: "First weekly resistance (PP×2 − prior low) — self-fulfilling level widely watched by institutions" };
  if (method === "WeeklyR2") return { label: "Weekly R2 pivot", detail: "Second weekly resistance (PP + prior range) — extended target for strong trending moves" };
  if (method === "VolumeProfileVAH") return { label: "Volume Profile VAH", detail: "Value Area High — upper boundary of the zone holding 70% of recent volume; strong institutional supply cluster" };
  if (method === "ClusteredResist") return { label: "Clustered resistance", detail: "Price zone with multiple prior pivot highs — the strongest nearby supply area" };
  if (method === "SwingResist") return { label: "Swing resistance", detail: "Most recent pivot high on the daily chart" };
  return { label: method, detail: "" };
}

function LevelCard({
  label, price, subLabel, reason, colorClass, borderClass,
}: {
  label: string; price: string; subLabel: string;
  reason: { label: string; detail: string };
  colorClass: string; borderClass: string;
}) {
  return (
    <div className={`bg-card ${borderClass} rounded-lg p-4`}>
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

function IndicatorsPanel({ ind }: { ind: TechnicalIndicators }) {
  const breakoutColors = ["bg-secondary text-muted-foreground", "bg-yellow-500/20 text-yellow-400", "bg-blue-500/20 text-blue-400", "bg-green-500/20 text-green-400"];
  const breakoutColor = breakoutColors[ind.breakout_score ?? 0];

  return (
    <div className="bg-card border border-border rounded-lg p-4 space-y-4">
      <h2 className="font-semibold">Technical Indicators</h2>

      {/* Row 1: regime + key booleans */}
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

      {/* Row 2: metric pills */}
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
          <div className={`border border-transparent rounded-lg px-3 py-2 text-center ${breakoutColor}`}>
            <p className="text-xs opacity-70 mb-0.5">Breakout</p>
            <p className="text-sm font-semibold">{ind.breakout_score}/3</p>
          </div>
        )}
      </div>

      {/* Breakout detail */}
      {ind.breakout_details && (
        <p className="text-xs text-muted-foreground">
          Breakout checkpoints: <span className="text-foreground">{ind.breakout_details}</span>
        </p>
      )}

      {/* Swing levels */}
      {(ind.swing_resistance != null || ind.swing_support != null) && (
        <div className="flex gap-4 text-sm">
          {ind.swing_resistance != null && (
            <span className="text-muted-foreground">
              Resistance <span className="text-red-400 font-medium">${ind.swing_resistance.toFixed(2)}</span>
            </span>
          )}
          {ind.swing_support != null && (
            <span className="text-muted-foreground">
              Support <span className="text-green-400 font-medium">${ind.swing_support.toFixed(2)}</span>
            </span>
          )}
        </div>
      )}

      {/* Volume Profile */}
      {(ind.vpoc != null || ind.val != null || ind.vah != null) && (
        <div className="border-t border-border pt-3">
          <p className="text-xs text-muted-foreground uppercase tracking-wide mb-2">Volume Profile</p>
          <div className="flex flex-wrap gap-4 text-sm">
            {ind.vah != null && (
              <span className="text-muted-foreground">VAH <span className="text-red-400 font-medium">${ind.vah.toFixed(2)}</span></span>
            )}
            {ind.vpoc != null && (
              <span className="text-muted-foreground">VPOC <span className="text-foreground font-medium">${ind.vpoc.toFixed(2)}</span></span>
            )}
            {ind.val != null && (
              <span className="text-muted-foreground">VAL <span className="text-green-400 font-medium">${ind.val.toFixed(2)}</span></span>
            )}
          </div>
        </div>
      )}

      {/* AVWAP */}
      {ind.avwap != null && (
        <div className="border-t border-border pt-3">
          <p className="text-xs text-muted-foreground uppercase tracking-wide mb-2">Anchored VWAP</p>
          <div className="flex flex-wrap gap-4 text-sm items-center">
            <span className="text-muted-foreground">
              AVWAP <span className="text-foreground font-medium">${ind.avwap.toFixed(2)}</span>
            </span>
            {ind.price_above_avwap != null && (
              <span className={`text-xs px-2 py-0.5 rounded font-medium border ${
                ind.price_above_avwap
                  ? "bg-green-500/20 text-green-400 border-green-500/30"
                  : "bg-red-500/20 text-red-400 border-red-500/30"
              }`}>
                {ind.price_above_avwap ? "Price above AVWAP ✓" : "Price below AVWAP ✗"}
              </span>
            )}
            {ind.weekly_structural_stop != null && (
              <span className="text-muted-foreground">
                Weekly stop <span className="text-red-400 font-medium">${ind.weekly_structural_stop.toFixed(2)}</span>
              </span>
            )}
          </div>
        </div>
      )}

      {/* Gap + Sizing */}
      {(ind.gap_type != null || ind.beta != null || ind.hv_rank != null) && (
        <div className="border-t border-border pt-3">
          <p className="text-xs text-muted-foreground uppercase tracking-wide mb-2">Market Context</p>
          <div className="flex flex-wrap gap-2">
            {ind.gap_type && ind.gap_type !== "none" && (
              <span className={`text-xs px-2 py-0.5 rounded font-medium border ${
                ind.gap_type === "breakaway" ? "bg-green-500/20 text-green-400 border-green-500/30"
                : ind.gap_type === "exhaustion" ? "bg-red-500/20 text-red-400 border-red-500/30"
                : "bg-secondary text-muted-foreground border-border"
              }`}>
                {ind.gap_type} gap {ind.gap_pct != null ? `(${ind.gap_pct > 0 ? "+" : ""}${ind.gap_pct.toFixed(1)}%)` : ""}
              </span>
            )}
            {ind.beta != null && (
              <span className="text-xs px-2 py-0.5 rounded border bg-secondary text-muted-foreground border-border">
                β {ind.beta.toFixed(2)}
              </span>
            )}
            {ind.hv_rank != null && (
              <span className={`text-xs px-2 py-0.5 rounded font-medium border ${
                ind.hv_rank >= 80 ? "bg-red-500/20 text-red-400 border-red-500/30"
                : ind.hv_rank >= 40 ? "bg-yellow-500/20 text-yellow-400 border-yellow-500/30"
                : "bg-green-500/20 text-green-400 border-green-500/30"
              }`}>
                HV {ind.hv_rank.toFixed(0)}th pct
              </span>
            )}
            {ind.regime_sizing != null && ind.regime_sizing < 1.0 && (
              <span className="text-xs px-2 py-0.5 rounded border bg-yellow-500/20 text-yellow-400 border-yellow-500/30">
                Regime ×{ind.regime_sizing.toFixed(2)}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
type BracketState = "idle" | "submitting" | "submitted" | "error";

export default function SignalDetailPage() {
  const { ticker } = useParams<{ ticker: string }>();
  const { signals } = useTradingStore();
  const signal = signals.find((s) => s.ticker === ticker.toUpperCase());

  const [bracketState, setBracketState] = useState<BracketState>("idle");
  const [bracketQty, setBracketQty] = useState<number>(10);
  const [bracketOrderId, setBracketOrderId] = useState<number | null>(null);
  const [bracketError, setBracketError] = useState<string>("");
  const [ibkrEnabled, setIbkrEnabled] = useState<boolean | null>(null); // null = loading

  useEffect(() => {
    fetch(`${API_BASE}/api/v1/trades/ibkr/status`)
      .then((r) => r.json())
      .then((d) => setIbkrEnabled(d.enabled))
      .catch(() => setIbkrEnabled(false));
  }, []);

  const handleSubmitBracket = useCallback(async () => {
    if (!signal) return;
    setBracketState("submitting");
    setBracketError("");
    try {
      const pfRes = await fetch(`${API_BASE}/api/v1/portfolio/`);
      if (!pfRes.ok) throw new Error("Could not load portfolios");
      const portfolios = await pfRes.json();
      if (!portfolios.length) throw new Error("No portfolio found — create one first");

      const res = await fetch(`${API_BASE}/api/v1/trades/bracket`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          signal_id: signal.id,
          portfolio_id: portfolios[0].id,
          quantity: bracketQty,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail ?? `HTTP ${res.status}`);
      }
      const result = await res.json();
      setBracketOrderId(result.ibkr_parent_order_id);
      setBracketState("submitted");
    } catch (e) {
      setBracketError(e instanceof Error ? e.message : "Submission failed");
      setBracketState("error");
    }
  }, [signal, bracketQty]);

  if (!signal) {
    return (
      <div className="text-center py-20">
        <p className="text-muted-foreground">Signal not found for {ticker}</p>
        <Link href="/" className="text-primary hover:underline mt-4 inline-block">
          Back to dashboard
        </Link>
      </div>
    );
  }

  const decisionColor =
    signal.decision === "BUY" ? "text-green-500" :
    signal.decision === "SELL" ? "text-red-500" : "text-yellow-500";

  const DecisionIcon =
    signal.decision === "BUY" ? TrendingUp :
    signal.decision === "SELL" ? TrendingDown : Minus;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Link href="/" className="text-muted-foreground hover:text-foreground transition-colors">
          <ArrowLeft className="h-5 w-5" />
        </Link>
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-3">
            {signal.ticker}
            <span className={`flex items-center gap-1 text-lg ${decisionColor}`}>
              <DecisionIcon className="h-5 w-5" />
              {signal.decision}
            </span>
          </h1>
          <p className="text-muted-foreground text-sm">
            Confidence: {(signal.confidence_score * 100).toFixed(0)}% · {signal.trading_mode} trade
          </p>
        </div>
      </div>

      {/* Chart */}
      <div className="bg-card border border-border rounded-lg p-4">
        <CandlestickChart
          ticker={signal.ticker}
          entryPrice={signal.entry_price}
          stopLossPrice={signal.stop_loss_price}
          takeProfitPrice={signal.take_profit_price}
        />
      </div>

      {/* Trade levels */}
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

      {/* T2 — second target for trailing remainder */}
      {signal.take_profit_price_2 && (
        <div className="bg-card border border-green-500/10 rounded-lg p-4 flex items-center justify-between">
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wide mb-0.5">Target 2 (T2) — trail 25%</p>
            <p className="text-lg font-bold text-green-300">${signal.take_profit_price_2.toFixed(2)}</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              +{signal.entry_price ? ((signal.take_profit_price_2 - signal.entry_price) / signal.entry_price * 100).toFixed(1) : "?"}% from entry · next resistance above T1
            </p>
          </div>
          <div className="text-xs text-muted-foreground text-right max-w-[55%]">
            After T1 is hit, 50% position remains with stop moved to breakeven.
            T2 exits another 25% — the final 25% trails with chandelier (+ PSAR when ADX &gt; 25).
          </div>
        </div>
      )}

      {/* Submit to TWS — BUY signals only, requires IBKR enabled in Settings */}
      {signal.decision === "BUY" && signal.entry_price && signal.stop_loss_price && signal.take_profit_price && ibkrEnabled === true && (
        bracketState === "submitted" ? (
          <div className="bg-green-500/10 border border-green-500/30 rounded-lg p-4 flex items-center gap-3">
            <CheckCircle2 className="h-5 w-5 text-green-400 shrink-0" />
            <div>
              <p className="font-medium text-green-400">Bracket order submitted to TWS</p>
              <p className="text-xs text-muted-foreground mt-0.5">
                Order #{bracketOrderId} · Entry limit → stop + T1 OCO live in your paper account
              </p>
            </div>
          </div>
        ) : (
          <div className="bg-card border border-primary/20 rounded-lg p-4 space-y-3">
            <p className="text-sm font-medium flex items-center gap-2">
              <Send className="h-4 w-4 text-primary" />
              Submit bracket order to TWS (paper)
            </p>
            <div className="flex items-center gap-3">
              <div className="flex-1">
                <label className="text-xs text-muted-foreground">Shares</label>
                <input
                  type="number"
                  min={1}
                  value={bracketQty}
                  onChange={(e) => setBracketQty(Math.max(1, parseInt(e.target.value) || 1))}
                  className="w-full bg-secondary border border-border rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary/40 mt-1"
                />
              </div>
              <div className="text-xs text-muted-foreground space-y-0.5 pt-4">
                <p>Entry <span className="text-foreground font-mono">${signal.entry_price.toFixed(2)}</span></p>
                <p>Stop <span className="text-red-400 font-mono">${signal.stop_loss_price.toFixed(2)}</span></p>
                <p>T1 <span className="text-green-400 font-mono">${signal.take_profit_price.toFixed(2)}</span></p>
              </div>
            </div>
            {bracketState === "error" && (
              <p className="text-xs text-red-400">{bracketError}</p>
            )}
            <button
              onClick={handleSubmitBracket}
              disabled={bracketState === "submitting"}
              className="w-full py-2.5 rounded-lg bg-primary text-primary-foreground text-sm font-semibold hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
            >
              {bracketState === "submitting" ? (
                <><RefreshCw className="h-4 w-4 animate-spin" /> Placing order…</>
              ) : (
                <><Send className="h-4 w-4" /> Submit to TWS</>
              )}
            </button>
            <p className="text-xs text-muted-foreground text-center">
              Places a limit entry + stop-loss + T1 limit sell as a linked bracket on your paper account
            </p>
          </div>
        )
      )}

      {/* Agent scores */}
      <div className="bg-card border border-border rounded-lg p-4">
        <h2 className="font-semibold mb-4">Agent Analysis Scores</h2>
        <AgentScoreBreakdown scores={signal.agent_scores} />
      </div>

      {/* Risks */}
      {signal.key_risks && signal.key_risks.length > 0 && (
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

      {/* Technical Indicators */}
      {signal.indicators && <IndicatorsPanel ind={signal.indicators} />}

      {/* Reasoning */}
      {signal.reasoning && (
        <div className="bg-card border border-border rounded-lg p-4">
          <h2 className="font-semibold mb-2">AI Reasoning</h2>
          <p className="text-sm text-muted-foreground leading-relaxed">{signal.reasoning}</p>
        </div>
      )}
    </div>
  );
}
