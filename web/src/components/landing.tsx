"use client";

import { useEffect, useState } from "react";
import { api, type BatchSummaryRow } from "@/lib/api";
import { fmt } from "@/lib/format";
import { ZMeter } from "@/components/verdict";
import { Badge } from "@/components/ui";
import { ArrowsClockwise, Key, Prohibit, type Icon } from "@phosphor-icons/react";

/* Hero visual: a real detector reading of a real record (from the history
   file), not a mock screenshot. Numbers below are the first row of the
   original history: 277 tokens scored, 193 green, z = 6.55. */
const SAMPLE = { tokens: 277, green: 193, z: 6.55, p: 2.9e-11 };

export function HeroPreview() {
  return (
    <div className="rounded-[var(--radius-surface)] border border-line bg-bg-elev p-5 shadow-[var(--shadow-surface)]">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-fg-muted">Detection result</span>
        <Badge tone="accent">LIKELY MARKTEXT</Badge>
      </div>
      <div className="mt-4">
        <ZMeter z={SAMPLE.z} />
      </div>
      <dl className="tabular mt-5 grid grid-cols-3 gap-3 font-mono text-sm">
        <div>
          <dt className="text-[11px] text-fg-faint">tokens scored</dt>
          <dd>{SAMPLE.tokens}</dd>
        </div>
        <div>
          <dt className="text-[11px] text-fg-faint">green tokens</dt>
          <dd>
            {SAMPLE.green} <span className="text-fg-faint">({fmt.pct(SAMPLE.green / SAMPLE.tokens, 1)})</span>
          </dd>
        </div>
        <div>
          <dt className="text-[11px] text-fg-faint">p-value</dt>
          <dd>{fmt.p(SAMPLE.p)}</dd>
        </div>
      </dl>
      <p className="mt-4 text-xs text-fg-faint">A recorded analysis from this installation. Chance level is 50% green.</p>
    </div>
  );
}

/* Step 1 visual: a sentence with its tokens coloured by list membership.
   Green tokens got the bias; the reader sees why "green share" means
   something. The split shown is illustrative; real lists change per position. */
const TOKENS: Array<[string, boolean]> = [
  ["Cryptography", true],
  [" is", true],
  [" the", false],
  [" science", true],
  [" of", true],
  [" protecting", false],
  [" information", true],
  [" from", true],
  [" unauthorized", true],
  [" access", false],
  [".", true],
];

export function TokenStrip() {
  return (
    <p className="rounded-[var(--radius-input)] bg-bg-muted px-3 py-2 font-mono text-sm leading-7">
      {TOKENS.map(([t, green], i) => (
        <span
          key={i}
          className={green ? "rounded bg-accent-soft px-0.5 text-accent-soft-fg" : "rounded px-0.5 text-fg-muted"}
        >
          {t}
        </span>
      ))}
    </p>
  );
}

export function FormulaStrip() {
  return (
    <div className="rounded-[var(--radius-input)] bg-bg-muted px-3 py-3 font-mono text-sm">
      <div>z = (green − γ·T) / √(T·γ·(1 − γ))</div>
      <div className="mt-1 text-fg-muted">= (193 − 138.5) / 8.32 = 6.55</div>
    </div>
  );
}

export function ThresholdStrip() {
  return (
    <ul className="space-y-1.5 text-sm">
      {[
        ["z ≥ 4.0", "LIKELY MARKTEXT", "accent"],
        ["z ≥ 2.0", "POSSIBLE WATERMARK", "warn"],
        ["below", "NOT DETECTED", "neutral"],
        ["under 100 tokens", "INCONCLUSIVE", "muted"],
      ].map(([rule, label, tone]) => (
        <li key={label} className="flex items-center justify-between gap-3 rounded-[var(--radius-input)] bg-bg-muted px-3 py-1.5">
          <span className="font-mono text-xs text-fg-muted">{rule}</span>
          <Badge tone={tone as "accent" | "warn" | "neutral" | "muted"}>{label}</Badge>
        </li>
      ))}
    </ul>
  );
}

/* The measured table from the newest batch. Reads the API when it is up;
   otherwise shows the numbers from the smoke batch recorded in the README. */
