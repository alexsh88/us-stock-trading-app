"use client";

import { useParams } from "next/navigation";
import { ArrowLeft, TrendingUp, TrendingDown, Minus, Info } from "lucide-react";
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
    </div>
  );
}

export default function SignalDetailPage() {
  const { ticker } = useParams<{ ticker: string }>();
  const { signals } = useTradingStore();
  const signal = signals.find((s) => s.ticker === ticker.toUpperCase());

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
          label="Take Profit"
          price={`$${signal.take_profit_price?.toFixed(2)}`}
          subLabel={`R:R ${signal.risk_reward_ratio?.toFixed(1)}×`}
          reason={formatTargetReason(signal.indicators?.target_method, signal.risk_reward_ratio)}
          colorClass="text-green-400"
          borderClass="border border-green-500/20"
        />
      </div>

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
