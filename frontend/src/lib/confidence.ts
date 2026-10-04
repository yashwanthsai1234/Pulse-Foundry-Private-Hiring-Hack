/** Confidence colour: green >= 0.85, amber >= 0.6, red below. */
export const confidenceColor = (v: number) =>
  v >= 0.85 ? "bg-green-100 text-green-800" : v >= 0.6 ? "bg-amber-100 text-amber-800" : "bg-red-100 text-red-800";
