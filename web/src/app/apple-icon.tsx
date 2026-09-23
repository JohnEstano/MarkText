import { ImageResponse } from "next/og";
import { MARK_VIEWBOX, LEG_LEFT, LEG_RIGHT, RING, STEM } from "@/components/mark-paths";

export const size = { width: 180, height: 180 };
export const contentType = "image/png";

/* Apple touch icon: the mark on a solid light tile (iOS adds its own
   rounding, so the tile has square corners). */
export default function AppleIcon() {
  return new ImageResponse(
    (
      <div style={{ width: 180, height: 180, background: "#fafafa", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <svg width="132" height="132" viewBox={MARK_VIEWBOX}>
          <path d={LEG_LEFT} fill="#18181b" />
          <path d={LEG_RIGHT} fill="#18181b" />
          <circle cx={RING.cx} cy={RING.cy} r={RING.r} fill="none" stroke="#2f7d5b" strokeWidth={RING.width} />
          <line x1={STEM.x} y1={STEM.y1} x2={STEM.x} y2={STEM.y2} stroke="#2f7d5b" strokeWidth={STEM.width} strokeLinecap="round" />
        </svg>
      </div>
    ),
    size,
  );
}
