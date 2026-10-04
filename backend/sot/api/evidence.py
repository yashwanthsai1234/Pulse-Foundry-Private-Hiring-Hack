"""GET /api/evidence/crop: PNG clip of a PDF cell with the highlight rectangle in X-Highlight.

Sources:
- https://pymupdf.readthedocs.io/en/latest/page.html#Page.get_pixmap (clip, dpi)
- https://pymupdf.readthedocs.io/en/latest/rect.html (Rect.intersect, normalize)
"""
from __future__ import annotations

import math

import pymupdf
from fastapi import APIRouter, HTTPException, Request, Response

from sot.store import repo

router = APIRouter()
DPI = 144


@router.get("/evidence/crop")
def crop(request: Request, file_id: str, page: int, x0: float, top: float, x1: float, bottom: float,
         pad: float = 40) -> Response:
    try:
        path = repo.load_file(request.app.state.db, file_id).path
    except IndexError as err:
        raise HTTPException(404, "unknown file") from err
    if not all(math.isfinite(v) for v in (x0, top, x1, bottom, pad)):
        raise HTTPException(400, "bbox must be finite numbers")
    try:
        doc = pymupdf.open(path)
    except pymupdf.FileDataError as err:
        raise HTTPException(415, "only PDF files have a page to crop") from err
    with doc:
        if not 1 <= page <= len(doc):
            raise HTTPException(404, "no such page")
        pg = doc[page - 1]
        box = pymupdf.Rect(x0, top, x1, bottom).normalize()
        clip = pymupdf.Rect(box.x0 - pad, box.y0 - pad, box.x1 + pad, box.y1 + pad).intersect(pg.rect)
        box = box.intersect(clip)  # the highlight stays inside the picture, so its fractions are within 0..1
        if clip.is_empty or box.is_empty:
            raise HTTPException(400, "bbox is outside the page")
        png = pg.get_pixmap(clip=clip, dpi=DPI).tobytes("png")
    hx = ((box.x0 - clip.x0) / clip.width, (box.y0 - clip.y0) / clip.height,
          box.width / clip.width, box.height / clip.height)
    return Response(png, media_type="image/png", headers={"X-Highlight": ",".join(f"{v:.4f}" for v in hx),
                                                             "Access-Control-Expose-Headers": "X-Highlight"})
