"use client";

import {
  BookOpen, PlayCircle, LayoutDashboard, LineChart, Brain,
  TrendingUp, BarChart2, Activity, Layers, ShieldCheck,
  History, Settings, ChevronRight, Info, Zap, Target,
  AlertTriangle, CheckCircle2, Clock, Globe, Database,
} from "lucide-react";

function Section({ id, icon: Icon, title, children }: {
  id?: string; icon: any; title: string; children: React.ReactNode;
}) {
  return (
    <section id={id} className="space-y-4">
      <div className="flex items-center gap-3 border-b border-border pb-3">
        <div className="p-2 rounded-lg bg-primary/10 text-primary">
          <Icon className="h-5 w-5" />
        </div>
        <h2 className="text-xl font-semibold">{title}</h2>
      </div>
      {children}
    </section>
  );
}

function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-card border border-border rounded-lg p-5 ${className}`}>
      {children}
    </div>
  );
}

function Callout({ icon: Icon, color, title, children }: {
  icon: any; color: string; title: string; children: React.ReactNode;
}) {
  const colors: Record<string, string> = {
    blue:   "bg-blue-500/10 border-blue-500/30 text-blue-400",
    green:  "bg-green-500/10 border-green-500/30 text-green-400",
    yellow: "bg-yellow-500/10 border-yellow-500/30 text-yellow-400",
    red:    "bg-red-500/10 border-red-500/30 text-red-400",
    indigo: "bg-indigo-500/10 border-indigo-500/30 text-indigo-400",
  };
  return (
    <div className={`border rounded-lg p-4 ${colors[color]}`}>
      <div className="flex items-center gap-2 font-medium mb-1">
        <Icon className="h-4 w-4 flex-shrink-0" />
        {title}
      </div>
      <div className="text-sm opacity-90 text-foreground">{children}</div>
    </div>
  );
}

function Badge({ label, color }: { label: string; color: string }) {
  const colors: Record<string, string> = {
    green:  "bg-green-500/20 text-green-400 border border-green-500/30",
    red:    "bg-red-500/20 text-red-400 border border-red-500/30",
    blue:   "bg-blue-500/20 text-blue-400 border border-blue-500/30",
    yellow: "bg-yellow-500/20 text-yellow-400 border border-yellow-500/30",
    indigo: "bg-indigo-500/20 text-indigo-400 border border-indigo-500/30",
    gray:   "bg-secondary text-muted-foreground border border-border",
  };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${colors[color]}`}>
      {label}
    </span>
  );
}

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-4">
      <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary text-primary-foreground flex items-center justify-center text-sm font-bold">
        {n}
      </div>
      <div className="pt-1 space-y-1">
        <p className="font-medium">{title}</p>
        <p className="text-sm text-muted-foreground">{children}</p>
      </div>
    </div>
  );
}

