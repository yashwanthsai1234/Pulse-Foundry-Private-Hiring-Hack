"""Column profiles: type, null ratio, distinct count, sample and validator hit rates (§9.2).

Sources:
- https://docs.pola.rs/api/python/stable/reference/dataframe/api/polars.DataFrame.sample.html (seeded sampling)
- https://arxiv.org/abs/1905.10688 (Sherlock: per-column statistical + value features)
"""
from __future__ import annotations

import re

from sot.core.models import ColumnProfile, InferredType, RawTable
from sot.normalize.dates import EXCEL, infer_column_date_format
from sot.semantic.validators import Validator

_INT = re.compile(r"[+-]?\d+")
_NUM = re.compile(r"[+-]?\d*\.\d+|[+-]?\d+\.?")
MIN_VALUES = 2  # a hit rate over fewer non-null values is shrunk (one lucky cell is not evidence), unless the table is that short
_BOOL = {"true", "false", "yes", "no", "y", "n"}


def _infer_type(values: list[str]) -> InferredType:
    if not values:
        return "empty"
    if all(_INT.fullmatch(v) for v in values):
        return "integer"
    if all(_NUM.fullmatch(v.replace(",", "")) for v in values):
        return "number"
    if all(v.lower() in _BOOL for v in values):
        return "bool"
    fmt, _ = infer_column_date_format(values)
    return "date" if fmt not in (None, EXCEL) else "string"


def profile_table(t: RawTable, validators: dict[str, Validator], sample_rows: int = 2000) -> list[ColumnProfile]:
    df = t.df.sample(sample_rows, seed=0) if t.df.height > sample_rows else t.df
    profiles = []
    for i, col in enumerate(t.header):
        values = [v.strip() for v in df[col].to_list() if v is not None and v.strip()]
        profiles.append(ColumnProfile(
            column=col, index=i, n=t.df.height,
            null_ratio=1 - len(values) / df.height if df.height else 1.0,
            distinct=len(set(values)), inferred_type=_infer_type(values),
            sample=list(dict.fromkeys(values))[:20],
            validator_hits={f: sum(map(check, values)) / max(len(values), min(MIN_VALUES, df.height)) for f, check in validators.items()} if values else {},
        ))
    return profiles
