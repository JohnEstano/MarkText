import { ImageResponse } from "next/og";
import { MARK_VIEWBOX, LEG_LEFT, LEG_RIGHT, RING, STEM } from "@/components/mark-paths";

export const alt = "MarkText: watermark text you generate. Prove it later.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

/* Social preview: mark, wordmark and the one-line promise on the light
   surface, with the accent kept to the key. */
export default function OpenGraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: 1200,
          height: 630,
          background: "#fafafa",
          color: "#18181b",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          padding: "0 96px",
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 28 }}>
          <svg width="112" height="112" viewBox={MARK_VIEWBOX}>
          <path d={LEG_LEFT} fill="#18181b" />
          <path d={LEG_RIGHT} fill="#18181b" />
          <circle cx={RING.cx} cy={RING.cy} r={RING.r} fill="none" stroke="#2f7d5b" strokeWidth={RING.width} />
          <line x1={STEM.x} y1={STEM.y1} x2={STEM.x} y2={STEM.y2} stroke="#2f7d5b" strokeWidth={STEM.width} strokeLinecap="round" />
        </svg>
          <div style={{ fontSize: 88, fontWeight: 600 }}>MarkText</div>
        </div>
        <div style={{ marginTop: 48, fontSize: 44, maxWidth: 900, lineHeight: 1.2 }}>
          Watermark the text you generate. Prove it later with a statistical test.
        </div>
        <div style={{ marginTop: 28, fontSize: 26, color: "#52525b" }}>A local, open tool for lecturers and researchers.</div>
      </div>
    ),
    size,
  );
}
