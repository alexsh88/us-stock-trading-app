import { create } from "zustand";

export interface AgentScores {
  technical?: number | null;
  fundamental?: number | null;
  sentiment?: number | null;
  catalyst?: number | null;
}

export interface TechnicalIndicators {
  adx?: number | null;
  regime?: "trending" | "neutral" | "choppy" | null;
  mtf_aligned?: boolean | null;
  bb_squeeze?: boolean | null;
  squeeze_released?: boolean | null;
  breakout_score?: number | null;  // 0–3
  breakout_details?: string | null;
  vol_ratio?: number | null;
  swing_resistance?: number | null;
  swing_support?: number | null;
  rsi?: number | null;
  macd_signal?: "bullish" | "bearish" | null;
  bb_position?: string | null;
  vwap_relation?: string | null;
  stop_loss_method?: string | null;
  target_method?: string | null;
}

export interface TradeSignal {
  id: string;
  run_id: string;
  ticker: string;
  decision: "BUY" | "SELL" | "HOLD" | "SKIP";
  confidence_score: number;
  trading_mode: string;
  entry_price?: number | null;
  stop_loss_price?: number | null;
  stop_loss_method?: string | null;
  take_profit_price?: number | null;
  risk_reward_ratio?: number | null;
  position_size_pct?: number | null;
  agent_scores: AgentScores;
  indicators?: TechnicalIndicators | null;
  key_risks: string[];
  reasoning?: string | null;
  is_paper: boolean;
  created_at: string;
}

export interface AnalysisRun {
  id: string;
  status: "pending" | "running" | "completed" | "failed";
  top_n: number;
  mode: string;
  tickers_screened?: number | null;
  signals_generated?: number | null;
  error_message?: string | null;
  created_at: string;
  completed_at?: string | null;
}

interface TradingStore {
  signals: TradeSignal[];
  currentRun: AnalysisRun | null;
  quotes: Record<string, number>;

  setSignals: (signals: TradeSignal[]) => void;
  setCurrentRun: (run: AnalysisRun | null) => void;
  updateQuote: (ticker: string, price: number) => void;
}

export const useTradingStore = create<TradingStore>((set) => ({
  signals: [],
  currentRun: null,
  quotes: {},

  setSignals: (signals) => set({ signals }),
  setCurrentRun: (currentRun) => set({ currentRun }),
  updateQuote: (ticker, price) =>
    set((state) => ({ quotes: { ...state.quotes, [ticker]: price } })),
}));
