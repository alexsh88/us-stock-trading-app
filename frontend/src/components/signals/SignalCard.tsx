"use client";

import Link from "next/link";
import { TrendingUp, TrendingDown, Minus, ArrowRight } from "lucide-react";
import type { TradeSignal } from "@/store/trading-store";

interface Props {
  signal: TradeSignal;
  onPaperTrade?: (signal: TradeSignal) => void;
}

export function SignalCard({ signal, onPaperTrade }: Props) {
  const isBuy = signal.decision === "BUY";
  const isSell = signal.decision === "SELL";

  const decisionStyles = isBuy
    ? "bg-green-500/10 text-green-400 border-green-500/20"
    : isSell
    ? "bg-red-500/10 text-red-400 border-red-500/20"
    : "bg-yellow-500/10 text-yellow-400 border-yellow-500/20";

  const DecisionIcon = isBuy ? TrendingUp : isSell ? TrendingDown : Minus;
  const confidencePct = Math.round(signal.confidence_score * 100);

  return (
    <div className="bg-card border border-border rounded-lg p-4 hover:border-primary/50 transition-colors">
      {/* Top row */}
      <div className="flex items-start justify-between mb-3">
        <div>
          <span className="text-lg font-bold">{signal.ticker}</span>
          <span className="text-xs text-muted-foreground ml-2">{signal.trading_mode}</span>
        </div>
        <span className={`flex items-center gap-1 px-2 py-1 rounded border text-xs font-semibold ${decisionStyles}`}>
          <DecisionIcon className="h-3 w-3" />
          {signal.decision}
        </span>
      </div>

      {/* Confidence bar */}
      <div className="mb-3">
        <div className="flex justify-between text-xs mb-1">
          <span className="text-muted-foreground">Confidence</span>
          <span className="font-medium">{confidencePct}%</span>
        </div>
        <div className="h-1.5 bg-secondary rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${
              confidencePct >= 70 ? "bg-green-500" : confidencePct >= 50 ? "bg-yellow-500" : "bg-red-500"
            }`}
            style={{ width: `${confidencePct}%` }}
          />
        </div>
      </div>

      {/* Price levels */}
      <div className="grid grid-cols-3 gap-2 mb-3 text-center">
        <div className="bg-secondary rounded p-2">
          <p className="text-xs text-muted-foreground">Entry</p>
          <p className="text-sm font-semibold">${signal.entry_price?.toFixed(2)}</p>
        </div>
        <div className="bg-red-500/5 border border-red-500/20 rounded p-2">
          <p className="text-xs text-red-400">Stop</p>
          <p className="text-sm font-semibold text-red-400">${signal.stop_loss_price?.toFixed(2)}</p>
        </div>
        <div className="bg-green-500/5 border border-green-500/20 rounded p-2">
          <p className="text-xs text-green-400">Target</p>
          <p className="text-sm font-semibold text-green-400">${signal.take_profit_price?.toFixed(2)}</p>
        </div>
      </div>

      {/* R:R + position size */}
      <div className="flex items-center justify-between text-xs text-muted-foreground mb-3">
        <span>R:R {signal.risk_reward_ratio?.toFixed(1)}x</span>
        <span>Size {signal.position_size_pct?.toFixed(1)}% of portfolio</span>
      </div>

      {/* Actions */}
      <div className="flex gap-2">
        {onPaperTrade && signal.decision === "BUY" && (
          <button
            onClick={() => onPaperTrade(signal)}
            className="flex-1 bg-green-500/10 hover:bg-green-500/20 text-green-400 border border-green-500/20 rounded px-3 py-2 text-xs font-medium transition-colors"
          >
            Paper Trade
          </button>
        )}
        <Link
          href={`/signals/${signal.ticker}`}
          className="flex-1 flex items-center justify-center gap-1 bg-secondary hover:bg-secondary/80 rounded px-3 py-2 text-xs font-medium transition-colors"
        >
          Details <ArrowRight className="h-3 w-3" />
        </Link>
      </div>
    </div>
  );
}
