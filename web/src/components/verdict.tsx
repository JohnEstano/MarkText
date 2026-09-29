"use client";

import { motion, useReducedMotion } from "motion/react";
import { Badge } from "@/components/ui";
import { fmt, verdictTone } from "@/lib/format";

export function VerdictBadge({ label, className }: { label: string; className?: string }) {
  return (
    <Badge tone={verdictTone(label)} className={className}>
      {label}
    </Badge>
  );
}

/* A horizontal z-score meter. The fill animates once from zero to the
   value, which is the one motion on the landing page that explains the
   product: the further right, the stronger the evidence. */
export function ZMeter({
  z,
  detection = 4,
  possible = 2,
  max = 10,
}: {
  z: number;
  detection?: number;
  possible?: number;
  max?: number;
}) {
  const reduce = useReducedMotion();
  const clamp = (v: number) => Math.max(0, Math.min(max, v));
  const pct = (v: number) => `${(clamp(v) / max) * 100}%`;
  return (
    <div>
      <div className="relative h-3 w-full overflow-hidden rounded-full bg-bg-muted">
        <motion.div
          className="h-full rounded-full bg-accent"
          initial={reduce ? { width: pct(z) } : { width: 0 }}
          animate={{ width: pct(z) }}
          transition={{ type: "spring", stiffness: 60, damping: 18 }}
        />
        <span
          aria-hidden
          className="absolute top-0 h-full w-px bg-fg/40"
          style={{ left: pct(possible) }}
          title={`possible: z ≥ ${possible}`}
        />
        <span
          aria-hidden
          className="absolute top-0 h-full w-px bg-fg"
          style={{ left: pct(detection) }}
          title={`likely: z ≥ ${detection}`}
        />
      </div>
      <div className="tabular mt-1 flex justify-between font-mono text-[11px] text-fg-faint">
        <span>0</span>
        <span>z = {fmt.z(z)}</span>
        <span>{max}+</span>
      </div>
    </div>
  );
}
