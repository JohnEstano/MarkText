"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
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

const MODEL_KEYS = ["Flagged", "Possible", "Not AI writing", "Inconclusive"] as const;
const MODEL_FILLS: Record<(typeof MODEL_KEYS)[number], string> = {
  Flagged: TONES["LIKELY MARKTEXT"],
  Possible: TONES["POSSIBLE WATERMARK"],
  "Not AI writing": TONES["NOT DETECTED"],
  Inconclusive: TONES["INCONCLUSIVE (short text)"],
};

/* One stacked bar per model: which model each score names. Rows with no
   model land in "Unknown" so old rows stay visible instead of vanishing. */
export function ModelBars({
  rows,
  height = 260,
}: {
  rows: Array<{ model?: string; result: string }>;
  height?: number;
}) {
  const models = [...new Set(rows.map((r) => r.model || "Unknown"))];
  const data = models.map((model) => {
    const own = rows.filter((r) => (r.model || "Unknown") === model);
    const count = (label: string) => own.filter((r) => r.result === label).length;
    return {
      model,
      Flagged: count("LIKELY MARKTEXT"),
      Possible: count("POSSIBLE WATERMARK"),
      "Not AI writing": count("NOT DETECTED"),
      Inconclusive: own.length - count("LIKELY MARKTEXT") - count("POSSIBLE WATERMARK") - count("NOT DETECTED"),
    };
  });
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 12, right: 16, bottom: 12, left: 0 }}>
          <CartesianGrid stroke="var(--line)" strokeDasharray="2 4" vertical={false} />
          <XAxis
            dataKey="model"
            tick={{ fill: "var(--fg-muted)", fontSize: 11, fontFamily: "var(--font-mono)" }}
            stroke="var(--line-strong)"
            interval={0}
          />
          <YAxis
            allowDecimals={false}
            tick={{ fill: "var(--fg-muted)", fontSize: 11, fontFamily: "var(--font-mono)" }}
            stroke="var(--line-strong)"
            width={32}
          />
          <Tooltip
            cursor={{ fill: "var(--bg-muted)" }}
            contentStyle={{
              background: "var(--bg-elev)",
              border: "1px solid var(--line)",
              borderRadius: 8,
              fontSize: 12,
              color: "var(--fg)",
            }}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          {MODEL_KEYS.map((k) => (
            <Bar key={k} dataKey={k} stackId="models" fill={MODEL_FILLS[k]} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
