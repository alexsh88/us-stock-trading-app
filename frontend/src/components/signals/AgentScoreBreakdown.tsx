"use client";

interface AgentScores {
  technical?: number | null;
  fundamental?: number | null;
  sentiment?: number | null;
  catalyst?: number | null;
}

interface Props {
  scores: AgentScores;
}

const AGENTS = [
  { key: "technical" as const, label: "Technical", description: "RSI, MACD, ADX regime, BB Squeeze, Breakout Score, MTF alignment" },
  { key: "fundamental" as const, label: "Fundamental", description: "P/E, FCF, Revenue Growth" },
  { key: "sentiment" as const, label: "Sentiment", description: "News & Reddit analysis" },
  { key: "catalyst" as const, label: "Catalyst", description: "Earnings, SEC filings, news events" },
];

export function AgentScoreBreakdown({ scores }: Props) {
  return (
    <div className="space-y-3">
      {AGENTS.map(({ key, label, description }) => {
        const score = scores[key];
        const pct = score != null ? Math.round(score * 100) : null;
        return (
          <div key={key}>
            <div className="flex justify-between text-sm mb-1">
              <div>
                <span className="font-medium">{label}</span>
                <span className="text-xs text-muted-foreground ml-2">{description}</span>
              </div>
              <span className="font-semibold">{pct != null ? `${pct}%` : "N/A"}</span>
            </div>
            <div className="h-2 bg-secondary rounded-full overflow-hidden">
              {pct != null && (
                <div
                  className={`h-full rounded-full ${
                    pct >= 70 ? "bg-green-500" : pct >= 50 ? "bg-yellow-500" : "bg-red-500"
                  }`}
                  style={{ width: `${pct}%` }}
                />
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