export default function GuidePage() {
  return (
    <div className="max-w-3xl space-y-12 pb-16">

      {/* Header */}
      <div className="space-y-2">
        <div className="flex items-center gap-3">
          <BookOpen className="h-7 w-7 text-primary" />
          <h1 className="text-3xl font-bold">How It Works</h1>
        </div>
        <p className="text-muted-foreground">
          A complete guide to the AI trading pipeline — what every indicator means, how to read signals, and how to use the charts.
        </p>
      </div>

      {/* Quick nav */}
      <Card className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-sm">
        {[
          ["Running an Analysis", "#run"],
          ["Signal Cards", "#signals"],
          ["The Chart", "#chart"],
          ["ADX Regime", "#adx"],
          ["MTF Alignment", "#mtf"],
          ["BB Squeeze", "#squeeze"],
          ["EMA 150 & Streak", "#ema150"],
          ["Breakout Score", "#breakout"],
          ["RS Rank", "#rs"],
          ["Sector Rotation", "#sector"],
          ["Smart Caching", "#caching"],
          ["History", "#history"],
          ["Settings", "#settings"],
        ].map(([label, href]) => (
          <a
            key={href}
            href={href}
            className="flex items-center gap-1 text-muted-foreground hover:text-foreground hover:bg-secondary rounded px-2 py-1.5 transition-colors"
          >
            <ChevronRight className="h-3 w-3 flex-shrink-0" />
            {label}
          </a>
        ))}
      </Card>

      {/* ── 1. Running an Analysis ── */}
      <Section id="run" icon={PlayCircle} title="Running an Analysis">
        <Card className="space-y-5">
          <div className="space-y-4">
            <Step n={1} title="(Optional) Configure your watchlist">
              Go to <strong>Settings</strong> and type comma-separated tickers like{" "}
              <code className="bg-secondary px-1 rounded text-xs">AAPL, NVDA, MSFT</code>.
              Leave it empty to let the ETF-first auto-screener dynamically build the universe from today&apos;s strongest sectors.
            </Step>
            <Step n={2} title="Choose Top N and click Run Analysis">
              Top N controls how many final signals the synthesizer returns. The pipeline
              always screens more candidates internally — Top N is just the output limit.
            </Step>
            <Step n={3} title="Watch the status banner">
              Shows "screened X tickers" while running, then switches to signal count
              when complete. The full pipeline takes 1–3 minutes depending on universe size.
            </Step>
            <Step n={4} title="Click any signal card to open the chart">
              Each card links to the detail page with candlesticks, overlays, and the
              full agent reasoning breakdown.
            </Step>
          </div>
        </Card>

        <Callout icon={Info} color="blue" title="How the pipeline selects stocks">
          The screener first ranks all 14 sector ETFs by weekly momentum vs SPY. It pulls stocks
          only from the top N leading sectors (default: top 3, ~40–65 candidates). Those candidates
          are then filtered by price ($5–$2000), volume, ATR volatility, and RS rank. Four AI agents
          score each surviving stock in parallel — technical, fundamental, sentiment, and catalyst —
          before a synthesizer makes the final BUY/SELL/SKIP decision.
        </Callout>
      </Section>

      {/* ── 2. Signal Cards ── */}
      <Section id="signals" icon={LayoutDashboard} title="Reading a Signal Card">
        <Card className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
            <div className="space-y-3">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <Badge label="BUY" color="green" />
                  <Badge label="SELL" color="red" />
                  <span className="text-muted-foreground text-xs">+ confidence %</span>
                </div>
                <p className="text-muted-foreground">
                  The synthesizer&apos;s final decision. Only BUY/SELL signals with
                  confidence ≥ 60% are shown — lower-conviction setups are discarded.
                </p>
              </div>
              <div>
                <p className="font-medium mb-1">Entry / Stop / Target</p>
                <p className="text-muted-foreground">
                  Entry = current price at analysis time. Stop = ATR-based stop loss.
                  Target = calculated take-profit. The R:R ratio shows how many dollars
                  you make for every dollar risked.
                </p>
              </div>
            </div>
            <div className="space-y-3">
              <div>
                <p className="font-medium mb-1">Position Size %</p>
                <p className="text-muted-foreground">
                  Kelly-criterion sizing, capped at 5% of portfolio per trade. Higher
                  confidence = larger recommended size.
                </p>
              </div>
              <div>
                <p className="font-medium mb-1">Agent Score Bars</p>
                <p className="text-muted-foreground">
                  Technical · Fundamental · Sentiment · Catalyst. Each 0.0–1.0.
                  The composite is weighted 35/25/20/20. A high composite with one
                  weak score is still valid — one agent can miss.
                </p>
              </div>
            </div>
          </div>
        </Card>
      </Section>

      {/* ── 3. The Chart ── */}
      <Section id="chart" icon={LineChart} title="Reading the Chart">
        <Card className="space-y-4">
          <p className="text-sm text-muted-foreground">
            The signal detail chart has four layers rendered on top of each other:
          </p>
          <div className="space-y-3">
            {[
              {
                swatch: "bg-green-500",
                label: "Green/Red candles",
                desc: "Standard candlesticks. Green = close above open. Red = close below open. Wick = intraday range.",
              },
              {
                swatch: "border-t-2 border-dotted border-indigo-400",
                swatchType: "line",
                label: "Dotted indigo lines — BB Bands",
                desc: "Upper and lower Bollinger Bands (20-day, 2σ). Price touching the upper band = extended / overbought. Touching the lower = oversold. Bands contracting = squeeze building.",
              },
              {
                swatch: "border-t border-dashed border-indigo-400/50",
                swatchType: "line",
                label: "Dashed indigo — BB Mid (20-day SMA)",
                desc: "The 20-day simple moving average. Acts as dynamic support in uptrends and resistance in downtrends.",
              },
              {
                swatch: "border-t border-dashed border-red-500",
                swatchType: "line",
                label: "Red dashed horizontals — Swing Resistance",
                desc: "Recent swing highs — price levels where sellers previously took control. A candle closing above these = bullish breakout.",
              },
              {
                swatch: "border-t border-dashed border-green-500",
                swatchType: "line",
                label: "Green dashed horizontals — Swing Support",
                desc: "Recent swing lows — price levels where buyers stepped in. Good zones for stop-loss placement.",
              },
              {
                swatch: "bg-green-500/40",
                label: "Volume bars (bottom panel)",
                desc: "Green = up-candle volume, red = down-candle volume. A volume bar 1.5× taller than average on a breakout candle = confirmed move.",
              },
              {
                swatch: "bg-gray-400",
                label: "Grey dashed — Entry",
                desc: "The suggested entry price from the analysis.",
              },
              {
                swatch: "bg-red-500",
                label: "Red solid — Stop Loss",
                desc: "ATR-based stop. Exit if price closes below this.",
              },
              {
                swatch: "bg-green-500",
                label: "Green solid — Take Profit Target",
                desc: "The target price for the trade.",
              },
            ].map(({ swatch, swatchType, label, desc }) => (
              <div key={label} className="flex gap-3 text-sm">
                <div className="flex-shrink-0 w-10 flex items-center justify-center">
                  {swatchType === "line" ? (
                    <div className={`w-8 ${swatch}`} />
                  ) : (
                    <div className={`w-3 h-3 rounded-sm ${swatch}`} />
                  )}
                </div>
                <div>
                  <span className="font-medium">{label}</span>
                  <span className="text-muted-foreground"> — {desc}</span>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </Section>

      {/* ── 4. ADX Regime ── */}
      <Section id="adx" icon={Activity} title="ADX Regime Filter">
        <Card className="space-y-4">
          <p className="text-sm text-muted-foreground">
            ADX (Average Directional Index, period 14) measures <strong>trend strength</strong>,
            not direction. It&apos;s used as a meta-filter that switches the pipeline between
            two distinct modes depending on market conditions.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {[
              {
                badge: "Trending", badgeColor: "green",
                threshold: "ADX > 25",
                desc: "Strong trend in play. Pipeline weights momentum signals — MACD direction, price vs SMA, breakouts above resistance.",
                tip: "Momentum setups like breakouts are reliable here.",
              },
              {
                badge: "Neutral", badgeColor: "yellow",
                threshold: "ADX 20–25",
                desc: "Ambiguous — transitioning between trending and choppy. Signals are still generated but weighted conservatively.",
                tip: "Be more selective. Wait for clearer regime.",
              },
              {
                badge: "Choppy", badgeColor: "red",
                threshold: "ADX < 20",
                desc: "No trend. Pipeline weights mean-reversion signals — RSI extremes, BB band bounces, oversold conditions.",
                tip: "Don't chase breakouts here. They usually fail.",
              },
            ].map(({ badge, badgeColor, threshold, desc, tip }) => (
              <div key={badge} className="bg-secondary/50 rounded-lg p-4 space-y-2">
                <div className="flex items-center justify-between">
                  <Badge label={badge} color={badgeColor as any} />
                  <span className="text-xs font-mono text-muted-foreground">{threshold}</span>
                </div>
                <p className="text-sm text-muted-foreground">{desc}</p>
                <p className="text-xs text-primary/80 font-medium">{tip}</p>
              </div>
            ))}
          </div>
        </Card>
        <Callout icon={Brain} color="indigo" title="Why this matters">
          Using RSI in a trending market generates constant false oversold signals — the stock keeps going up.
          Using MACD in a choppy market generates endless whipsaws. ADX lets the pipeline adapt its logic
          to current conditions rather than applying fixed rules blindly.
        </Callout>
      </Section>

      {/* ── 5. MTF ── */}
      <Section id="mtf" icon={Layers} title="Multi-Timeframe (MTF) Alignment">
        <Card className="space-y-4">
          <p className="text-sm text-muted-foreground">
            MTF alignment checks whether the <strong>weekly trend agrees with the daily setup</strong>.
            Specifically: is the current price above the 20-week simple moving average?
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="bg-green-500/10 border border-green-500/20 rounded-lg p-4 space-y-2">
              <div className="flex items-center gap-2 text-green-400 font-medium">
                <CheckCircle2 className="h-4 w-4" />
                MTF Aligned = YES
              </div>
              <p className="text-sm text-muted-foreground">
                Price is above the 20-week SMA. Weekly trend is bullish. A daily BUY setup
                in a weekly uptrend has a meaningfully higher win rate than a counter-trend trade.
              </p>
            </div>
            <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-4 space-y-2">
              <div className="flex items-center gap-2 text-red-400 font-medium">
                <AlertTriangle className="h-4 w-4" />
                MTF Aligned = NO
              </div>
              <p className="text-sm text-muted-foreground">
                Price is below the 20-week SMA. Trading against the weekly downtrend.
                The signal is still generated but scored lower. Treat with extra caution.
              </p>
            </div>
          </div>
        </Card>
      </Section>

      {/* ── 5b. EMA 150 & Streak ── */}
      <Section id="ema150" icon={TrendingUp} title="EMA 150 Distance & Day Streak">
        <Card className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Two indicators that measure <strong>how extended a stock is</strong> relative to its
            trend and recent momentum — both help avoid buying at the top of an overextended move.
          </p>

          <div className="space-y-4">
            <div>
              <p className="font-medium text-sm mb-2">EMA 150 Distance (Weinstein Stage 2)</p>
              <p className="text-sm text-muted-foreground mb-3">
                Shows how far the current price is from the 150-day Exponential Moving Average,
                expressed as a percentage. This is the key trend filter from Stan Weinstein&apos;s
                Stage Analysis — stocks in <em>Stage 2 uptrends</em> trade clearly above their EMA 150.
              </p>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                {[
                  { range: "−∞ to 0%",   label: "Below EMA 150",      color: "bg-red-500/10 text-red-400 border border-red-500/20",      tip: "Stage 3/4 downtrend — avoid longs, −0.10 score penalty" },
                  { range: "0% to +5%",  label: "Just above",          color: "bg-yellow-500/10 text-yellow-400 border border-yellow-500/20", tip: "Early Stage 2 or recovery — neutral" },
                  { range: "+5% to +25%", label: "Healthy uptrend",    color: "bg-green-500/10 text-green-400 border border-green-500/20",  tip: "Ideal range — trend intact, not overextended" },
                  { range: "> +25%",     label: "Overextended",         color: "bg-orange-500/10 text-orange-400 border border-orange-500/20", tip: "Pullback risk — −0.08 score penalty" },
                ].map(({ range, label, color, tip }) => (
                  <div key={range} className={`rounded-lg p-3 ${color}`}>
                    <p className="font-mono font-bold text-xs">{range}</p>
                    <p className="font-medium mt-1">{label}</p>
                    <p className="opacity-80 mt-0.5">{tip}</p>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <p className="font-medium text-sm mb-2">Consecutive Day Streak</p>
              <p className="text-sm text-muted-foreground mb-3">
                Counts consecutive days the stock closed higher (positive) or lower (negative).
                A long streak in the right regime is momentum confirmation; in choppy conditions
                it signals mean-reversion risk.
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
                <div className="bg-green-500/10 border border-green-500/20 rounded-lg p-3 space-y-1">
                  <div className="flex items-center gap-2 text-green-400 font-medium text-xs">
                    <CheckCircle2 className="h-4 w-4" />
                    Trending (ADX &gt; 25) + Streak ≥ 5
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Momentum confirmation. A stock running 5+ days in a strong trend is showing
                    institutional follow-through — not necessarily exhausted.
                  </p>
                </div>
                <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-3 space-y-1">
                  <div className="flex items-center gap-2 text-red-400 font-medium text-xs">
                    <AlertTriangle className="h-4 w-4" />
                    Choppy (ADX &lt; 20) + Streak ≥ 5 + RSI &gt; 65
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Mean-reversion risk. Without a real trend engine, a 5-day run in a choppy
                    market is often exhaustion. Pipeline scores −0.08 here.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </Card>
        <Callout icon={Brain} color="indigo" title="Why these matter together">
          A stock at EMA150 +30% with a 6-day streak in a choppy market is the classic &quot;late to the party&quot;
          setup — the pipeline will score it significantly lower than a stock at EMA150 +10% with a 3-day
          streak in a trending regime, even if their RSI and MACD look similar.
        </Callout>
      </Section>

      {/* ── 6. BB Squeeze ── */}
      <Section id="squeeze" icon={Zap} title="Bollinger Band Squeeze">
        <Card className="space-y-4">
          <p className="text-sm text-muted-foreground">
            A BB Squeeze occurs when the Bollinger Bands (20-day, 2σ) contract <em>inside</em> the
            Keltner Channel (EMA20 ± 1.5×ATR10). This signals compressed volatility — the market is
            coiling before an explosive move.
          </p>
          <div className="space-y-3">
            <div className="flex gap-3 text-sm">
              <Badge label="In Squeeze" color="yellow" />
              <span className="text-muted-foreground">
                Volatility compressed. A big move is building but direction is unknown yet.
                The longer the squeeze, the more powerful the eventual breakout.
                <em> Also shows "X bars" — longer squeeze = more energy stored.</em>
              </span>
            </div>
            <div className="flex gap-3 text-sm">
              <Badge label="Squeeze Released" color="green" />
              <span className="text-muted-foreground">
                The squeeze just ended in the last 1–3 bars. Volatility is expanding.
                The first candle outside the bands suggests the breakout direction.
                This is the <strong>highest-value signal</strong> — momentum burst is just starting.
              </span>
            </div>
            <div className="flex gap-3 text-sm">
              <Badge label="No Squeeze" color="gray" />
              <span className="text-muted-foreground">
                Normal volatility environment. Bands are wider than the Keltner Channel.
              </span>
            </div>
          </div>
        </Card>
        <Callout icon={Info} color="yellow" title="Combine with volume and regime">
          A squeeze release in a <strong>trending regime (ADX&gt;25)</strong> with a volume spike is a
          high-conviction breakout setup. A squeeze release in a choppy regime often results in a
          head-fake — wait for volume confirmation before acting.
        </Callout>
      </Section>

      {/* ── 7. Breakout Score ── */}
      <Section id="breakout" icon={Target} title="Volume-Confirmed Breakout Score">
        <Card className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Three checkpoints that must all be met for a high-conviction breakout.
            The score (0–3) is shown in the technical reasoning and used by the synthesizer.
          </p>
          <div className="space-y-3">
            {[
              {
                n: "1", label: "Price broke swing resistance",
                desc: "The most recent closing price is above the nearest swing high (resistance level).",
              },
              {
                n: "2", label: "Volume ≥ 1.5× 20-day average",
                desc: "The breakout candle had significantly above-average volume — institutions are participating, not just retail noise.",
              },
              {
                n: "3", label: "RSI > 50 at breakout",
                desc: "Momentum is positive. RSI below 50 on a breakout often means the move lacks strength and may fail.",
              },
            ].map(({ n, label, desc }) => (
              <div key={n} className="flex gap-4 text-sm">
                <div className="flex-shrink-0 w-7 h-7 rounded-full bg-primary/20 text-primary flex items-center justify-center font-bold text-xs">
                  {n}
                </div>
                <div>
                  <p className="font-medium">{label}</p>
                  <p className="text-muted-foreground">{desc}</p>
                </div>
              </div>
            ))}
          </div>
          <div className="grid grid-cols-4 gap-2 pt-2">
            {[
              { score: "0/3", label: "No signal", color: "bg-secondary text-muted-foreground" },
              { score: "1/3", label: "Watch only", color: "bg-yellow-500/10 text-yellow-400 border border-yellow-500/20" },
              { score: "2/3", label: "Moderate", color: "bg-blue-500/10 text-blue-400 border border-blue-500/20" },
              { score: "3/3", label: "High conviction", color: "bg-green-500/10 text-green-400 border border-green-500/20" },
            ].map(({ score, label, color }) => (
              <div key={score} className={`rounded-lg p-3 text-center ${color}`}>
                <p className="font-bold text-base">{score}</p>
                <p className="text-xs mt-0.5 opacity-80">{label}</p>
              </div>
            ))}
          </div>
        </Card>
      </Section>

      {/* ── 8. RS Rank ── */}
      <Section id="rs" icon={TrendingUp} title="Relative Strength Rank">
        <Card className="space-y-4">
          <p className="text-sm text-muted-foreground">
            At the screener stage, every stock&apos;s 1-month return relative to SPY is computed.
            Only stocks in the <strong>top 20% (80th percentile)</strong> of that RS ranking enter the
            analysis pipeline. This implements the Jegadeesh-Titman momentum factor — one of the
            most consistently validated effects in academic finance.
          </p>
          <div className="bg-secondary/50 rounded-lg p-4 space-y-2 text-sm">
            <p className="font-medium">Why top 20% specifically?</p>
            <p className="text-muted-foreground">
              Stocks with strong recent relative performance tend to continue outperforming over
              the next 1–3 months. The effect is strongest in the top quintile. Below the 60th
              percentile, the predictive power drops significantly. Combined with the ETF-first
              sector filter (40–65 sector-focused candidates), keeping only top-20% RS narrows
              the final analysis pool to ~10–20 tickers — meaning LLM agents focus only on the
              highest-quality setups.
            </p>
          </div>
        </Card>
      </Section>

      {/* ── 9. Sector Rotation ── */}
      <Section id="sector" icon={Globe} title="ETF-First Sector Rotation">
        <Card className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Instead of scanning a static list of stocks, the screener starts by ranking
            <strong> all 14 sector ETFs</strong> against SPY. Only stocks that belong to the
            leading sectors are included in the universe — so if Energy is the strongest sector
            this week, Energy stocks dominate the candidate pool.
          </p>

          <div className="space-y-3 text-sm">
            <p className="font-medium">Two-pass process:</p>
            <div className="space-y-2">
              <div className="flex gap-3 items-start">
                <span className="flex-shrink-0 w-6 h-6 rounded-full bg-blue-500/20 text-blue-400 flex items-center justify-center text-xs font-bold">1</span>
                <div>
                  <p className="font-medium">ETF ranking (upstream universe selection)</p>
                  <p className="text-muted-foreground">
                    All 14 ETFs (XLK, XLE, XLF, XLV, XLI, XLC, XLB, XLP, XLU, XLRE, XLY, GLD, SLV, USO)
                    are scored as <code className="bg-secondary px-1 rounded text-xs">0.6 × RS_5d + 0.4 × RS_1mo</code> vs SPY.
                    Top N ETFs (configurable via <strong>Sector Breadth</strong> setting, default 3) are selected.
                    Their mapped stock pools are merged into the dynamic candidate universe (~40–65 tickers).
                  </p>
                </div>
              </div>
              <div className="flex gap-3 items-start">
                <span className="flex-shrink-0 w-6 h-6 rounded-full bg-purple-500/20 text-purple-400 flex items-center justify-center text-xs font-bold">2</span>
                <div>
                  <p className="font-medium">Post-screener sector filter (news-adjusted)</p>
                  <p className="text-muted-foreground">
                    After RS filtering, Claude Haiku re-ranks top sectors factoring in today&apos;s
                    Finnhub headlines. If Energy has strong RS <em>and</em> positive news (rising oil),
                    it ranks higher. If Financials have good RS but negative headlines (rate shock),
                    it adjusts down. Result cached 4h.
                  </p>
                </div>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-4 sm:grid-cols-7 gap-2 text-xs text-center">
            {["XLK Tech", "XLE Energy", "XLF Finance", "XLV Health", "XLI Industry", "XLB Materials", "XLC Comms", "GLD Gold", "USO Oil", "XLY Disc", "XLP Staples", "XLU Util", "XLRE REIT", "SLV Silver"].map(s => (
              <div key={s} className="bg-secondary rounded-lg py-2 px-1 text-muted-foreground font-medium">{s}</div>
            ))}
          </div>

          <Callout icon={CheckCircle2} color="green" title="Safe fallback">
            If ETF ranking fails (network error), the screener falls back to a broad static universe
            covering all sectors. The sector breadth setting (1–14) lets you control focus vs variety
            — set to 14 to replicate the old all-sectors behaviour.
          </Callout>
        </Card>
      </Section>

      {/* ── 10. Smart Caching ── */}
      <Section id="caching" icon={Database} title="Smart Caching">
        <Card className="space-y-4">
          <p className="text-sm text-muted-foreground">
            LLM scores are cached in Redis so repeated runs within the same time window skip
            redundant API calls. <strong>Indicator data (RSI, ADX, etc.) is always recomputed fresh</strong>
            — only the expensive LLM scoring step is cached.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
            {[
              { node: "Technical",    ttl: "2 hours",  reason: "Indicator setups change slowly intraday. Second run in the same 2h window is instant." },
              { node: "Fundamental",  ttl: "24 hours", reason: "P/E, FCF, margins are quarterly data — unchanged within a trading day." },
              { node: "Sentiment",    ttl: "30 min",   reason: "News and Reddit signals move fast. Scores refresh every half-hour bucket." },
              { node: "Catalyst",     ttl: "4 hours",  reason: "Earnings dates and news counts change slowly. Refreshed mid-day." },
              { node: "Sector",       ttl: "4 hours",  reason: "Sector rankings are stable through a trading day. Fetched once per morning." },
            ].map(({ node, ttl, reason }) => (
              <div key={node} className="bg-secondary/50 rounded-lg p-3 space-y-1">
                <div className="flex items-center justify-between">
                  <span className="font-medium">{node}</span>
                  <span className="text-xs bg-primary/10 text-primary px-2 py-0.5 rounded">{ttl}</span>
                </div>
                <p className="text-xs text-muted-foreground">{reason}</p>
              </div>
            ))}
          </div>
          <Callout icon={Info} color="blue" title="Cache keys include ticker + date (+ mode for technical)">
            If you change trading mode from Swing to Intraday, the technical scores are re-scored
            because the mode is part of the cache key. All other nodes are mode-agnostic and share
            the same daily cache.
          </Callout>
        </Card>
      </Section>

      {/* ── 11. History ── */}
      <Section id="history" icon={History} title="Run History">
        <Card className="space-y-3 text-sm text-muted-foreground">
          <p>
            Every analysis run is saved permanently. Signals are never deleted — each run has its
            own ID and the signals belong to that run.
          </p>
          <p>
            The <strong>dropdown in the top-right of the dashboard</strong> lets you switch between
            past runs. Useful for comparing what the pipeline generated yesterday vs today, or
            reviewing a signal you already acted on.
          </p>
          <p>
            The status banner always shows the run date, signal count, tickers screened, and
            trading mode (swing vs intraday) so you know exactly which run you&apos;re looking at.
          </p>
        </Card>
      </Section>

      {/* ── 10. Settings ── */}
      <Section id="settings" icon={Settings} title="Settings Reference">
        <Card className="space-y-4">
          <div className="space-y-4 text-sm">
            {[
              {
                label: "Top N Stocks",
                desc: "How many signals the synthesizer returns per run. The pipeline always screens more internally — this is only the output limit. Default: 5.",
              },
              {
                label: "Trading Mode",
                desc: "Swing (2–5 day holds, ATR-2× stops) or Intraday (same-day, ATR-1.5× stops). Affects stop distances, position sizing, and which indicators the pipeline emphasises. VWAP is only used in Intraday mode.",
              },
              {
                label: "Sector Breadth",
                desc: "Slider 1–14. Controls how many leading sector ETFs contribute stocks to the candidate universe. 1 = single strongest sector only (~10–15 stocks, very focused). 3 = default (~40–65 stocks, good balance of focus and variety). 14 = all sectors (~100+ stocks, same as old static screener with no rotation bias).",
              },
              {
                label: "Custom Watchlist",
                desc: "Comma-separated tickers, e.g. AAPL, NVDA, TSLA. When populated, the ETF-first auto-screener is completely bypassed — the exact tickers you enter go straight to the four analysis agents. Leave empty to use the ETF-first sector screener.",
              },
              {
                label: "Paper Trading Mode",
                desc: "When enabled (default), all signals are paper trades only — no real orders are placed. Disable only when IBKR live trading integration is configured (Phase 3).",
              },
            ].map(({ label, desc }) => (
              <div key={label} className="border-b border-border pb-3 last:border-0 last:pb-0">
                <p className="font-medium mb-1">{label}</p>
                <p className="text-muted-foreground">{desc}</p>
              </div>
            ))}
          </div>
        </Card>
      </Section>

      {/* ── Pipeline overview ── */}
      <Section icon={Brain} title="Full Pipeline Overview">
        <Card className="space-y-4 text-sm">
          <div className="space-y-2">
            {[
              { icon: ShieldCheck, label: "Screener",            color: "text-blue-400",   desc: "Ranks 14 sector ETFs → builds dynamic stock pool from top N sectors (~40–65 tickers) → filters by price, volume, ATR, RS rank → ~10–20 final candidates. No LLM, pure math." },
              { icon: Globe,       label: "Sector Rotation",    color: "text-sky-400",    desc: "Re-ranks top sectors by RS + today's Finnhub news (Haiku). Removes candidates from lagging sectors. Result cached 4h." },
              { icon: Activity,    label: "Technical Agent",    color: "text-indigo-400", desc: "RSI, MACD, ADX, EMA150 distance, day streak, BB Squeeze, Breakout Score, Swing Levels, MTF alignment → Haiku scores 0–1. Cached 2h." },
              { icon: BarChart2,   label: "Fundamental Agent",  color: "text-violet-400", desc: "P/E, revenue growth, FCF yield, margins via yfinance → Haiku scores 0–1. Cached 24h." },
              { icon: TrendingUp,  label: "Sentiment Agent",    color: "text-pink-400",   desc: "Finnhub news + ApeWisdom Reddit mentions → Haiku scores 0–1. Cached 30min." },
              { icon: Zap,         label: "Catalyst Agent",     color: "text-orange-400", desc: "Earnings dates, recent news events → Haiku scores 0–1. Cached 4h." },
              { icon: Target,      label: "Risk Manager",       color: "text-yellow-400", desc: "ATR-based stops (2× swing, 1.5× intraday), Kelly position sizing capped at 5%. Pure math." },
              { icon: Brain,       label: "Synthesizer",        color: "text-green-400",  desc: "All scores + regime + MTF data → Claude Sonnet produces final BUY/SELL/SKIP with entry, stop, target. Skipped entirely when bear regime (SPY < MA200×0.97 or VIX > 35). Top N returned." },
            ].map(({ icon: Icon, label, color, desc }, i, arr) => (
              <div key={label} className="flex gap-3">
                <div className="flex flex-col items-center">
                  <div className={`p-1.5 rounded-md bg-secondary ${color}`}>
                    <Icon className="h-4 w-4" />
                  </div>
                  {i < arr.length - 1 && <div className="w-px flex-1 bg-border mt-1" />}
                </div>
                <div className="pb-3">
                  <p className="font-medium">{label}</p>
                  <p className="text-muted-foreground">{desc}</p>
                </div>
              </div>
            ))}
          </div>
          <div className="bg-secondary/50 rounded-lg p-3 flex items-center gap-2 text-xs text-muted-foreground">
            <Clock className="h-3.5 w-3.5 flex-shrink-0" />
            Typical cost: ~$0.026/run (4 Haiku + 1 Sonnet call). ~$0.40/month for daily use. On warm cache: sector + synthesizer only (~$0.005). Full cold run time: 1–3 min.
          </div>
        </Card>
      </Section>

    </div>
  );
}
