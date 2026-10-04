// Renders the backend's PNG crop of a PDF cell and overlays the X-Highlight rectangle.
// Sources: https://developer.mozilla.org/en-US/docs/Web/CSS/position (absolute overlay inside a relative box)
import { useEffect, useState } from "react";
import { fetchCrop } from "../api/client";
import type { Locator } from "../api/types";
import { parseHighlight } from "../lib/highlight";

export function PdfCrop({ loc }: { loc: Locator }) {
  const [crop, setCrop] = useState<{ url: string; highlight: string | null } | null>(null);
  const [failed, setFailed] = useState(false);
  const [x0, top, x1, bottom] = loc.bbox!;

  useEffect(() => {
    fetchCrop({ file_id: loc.file_id, page: loc.page!, x0, top, x1, bottom }).then(setCrop, () => setFailed(true));
  }, [loc.file_id, loc.page, x0, top, x1, bottom]);

  if (failed) return <p className="text-sm text-red-600">Crop unavailable.</p>;
  if (!crop) return <p className="text-sm text-slate-400">Loading crop...</p>;
  const rect = parseHighlight(crop.highlight);
  return (
    <div className="relative inline-block border border-slate-300" data-testid="pdf-crop">
      <img src={crop.url} alt={`${loc.file_name} page ${loc.page}`} className="block max-w-full" />
      {rect && <div data-testid="highlight" className="absolute border-2 border-red-500 bg-red-500/15" style={rect} />}
    </div>
  );
}
