import { ImageResponse } from "next/og";

export const size = { width: 180, height: 180 };
export const contentType = "image/png";

/* Apple touch icon: the mark on a solid light tile (iOS adds its own
   rounding, so the tile has square corners). */
export default function AppleIcon() {
  return new ImageResponse(
    (
      <div style={{ width: 180, height: 180, background: "#fafafa", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <svg width="132" height="132" viewBox="0 0 32 32">
          <polyline points="5.5,30 5.5,8.5 13,20" fill="none" stroke="#18181b" strokeWidth="5" strokeLinejoin="miter" strokeMiterlimit="6" />
          <polyline points="26.5,30 26.5,8.5 19,20" fill="none" stroke="#18181b" strokeWidth="5" strokeLinejoin="miter" strokeMiterlimit="6" />
          <circle cx="16" cy="5" r="3.2" fill="none" stroke="#2f7d5b" strokeWidth="2.4" />
          <line x1="16" y1="8.2" x2="16" y2="30" stroke="#2f7d5b" strokeWidth="3.4" />
          <rect x="17.7" y="24" width="3.3" height="2.6" fill="#2f7d5b" />
        </svg>
      </div>
    ),
    size,
  );
}
