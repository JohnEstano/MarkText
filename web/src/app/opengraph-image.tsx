import { ImageResponse } from "next/og";

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
          <svg width="112" height="112" viewBox="0 0 32 32">
            <polyline points="5.5,30 5.5,8.5 13,20" fill="none" stroke="#18181b" strokeWidth="5" strokeLinejoin="miter" strokeMiterlimit="6" />
            <polyline points="26.5,30 26.5,8.5 19,20" fill="none" stroke="#18181b" strokeWidth="5" strokeLinejoin="miter" strokeMiterlimit="6" />
            <circle cx="16" cy="5" r="3.2" fill="none" stroke="#2f7d5b" strokeWidth="2.4" />
            <line x1="16" y1="8.2" x2="16" y2="30" stroke="#2f7d5b" strokeWidth="3.4" />
            <rect x="17.7" y="24" width="3.3" height="2.6" fill="#2f7d5b" />
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
