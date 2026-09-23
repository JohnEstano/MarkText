/* The MarkText mark: an M whose middle stroke is a green key. The legs take
   the current text colour, the key takes the accent token, so one file works
   in light and dark. Drawn on a 32-unit grid; the ring sits above the cap
   line on purpose (the chosen concept). */
export function Mark({ size = 20, className }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      aria-hidden="true"
      focusable="false"
      className={className}
    >
      <polyline points="5.5,30 5.5,8.5 13,20" fill="none" stroke="currentColor" strokeWidth="5" strokeLinejoin="miter" strokeMiterlimit="6" />
      <polyline points="26.5,30 26.5,8.5 19,20" fill="none" stroke="currentColor" strokeWidth="5" strokeLinejoin="miter" strokeMiterlimit="6" />
      <circle cx="16" cy="5" r="3.2" fill="none" stroke="var(--accent)" strokeWidth="2.4" />
      <line x1="16" y1="8.2" x2="16" y2="30" stroke="var(--accent)" strokeWidth="3.4" />
      <rect x="17.7" y="24" width="3.3" height="2.6" fill="var(--accent)" />
    </svg>
  );
}
