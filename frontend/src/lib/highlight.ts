import type { CSSProperties } from "react";

/** Parses the X-Highlight header "x,y,w,h" (fractions of the crop) into absolute-position percentages. */
export function parseHighlight(header: string | null): Pick<CSSProperties, "left" | "top" | "width" | "height"> | null {
  const n = header?.split(",").map(Number);
  if (!n || n.length !== 4 || n.some(Number.isNaN)) return null;
  const [x, y, w, h] = n.map((v) => `${+(v * 100).toFixed(3)}%`);
  return { left: x, top: y, width: w, height: h };
}
