"use client";

import {
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type Point = { tokens_scored: number; z_score: number; result: string; run_id?: string; mode?: string };

const TONES: Record<string, string> = {
  "LIKELY MARKTEXT": "var(--accent)",
  "POSSIBLE WATERMARK": "var(--warn)",
  "NOT DETECTED": "var(--fg-faint)",
  "INCONCLUSIVE (short text)": "var(--line-strong)",
};

/* z-score against tokens scored, one dot per record, with the two
   thresholds drawn so the reader sees the decision, not just the data. */
export function ZChart({
  points,
  detection = 4,
  possible = 2,
  height = 320,
}: {
  points: Point[];
  detection?: number;
  possible?: number;
  height?: number;
}) {
  const groups = Object.keys(TONES).map((label) => ({
    label,
    data: points.filter((p) => p.result === label),
  }));
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer>
        <ScatterChart margin={{ top: 12, right: 16, bottom: 12, left: 0 }}>
          <CartesianGrid stroke="var(--line)" strokeDasharray="2 4" />
          <XAxis
            type="number"
            dataKey="tokens_scored"
            name="tokens scored"
            tick={{ fill: "var(--fg-muted)", fontSize: 11, fontFamily: "var(--font-mono)" }}
            stroke="var(--line-strong)"
            label={{ value: "tokens scored", position: "insideBottom", offset: -4, fill: "var(--fg-muted)", fontSize: 11 }}
          />
          <YAxis
            type="number"
            dataKey="z_score"
            name="z"
            tick={{ fill: "var(--fg-muted)", fontSize: 11, fontFamily: "var(--font-mono)" }}
            stroke="var(--line-strong)"
            width={40}
          />
          <Tooltip
            cursor={{ stroke: "var(--line-strong)" }}
            contentStyle={{
              background: "var(--bg-elev)",
              border: "1px solid var(--line)",
              borderRadius: 8,
              fontSize: 12,
              color: "var(--fg)",
            }}
            formatter={(v, name) => [typeof v === "number" ? v.toFixed(2) : String(v ?? ""), String(name ?? "")]}
          />
          <ReferenceLine y={detection} stroke="var(--fg)" strokeDasharray="6 4" label={{ value: `z = ${detection}`, position: "right", fill: "var(--fg-muted)", fontSize: 11 }} />
          <ReferenceLine y={possible} stroke="var(--fg-faint)" strokeDasharray="3 4" />
          {groups.map((g) => (
            <Scatter key={g.label} name={g.label} data={g.data} fill={TONES[g.label]} fillOpacity={0.85} />
          ))}
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}
