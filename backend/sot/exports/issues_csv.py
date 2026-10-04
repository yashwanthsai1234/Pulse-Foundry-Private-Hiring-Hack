"""Issues CSV: all active issues, flattened, evidence as a text summary (IMPLEMENTATION §14).

Sources:
- https://docs.python.org/3/library/csv.html  (csv writer quoting)
"""
from __future__ import annotations

import csv
import io

from sot.core.models import SEVERITY_ORDER
from sot.store import repo
from sot.store.db import DB

COLUMNS = ["fingerprint", "check_id", "severity", "status", "owner", "title", "message", "entities", "facility_id",
           "period_start", "period_end", "action", "evidence", "note"]


def issues_csv(db: DB) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, COLUMNS)
    writer.writeheader()
    for i in sorted(repo.load_issues(db), key=lambda i: (SEVERITY_ORDER[i.severity], i.check_id, i.fingerprint)):
        writer.writerow({
            **i.model_dump(include=set(COLUMNS)), "entities": "; ".join(i.entity_ids),
            "evidence": " | ".join(f"{e.label}: {e.text}" for e in i.evidence)})
    return buf.getvalue()
