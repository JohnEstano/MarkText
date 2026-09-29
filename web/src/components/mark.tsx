import { MARK_VIEWBOX, LEG_LEFT, LEG_RIGHT, RING, STEM } from "@/components/mark-paths";

/* The MarkText mark: an M whose middle stroke is a green key. Legs take the
   current text colour, the key takes the accent token, so one component
   works in light and dark. Geometry in mark-paths.ts. */
export function Mark({ size = 20, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox={MARK_VIEWBOX} aria-hidden="true" focusable="false" className={className}>
      <path d={LEG_LEFT} fill="currentColor" />
      <path d={LEG_RIGHT} fill="currentColor" />
      <circle cx={RING.cx} cy={RING.cy} r={RING.r} fill="none" stroke="var(--accent)" strokeWidth={RING.width} />
      <line x1={STEM.x} y1={STEM.y1} x2={STEM.x} y2={STEM.y2} stroke="var(--accent)" strokeWidth={STEM.width} strokeLinecap="round" />
    </svg>
  );
}
