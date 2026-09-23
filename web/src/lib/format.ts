export const fmt = {
  z: (v: number | null | undefined) => (v == null || Number.isNaN(v) ? "-" : v.toFixed(2)),
  pct: (v: number | null | undefined, digits = 0) =>
    v == null || Number.isNaN(v) ? "-" : `${(v * 100).toFixed(digits)}%`,
  pct100: (v: number | null | undefined, digits = 1) =>
    v == null || Number.isNaN(v) ? "-" : `${v.toFixed(digits)}%`,
  p: (v: number | null | undefined) => (v == null || Number.isNaN(v) ? "-" : v.toExponential(2)),
  int: (v: number | null | undefined) => (v == null || Number.isNaN(v) ? "-" : Math.round(v).toLocaleString()),
  minutes: (s: number) => (s < 90 ? `${Math.round(s)} s` : `${Math.round(s / 60)} min`),
};

/* Time estimate for a batch, from the rates measured on the reference CPU:
   about 4.3 tokens/s watermarked, about 8 tokens/s normal. */
export function estimateSeconds(nPrompts: number, lengths: number[], runs: number, modes = 2) {
  const perToken = modes === 2 ? 1 / 4.3 + 1 / 8 : 1 / 4.3;
  return lengths.reduce((acc, L) => acc + nPrompts * runs * L * perToken, 0);
}

export function verdictTone(label: string): "accent" | "warn" | "neutral" | "muted" {
  if (label === "LIKELY MARKTEXT") return "accent";
  if (label === "POSSIBLE WATERMARK") return "warn";
  if (label.startsWith("INCONCLUSIVE")) return "muted";
  return "neutral";
}
