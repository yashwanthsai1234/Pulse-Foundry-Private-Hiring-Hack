"""Parser auction (IMPLEMENTATION §7): every parser bids on the first 64 KB; best bid >= min_score wins.

Sources:
- https://duckdb.org/2023/10/27/csv-sniffer.html (try every candidate, keep the best-scoring one)
"""
from __future__ import annotations

from pathlib import Path

from sot.core.models import AuctionResult, FileRef, SniffResult
from sot.core.registry import Parser

HEAD_BYTES = 64 * 1024


def _bid(parser: Parser, head: bytes, path: Path) -> SniffResult:
    try:
        return parser.sniff(head, path)
    except Exception as e:  # a broken file must not stop the other bidders
        return SniffResult(parser=parser.name, score=0.0, reason=f"sniff failed: {e}")


def run_auction(file: FileRef, parsers: list[Parser], min_score: float) -> AuctionResult:
    path = Path(file.path)
    with path.open("rb") as f:
        head = f.read(HEAD_BYTES)
    bids = sorted((_bid(p, head, path) for p in parsers), key=lambda b: -b.score)  # stable: ties keep registry order
    winner = bids[0] if bids and bids[0].score >= min_score else None
    return AuctionResult(file=file, bids=bids, winner=winner)
