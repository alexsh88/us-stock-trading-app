"use client";

import { useCallback } from "react";
import { useSSE } from "./useSSE";
import { useTradingStore } from "@/store/trading-store";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function useQuotes(tickers: string[]) {
  const { updateQuote } = useTradingStore();

  const url = tickers.length > 0
    ? `${API_URL}/api/v1/market-data/stream?tickers=${tickers.join(",")}`
    : null;

  const onMessage = useCallback(
    (data: unknown) => {
      if (typeof data === "object" && data !== null) {
        const quote = data as { ticker?: string; price?: number };
        if (quote.ticker && quote.price != null) {
          updateQuote(quote.ticker, quote.price);
        }
      }
    },
    [updateQuote]
  );

  useSSE(url, { onMessage });
}
