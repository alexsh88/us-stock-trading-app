"use client";

import { useState, useEffect } from "react";
import { Settings, Save } from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const SECTOR_LABELS: Record<number, string> = {
  1: "1 — single best sector (most focused)",
  2: "2 — top two sectors",
  3: "3 — top three sectors (default)",
  4: "4 — top four sectors",
  5: "5 — broader scan",
  7: "7 — half the ETF list",
  14: "14 — all sectors (same as old static screener)",
};

interface AppSettings {
  top_n: number;
  trading_mode: string;
  paper_trading: boolean;
  watchlist: string;
  sector_top_n: number;
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings>({
    top_n: 5,
    trading_mode: "swing",
    paper_trading: true,
    watchlist: "",
    sector_top_n: 3,
  });
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetch(`${API_URL}/api/v1/settings/`)
      .then((r) => r.json())
      .then((data) => setSettings({ ...data, watchlist: data.watchlist ?? "", sector_top_n: data.sector_top_n ?? 3 }))
      .catch(() => {});
  }, []);

  const save = async () => {
    await fetch(`${API_URL}/api/v1/settings/`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...settings, watchlist: settings.watchlist.trim() || null }),
    });
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div className="space-y-6 max-w-lg">
      <div className="flex items-center gap-2">
        <Settings className="h-6 w-6" />
        <h1 className="text-2xl font-bold">Settings</h1>
      </div>

      <div className="bg-card border border-border rounded-lg p-6 space-y-5">

        <div>
          <label className="block text-sm font-medium mb-2">Top N Stocks</label>
          <input
            type="number"
            min={1}
            max={50}
            value={settings.top_n}
            onChange={(e) => setSettings({ ...settings, top_n: Number(e.target.value) })}
            className="w-full bg-secondary border border-border rounded-md px-3 py-2 text-sm"
          />
          <p className="text-xs text-muted-foreground mt-1">Number of top stocks to surface per analysis run</p>
        </div>

        <div>
          <label className="block text-sm font-medium mb-2">Trading Mode</label>
          <select
            value={settings.trading_mode}
            onChange={(e) => setSettings({ ...settings, trading_mode: e.target.value })}
            className="w-full bg-secondary border border-border rounded-md px-3 py-2 text-sm"
          >
            <option value="swing">Swing (2-5 days, ATR-2x stops)</option>
            <option value="intraday">Intraday (same day, ATR-1.5x stops)</option>
          </select>
        </div>

        {/* Sector breadth slider */}
        <div>
          <label className="block text-sm font-medium mb-2">Sector Breadth</label>
          <div className="flex items-center gap-3">
            <span className="text-xs text-muted-foreground w-8 text-center font-mono">
              {settings.sector_top_n}
            </span>
            <input
              type="range"
              min={1}
              max={14}
              step={1}
              value={settings.sector_top_n}
              onChange={(e) => setSettings({ ...settings, sector_top_n: Number(e.target.value) })}
              className="flex-1 accent-primary"
            />
            <span className="text-xs text-muted-foreground w-8 text-center font-mono">14</span>
          </div>
          <p className="text-xs text-muted-foreground mt-1.5">
            {settings.sector_top_n === 1 && "Most focused — only the single strongest sector ETF this week"}
            {settings.sector_top_n === 2 && "Top 2 sectors — tight focus, ~25-40 candidate stocks"}
            {settings.sector_top_n === 3 && "Top 3 sectors (default) — ~40-65 candidates, good balance"}
            {settings.sector_top_n === 4 && "Top 4 sectors — ~55-80 candidates, more variety"}
            {settings.sector_top_n >= 5 && settings.sector_top_n <= 6 && `Top ${settings.sector_top_n} sectors — broad scan, ~80-110 candidates`}
            {settings.sector_top_n >= 7 && settings.sector_top_n <= 13 && `Top ${settings.sector_top_n} sectors — very broad, less sector-rotation signal`}
            {settings.sector_top_n === 14 && "All 14 sectors — equivalent to old static universe, no rotation bias"}
          </p>
        </div>

        <div>
          <label className="block text-sm font-medium mb-2">Custom Watchlist</label>
          <textarea
            rows={3}
            placeholder="AAPL, MSFT, NVDA, TSLA (leave empty to use auto-screener)"
            value={settings.watchlist}
            onChange={(e) => setSettings({ ...settings, watchlist: e.target.value })}
            className="w-full bg-secondary border border-border rounded-md px-3 py-2 text-sm font-mono resize-none"
          />
          <p className="text-xs text-muted-foreground mt-1">
            {settings.watchlist.trim()
              ? `${settings.watchlist.split(",").filter(t => t.trim()).length} tickers — screener will be skipped, these stocks go straight to analysis`
              : "Empty = use ETF-first auto-screener"}
          </p>
        </div>

        <div className="flex items-center justify-between">
          <div>
            <label className="text-sm font-medium">Paper Trading Mode</label>
            <p className="text-xs text-muted-foreground mt-0.5">Disable to enable live IBKR execution</p>
          </div>
          <button
            onClick={() => setSettings({ ...settings, paper_trading: !settings.paper_trading })}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
              settings.paper_trading ? "bg-primary" : "bg-muted"
            }`}
          >
            <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
              settings.paper_trading ? "translate-x-6" : "translate-x-1"
            }`} />
          </button>
        </div>

        {!settings.paper_trading && (
          <div className="bg-destructive/10 border border-destructive/30 rounded-md p-3 text-sm text-destructive">
            Warning: Live trading mode will execute real orders on your IBKR account.
          </div>
        )}

        <button
          onClick={save}
          className="w-full flex items-center justify-center gap-2 bg-primary text-primary-foreground py-2 rounded-md text-sm font-medium hover:bg-primary/90 transition-colors"
        >
          <Save className="h-4 w-4" />
          {saved ? "Saved!" : "Save Settings"}
        </button>
      </div>
    </div>
  );
}
