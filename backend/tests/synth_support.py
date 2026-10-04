"""Test-only helpers for the synthetic world (kept out of tools/synth: production code does not use them)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from tools.synth.generator import FACILITIES, TOKENS, World


def interval(shift) -> tuple[datetime, datetime]:
    hour, hours = TOKENS[shift.token]
    begin = datetime.combine(shift.work_date, datetime.min.time()) + timedelta(hours=hour)
    return begin, begin + timedelta(hours=hours)


def rn_gaps(world: World) -> list[tuple[str, date]]:
    """Facility x day pairs where the union of RN shifts overlapping the day has no 8 h consecutive span."""
    gaps = []
    for fac in FACILITIES:
        for day in world.days():
            lo = datetime.combine(day, datetime.min.time())
            hi = lo + timedelta(days=1)
            spans = sorted(i for i in (interval(s) for s in world.shifts if s.role == "RN" and s.facility == fac)
                           if i[0] < hi and i[1] > lo)
            best, run_start, run_end = timedelta(0), None, None
            for b, e in spans:
                if run_end is None or b > run_end:
                    run_start, run_end = b, e
                run_end = max(run_end, e)
                best = max(best, run_end - run_start)
            if best < timedelta(hours=8):
                gaps.append((fac, day))
    return gaps