const FALLBACK: BatchSummaryRow[] = [
  { mode: "watermarked", max_new_tokens: 150, n: 100, mean_z: 5.22, mean_green_pct: 71.7, flagged_rate: 0.86, possible_or_above_rate: 1, inconclusive_rate: 0.01, retokenize_mismatch: 3, rate_meaning: "TP rate @ z>=4.0" },
  { mode: "normal", max_new_tokens: 150, n: 100, mean_z: -0.35, mean_green_pct: 48.5, flagged_rate: 0, possible_or_above_rate: 0, inconclusive_rate: 0.01, retokenize_mismatch: 7, rate_meaning: "FP rate @ z>=4.0" },
  { mode: "watermarked", max_new_tokens: 50, n: 3, mean_z: 2.26, mean_green_pct: 66.7, flagged_rate: 0, possible_or_above_rate: 0.67, inconclusive_rate: 1, retokenize_mismatch: 0, rate_meaning: "TP rate @ z>=4.0" },
  { mode: "watermarked", max_new_tokens: 300, n: 3, mean_z: 6.42, mean_green_pct: 69.3, flagged_rate: 1, possible_or_above_rate: 1, inconclusive_rate: 0, retokenize_mismatch: 1, rate_meaning: "TP rate @ z>=4.0" },
  { mode: "normal", max_new_tokens: 50, n: 3, mean_z: 0.1, mean_green_pct: 50.7, flagged_rate: 0, possible_or_above_rate: 0, inconclusive_rate: 1, retokenize_mismatch: 0, rate_meaning: "FP rate @ z>=4.0" },
  { mode: "normal", max_new_tokens: 300, n: 3, mean_z: 0.46, mean_green_pct: 51.6, flagged_rate: 0, possible_or_above_rate: 0, inconclusive_rate: 0, retokenize_mismatch: 2, rate_meaning: "FP rate @ z>=4.0" },
];

