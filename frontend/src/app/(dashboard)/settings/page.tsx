"use client";

import { useState, useEffect, useCallback } from "react";
import { Settings, Save, ChevronDown, ChevronUp, Wifi, WifiOff, RefreshCw } from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Sector definitions ────────────────────────────────────────────────────────
const SECTOR_GROUPS = [
  {
    label: "Equity Sectors",
    sectors: [
      { etf: "XLK",  name: "Technology",             desc: "NVDA, AAPL, MSFT, AMD, semiconductors, software" },
      { etf: "XLF",  name: "Financials",              desc: "JPM, GS, V, MA, banks, asset managers" },
      { etf: "XLV",  name: "Health Care",             desc: "LLY, UNH, ABBV, AMGN, biotech, medtech" },
      { etf: "XLI",  name: "Industrials / Defense",   desc: "CAT, BA, LMT, GE, RTX, UPS, FDX" },
      { etf: "XLC",  name: "Communications",          desc: "GOOGL, META, NFLX, DIS, SPOT, COIN" },
      { etf: "XLB",  name: "Materials",               desc: "FCX, NEM, LIN, SHW, NUE, ALB, MP" },
      { etf: "XLP",  name: "Consumer Staples",        desc: "COST, WMT, PG, KO, PEP, PM, MO" },
      { etf: "XLU",  name: "Utilities",               desc: "NEE, DUK, SO, D — defensive/rate-sensitive" },
      { etf: "XLRE", name: "Real Estate",             desc: "AMT, PLD, EQIX, CCI, PSA, VICI" },
      { etf: "XLY",  name: "Consumer Discretionary",  desc: "AMZN, TSLA, HD, MCD, LULU, DECK, ABNB" },
    ],
  },
  {
    label: "Commodities & Energy",
    sectors: [
      { etf: "XLE",  name: "Energy",   desc: "XOM, CVX, COP, EOG, OXY, SLB, VLO, MPC" },
      { etf: "GLD",  name: "Gold",     desc: "NEM, AEM, GOLD, WPM, FNV, KGC, RGLD" },
      { etf: "SLV",  name: "Silver",   desc: "Tracks silver miners and precious metals" },
      { etf: "USO",  name: "Crude Oil",desc: "XOM, CVX, COP, OXY, SLB, HAL, MPC, VLO" },
    ],
  },
];

interface AppSettings {
  top_n: number;
  trading_mode: string;
  paper_trading: boolean;
  ibkr_enabled: boolean;
  watchlist: string;
  sector_top_n: number;
  pinned_sectors: string[];
}

type IbkrStatus = { enabled: boolean; connected: boolean; port: number; error: string | null } | null;

