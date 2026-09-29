/* Geometry of the MarkText mark, measured from the chosen concept sheet
   (ChatGPT "05 Keyed Trace") on a 200 px crop: legs 24 wide with 45-degree
   inner diagonals that end in a vertical notch, a thick ring, a rounded
   stem, no key bit. Shared by the React mark, the apple icon and the
   social image; icon.svg carries a static copy. */
export const MARK_VIEWBOX = "12 2 180 180";
export const LEG_LEFT =
  "M32 52H43A4 4 0 0 1 47 56V58L81 92V125L47 91V168A8 8 0 0 1 39 176H32A8 8 0 0 1 24 168V60A8 8 0 0 1 32 52Z";
export const LEG_RIGHT =
  "M172 52H161A4 4 0 0 0 157 56V58L123 92V125L157 91V168A8 8 0 0 0 165 176H172A8 8 0 0 0 180 168V60A8 8 0 0 0 172 52Z";
export const RING = { cx: 102, cy: 34, r: 18.75, width: 13.5 };
export const STEM = { x: 102, y1: 50, y2: 168.5, width: 15 };