export function ResultsTable() {
  const [rows, setRows] = useState<BatchSummaryRow[]>(FALLBACK);
  const [label, setLabel] = useState("Recorded batches: 100 prompts at 150 tokens, plus 3 prompts at 50 and 300 tokens.");
  useEffect(() => {
    api
      .experiments()
      .then(async (r) => {
        const biggest = [...r.batches].sort((a, b) => b.rows - a.rows)[0];
        if (!biggest || biggest.rows <= 200) return;
        const d = await api.experiment(biggest.batch_id);
        if (d.summary.length) {
          setRows(d.summary);
          setLabel(`Batch ${biggest.batch_id}: ${biggest.rows} generations from this installation.`);
        }
      })
      .catch(() => {});
  }, []);
  const byLength = new Map<number, { wm?: BatchSummaryRow; nm?: BatchSummaryRow }>();
  for (const r of rows) {
    const e = byLength.get(r.max_new_tokens) ?? {};
    if (r.mode === "watermarked") e.wm = r;
    else e.nm = r;
    byLength.set(r.max_new_tokens, e);
  }
  return (
    <div>
      <div className="overflow-x-auto rounded-[var(--radius-surface)] border border-line">
        <table className="w-full text-sm">
          <thead className="bg-bg-muted text-left text-xs text-fg-muted">
            <tr>
              <th className="px-4 py-2.5 font-medium">Length (tokens)</th>
              <th className="px-4 py-2.5 font-medium">Watermarked flagged (true positive)</th>
              <th className="px-4 py-2.5 font-medium">Normal flagged (false positive)</th>
              <th className="px-4 py-2.5 font-medium">Mean z, watermarked</th>
              <th className="px-4 py-2.5 font-medium">n per cell</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {[...byLength.entries()].sort((a, b) => a[0] - b[0]).map(([L, e]) => (
              <tr key={L}>
                <td className="tabular px-4 py-2.5 font-mono">{L}</td>
                <td className="tabular px-4 py-2.5 font-mono font-medium text-accent-soft-fg">{fmt.pct(e.wm?.flagged_rate)}</td>
                <td className="tabular px-4 py-2.5 font-mono">{fmt.pct(e.nm?.flagged_rate)}</td>
                <td className="tabular px-4 py-2.5 font-mono">{fmt.z(e.wm?.mean_z)}</td>
                <td className="tabular px-4 py-2.5 font-mono">{e.wm?.n ?? "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-fg-muted">{label} Threshold z ≥ 4.0. Rows under 100 scored tokens count as inconclusive.</p>
    </div>
  );
}

/* Section 4 fragment: the three facts behind "not an AI-text detector",
   as a divided list rather than cards. */
const FACTS: Array<{ Icon: Icon; title: string; body: string }> = [
  {
    Icon: Prohibit,
    title: "Not a universal detector",
    body: "NOT DETECTED means this watermark was not found. It says nothing about whether a person or another model wrote the text.",
  },
  {
    Icon: Key,
    title: "One shared secret",
    body: "Whoever holds the key can verify a text, and can also produce one that passes. The key is generated on first run and never leaves the machine.",
  },
  {
    Icon: ArrowsClockwise,
    title: "Change the key, orphan the past",
    body: "Text generated under an old key scores at chance under a new one. The history keeps the parameters of every run so the break is visible.",
  },
];

export function FactList() {
  return (
    <ul className="divide-y divide-line border-y border-line">
      {FACTS.map(({ Icon, title, body }) => (
        <li key={title} className="flex gap-4 py-5">
          <Icon size={22} weight="regular" className="mt-0.5 shrink-0 text-accent-soft-fg" aria-hidden />
          <div>
            <h3 className="font-medium">{title}</h3>
            <p className="pretty mt-1 text-sm text-fg-muted">{body}</p>
          </div>
        </li>
      ))}
    </ul>
  );
}

/* Section 5, lecturers: one prompt from the recorded batch, generated once
   in each mode and scored. Both rows are real (run ids ec8ca564 and
   843167dd, batch b6299b88). */
const PAIR = {
  prompt: "Tell a short story about a lighthouse keeper who finds a bottle.",
  normal: { z: 0.0, green: 73, tokens: 146, seed: 153524, label: "NOT DETECTED" },
  watermarked: { z: 5.46, green: 106, tokens: 146, seed: 418952, label: "LIKELY MARKTEXT" },
};

export function LectureDemo() {
  const cells = [
    ["Normal", PAIR.normal, "neutral"],
    ["Watermarked", PAIR.watermarked, "accent"],
  ] as const;
  return (
    <div className="rounded-[var(--radius-surface)] border border-line bg-bg-elev p-5 shadow-[var(--shadow-surface)]">
      <p className="text-xs font-medium text-fg-muted">Same prompt, both modes</p>
      <p className="mt-1.5 rounded-[var(--radius-input)] bg-bg-muted px-3 py-2 font-mono text-sm">{PAIR.prompt}</p>
      <div className="mt-5 grid gap-5 sm:grid-cols-2">
        {cells.map(([name, r, tone]) => (
          <div key={name} className="space-y-3">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium">{name}</span>
              <Badge tone={tone}>{r.label}</Badge>
            </div>
            <ZMeter z={r.z} />
            <dl className="tabular grid grid-cols-2 gap-2 font-mono text-xs">
              <div>
                <dt className="text-fg-faint">green share</dt>
                <dd>{fmt.pct(r.green / r.tokens, 1)}</dd>
              </div>
              <div>
                <dt className="text-fg-faint">seed</dt>
                <dd>{r.seed}</dd>
              </div>
            </dl>
          </div>
        ))}
      </div>
      <p className="mt-4 text-xs text-fg-faint">Prompt 4 of the recorded batch, 150 tokens each. Chance level is 50% green.</p>
    </div>
  );
}

/* Section 5, researchers: one history row as it is stored, every column a
   fact the analysis can be repeated from. Row 843167dd from the batch. */
const RECORD: Array<[string, string]> = [
  ["run_id", "843167dd"],
  ["timestamp", "2026-09-23 12:24:25"],
  ["source", "batch"],
  ["batch_id", "b6299b88"],
  ["mode", "watermarked"],
  ["seed", "418952"],
  ["tokens_scored", "146"],
  ["green_tokens", "106"],
  ["z_score", "5.46"],
  ["p_value", "2.818e-09"],
  ["bias / ratio", "3.0 / 0.5"],
  ["scheme / context", "selfhash / 5"],
  ["device", "cpu"],
  ["result", "LIKELY MARKTEXT"],
];

export function RecordCard() {
  return (
    <div className="rounded-[var(--radius-surface)] border border-line bg-bg-elev p-5 shadow-[var(--shadow-surface)]">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-fg-muted">One row of the history file</span>
        <span className="font-mono text-xs text-fg-faint">21 columns</span>
      </div>
      <dl className="tabular mt-4 grid grid-cols-2 gap-x-6 gap-y-2.5 font-mono text-xs sm:grid-cols-3">
        {RECORD.map(([k, v]) => (
          <div key={k} className="min-w-0">
            <dt className="truncate text-fg-faint">{k}</dt>
            <dd className={k === "result" ? "truncate text-accent-soft-fg" : "truncate"}>{v}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-4 text-xs text-fg-faint">Filter by any column, add a note, export the set, or delete with a backup taken first.</p>
    </div>
  );
}