export default function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings>({
    top_n: 5,
    trading_mode: "swing",
    paper_trading: true,
    ibkr_enabled: false,
    watchlist: "",
    sector_top_n: 3,
    pinned_sectors: [],
  });
  const [saved, setSaved] = useState(false);
  const [sectorOpen, setSectorOpen] = useState(false);
  const [ibkrStatus, setIbkrStatus] = useState<IbkrStatus>(null);
  const [ibkrTesting, setIbkrTesting] = useState(false);

  useEffect(() => {
    fetch(`${API_URL}/api/v1/settings/`)
      .then((r) => r.json())
      .then((data) =>
        setSettings({
          ...data,
          ibkr_enabled: data.ibkr_enabled ?? false,
          watchlist: data.watchlist ?? "",
          sector_top_n: data.sector_top_n ?? 3,
          pinned_sectors: data.pinned_sectors ?? [],
        })
      )
      .catch(() => {});
  }, []);

  const toggleSector = (etf: string) => {
    setSettings((prev) => ({
      ...prev,
      pinned_sectors: prev.pinned_sectors.includes(etf)
        ? prev.pinned_sectors.filter((s) => s !== etf)
        : [...prev.pinned_sectors, etf],
    }));
  };

  const testIbkrConnection = useCallback(async () => {
    setIbkrTesting(true);
    try {
      const res = await fetch(`${API_URL}/api/v1/trades/ibkr/status`);
      const data = await res.json();
      setIbkrStatus(data);
    } catch {
      setIbkrStatus({ enabled: false, connected: false, port: 7497, error: "Could not reach backend" });
    } finally {
      setIbkrTesting(false);
    }
  }, []);

  const save = async () => {
    await fetch(`${API_URL}/api/v1/settings/`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...settings,
        watchlist: settings.watchlist.trim() || null,
        pinned_sectors: settings.pinned_sectors,
      }),
    });
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const pinnedActive = settings.pinned_sectors.length > 0;

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

        {/* ── Sector Picker ── */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="text-sm font-medium">Sector Filter</label>
            {pinnedActive && (
              <span className="text-xs bg-primary/20 text-primary px-2 py-0.5 rounded font-medium">
                {settings.pinned_sectors.length} pinned
              </span>
            )}
          </div>

          <button
            type="button"
            onClick={() => setSectorOpen((o) => !o)}
            className="w-full flex items-center justify-between bg-secondary border border-border rounded-md px-3 py-2 text-sm hover:bg-secondary/80 transition-colors"
          >
            <span className={pinnedActive ? "text-foreground" : "text-muted-foreground"}>
              {pinnedActive
                ? settings.pinned_sectors.join(", ")
                : "Auto — ETF ranking picks leading sectors"}
            </span>
            {sectorOpen ? <ChevronUp className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
          </button>

          {sectorOpen && (
            <div className="mt-2 bg-secondary/50 border border-border rounded-md p-3 space-y-4">
              <p className="text-xs text-muted-foreground">
                Check the sectors you want to analyse. Leave all unchecked to let the system auto-rank and pick the top performers.
              </p>

              {SECTOR_GROUPS.map((group) => (
                <div key={group.label}>
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">{group.label}</p>
                  <div className="space-y-1.5">
                    {group.sectors.map(({ etf, name, desc }) => {
                      const checked = settings.pinned_sectors.includes(etf);
                      return (
                        <label
                          key={etf}
                          className={`flex items-start gap-3 cursor-pointer rounded-md px-2 py-1.5 transition-colors ${
                            checked ? "bg-primary/10" : "hover:bg-secondary"
                          }`}
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => toggleSector(etf)}
                            className="mt-0.5 accent-primary flex-shrink-0"
                          />
                          <div className="min-w-0">
                            <span className="text-sm font-medium">{etf}</span>
                            <span className="text-sm text-muted-foreground"> — {name}</span>
                            <p className="text-xs text-muted-foreground truncate">{desc}</p>
                          </div>
                        </label>
                      );
                    })}
                  </div>
                </div>
              ))}

              {pinnedActive && (
                <button
                  type="button"
                  onClick={() => setSettings((p) => ({ ...p, pinned_sectors: [] }))}
                  className="text-xs text-muted-foreground hover:text-foreground underline"
                >
                  Clear all — switch back to auto ranking
                </button>
              )}
            </div>
          )}

          <p className="text-xs text-muted-foreground mt-1.5">
            {pinnedActive
              ? `Only stocks from ${settings.pinned_sectors.join(", ")} will be analysed — ETF auto-ranking is bypassed`
              : "Auto mode: top sectors ranked by recent RS vs SPY, then stocks from those sectors are screened"}
          </p>
        </div>

        {/* Sector Breadth slider — disabled when pinned sectors active */}
        <div className={pinnedActive ? "opacity-40 pointer-events-none" : ""}>
          <label className="block text-sm font-medium mb-2">
            Sector Breadth
            {pinnedActive && <span className="text-xs text-muted-foreground font-normal ml-2">(disabled — using pinned sectors)</span>}
          </label>
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
              disabled={pinnedActive}
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

        {/* IBKR Connection */}
        <div className="border-t border-border pt-5 space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <label className="text-sm font-medium">IBKR TWS Connection</label>
              <p className="text-xs text-muted-foreground mt-0.5">
                Enable to submit real bracket orders to TWS (port 7497 paper)
              </p>
            </div>
            <button
              onClick={() => {
                const next = !settings.ibkr_enabled;
                setSettings({ ...settings, ibkr_enabled: next });
                setIbkrStatus(null);
              }}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                settings.ibkr_enabled ? "bg-green-500" : "bg-muted"
              }`}
            >
              <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                settings.ibkr_enabled ? "translate-x-6" : "translate-x-1"
              }`} />
            </button>
          </div>

          {settings.ibkr_enabled && (
            <div className="space-y-2">
              <button
                onClick={testIbkrConnection}
                disabled={ibkrTesting}
                className="flex items-center gap-2 text-xs px-3 py-1.5 rounded-md bg-secondary border border-border hover:bg-secondary/80 disabled:opacity-50 transition-colors"
              >
                <RefreshCw className={`h-3 w-3 ${ibkrTesting ? "animate-spin" : ""}`} />
                {ibkrTesting ? "Testing…" : "Test Connection"}
              </button>

              {ibkrStatus && (
                <div className={`flex items-start gap-2 rounded-md p-3 text-xs ${
                  ibkrStatus.connected
                    ? "bg-green-500/10 border border-green-500/30 text-green-400"
                    : "bg-red-500/10 border border-red-500/30 text-red-400"
                }`}>
                  {ibkrStatus.connected
                    ? <Wifi className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                    : <WifiOff className="h-3.5 w-3.5 mt-0.5 shrink-0" />}
                  <div>
                    {ibkrStatus.connected
                      ? `Connected to TWS on port ${ibkrStatus.port}`
                      : `Cannot connect to TWS on port ${ibkrStatus.port}`}
                    {ibkrStatus.error && (
                      <p className="text-red-300 mt-0.5">{ibkrStatus.error}</p>
                    )}
                    {!ibkrStatus.connected && (
                      <p className="text-muted-foreground mt-1">
                        Make sure TWS is open, API connections are enabled (TWS → Edit → Global Configuration → API → Settings → Enable ActiveX and Socket Clients), and port 7497 is set.
                      </p>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

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
