"use client";

import { useEffect, useRef } from "react";

interface Props {
  ticker: string;
  entryPrice?: number | null;
  stopLossPrice?: number | null;
  takeProfitPrice?: number | null;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function CandlestickChart({ ticker, entryPrice, stopLossPrice, takeProfitPrice }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    let cancelled = false;

    (async () => {
      const { createChart, LineStyle } = await import("lightweight-charts");
      if (cancelled || !containerRef.current) return;

      const chart = createChart(containerRef.current, {
        layout: {
          background: { color: "transparent" },
          textColor: "#94a3b8",
        },
        grid: {
          vertLines: { color: "#1e293b" },
          horzLines: { color: "#1e293b" },
        },
        crosshair: { mode: 1 },
        rightPriceScale: {
          borderColor: "#334155",
          scaleMargins: { top: 0.05, bottom: 0.22 }, // leave room for volume panel
        },
        timeScale: { borderColor: "#334155", timeVisible: false },
        width: containerRef.current.clientWidth,
        height: 420,
      });

      chartRef.current = chart;

      // --- Candlestick series ---
      const candleSeries = chart.addCandlestickSeries({
        upColor: "#22c55e",
        downColor: "#ef4444",
        borderUpColor: "#22c55e",
        borderDownColor: "#ef4444",
        wickUpColor: "#22c55e",
        wickDownColor: "#ef4444",
      });

      // --- BB band line series (on same price scale) ---
      const bbUpperSeries = chart.addLineSeries({
        color: "rgba(99, 102, 241, 0.5)",
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      const bbLowerSeries = chart.addLineSeries({
        color: "rgba(99, 102, 241, 0.5)",
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      const bbMidSeries = chart.addLineSeries({
        color: "rgba(99, 102, 241, 0.25)",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        priceLineVisible: false,
        lastValueVisible: false,
      });

      // --- Volume histogram series (separate scale at bottom) ---
      const volumeSeries = chart.addHistogramSeries({
        priceFormat: { type: "volume" },
        priceScaleId: "vol",
      });
      chart.priceScale("vol").applyOptions({
        scaleMargins: { top: 0.82, bottom: 0 },
      });

      // --- Fetch OHLCV + indicators ---
      try {
        const res = await fetch(`${API_URL}/api/v1/market-data/ohlcv/${ticker}?period=3mo`);
        if (res.ok && !cancelled) {
          const data = await res.json();

          if (data.candles?.length > 0) {
            candleSeries.setData(data.candles);

            // Volume bars — colour by candle direction
            const volData = data.candles.map((c: any) => ({
              time: c.time,
              value: c.volume,
              color: c.close >= c.open ? "rgba(34, 197, 94, 0.4)" : "rgba(239, 68, 68, 0.4)",
            }));
            volumeSeries.setData(volData);
          }

          if (data.bb?.length > 0) {
            const bbUpper = data.bb.map((b: any) => ({ time: b.time, value: b.upper }));
            const bbLower = data.bb.map((b: any) => ({ time: b.time, value: b.lower }));
            const bbMid = data.bb.map((b: any) => ({ time: b.time, value: b.mid }));
            bbUpperSeries.setData(bbUpper);
            bbLowerSeries.setData(bbLower);
            bbMidSeries.setData(bbMid);
          }

          // Swing resistance levels (red dashed)
          if (data.swing_highs?.length > 0) {
            for (const level of data.swing_highs) {
              candleSeries.createPriceLine({
                price: level,
                color: "rgba(239, 68, 68, 0.6)",
                lineWidth: 1,
                lineStyle: LineStyle.Dashed,
                axisLabelVisible: false,
                title: "",
              });
            }
          }

          // Swing support levels (green dashed)
          if (data.swing_lows?.length > 0) {
            for (const level of data.swing_lows) {
              candleSeries.createPriceLine({
                price: level,
                color: "rgba(34, 197, 94, 0.6)",
                lineWidth: 1,
                lineStyle: LineStyle.Dashed,
                axisLabelVisible: false,
                title: "",
              });
            }
          }
        }
      } catch {
        // ignore fetch errors
      }

      if (cancelled) {
        chart.remove();
        chartRef.current = null;
        return;
      }

      // --- Signal price lines (on top of everything) ---
      if (entryPrice) {
        candleSeries.createPriceLine({
          price: entryPrice,
          color: "#94a3b8",
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: "Entry",
        });
      }
      if (stopLossPrice) {
        candleSeries.createPriceLine({
          price: stopLossPrice,
          color: "#ef4444",
          lineWidth: 2,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: "Stop",
        });
      }
      if (takeProfitPrice) {
        candleSeries.createPriceLine({
          price: takeProfitPrice,
          color: "#22c55e",
          lineWidth: 2,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: "Target",
        });
      }

      chart.timeScale().fitContent();

      const resizeObserver = new ResizeObserver(() => {
        if (containerRef.current && chartRef.current) {
          chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
        }
      });
      resizeObserver.observe(containerRef.current);

      (chartRef.current as any)._cleanup = () => {
        resizeObserver.disconnect();
        chart.remove();
        chartRef.current = null;
      };
    })();

    return () => {
      cancelled = true;
      if (chartRef.current?._cleanup) {
        chartRef.current._cleanup();
      } else if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [ticker, entryPrice, stopLossPrice, takeProfitPrice]);

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-4 text-xs text-muted-foreground px-1">
        <span className="flex items-center gap-1">
          <span className="inline-block w-4 border-t border-dotted border-indigo-400" />
          BB Bands
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-4 border-t border-dashed border-red-500/60" />
          Resistance
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-4 border-t border-dashed border-green-500/60" />
          Support
        </span>
      </div>
      <div ref={containerRef} className="w-full" style={{ height: 420 }} />
    </div>
  );
}
