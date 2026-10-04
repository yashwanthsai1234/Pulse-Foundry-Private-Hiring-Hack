"""Runtime settings: environment variables over pack settings.yaml over defaults (IMPLEMENTATION §4).

Sources:
- https://docs.python.org/3/library/os.html#os.environ (SOT_* environment variables)
- https://pyyaml.org/wiki/PyYAMLDocumentation (safe_load of settings.yaml)
- https://docs.python.org/3/library/dataclasses.html
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent

DEFAULTS: dict[str, float] = {
    "sniff.min_score": 0.50,
    "pdf.method_min_score": 0.80,
    "map.auto_min": 0.80,
    "map.agent_min": 0.50,
    "map.no_field_score": 0.35,
    "link.auto": 0.95,
    "link.gray": 0.75,
    "link.prior": -5.0,
    "hours.tolerance_abs": 2.0,
    "hours.tolerance_rel": 0.05,
    "expiry.high_days": 30,
    "expiry.medium_days": 60,
    "agent.cli.concurrency": 4,
    "agent.cli.timeout_s": 90,
}


@dataclass
class Settings:
    pack_name: str
    pack_dir: Path
    runtime: Path
    agents: str  # queue | cli | off
    as_of: date
    values: dict[str, float] = field(default_factory=dict)

    def __getitem__(self, key: str) -> float:
        return self.values[key]

    @property
    def db_path(self) -> Path:
        return self.runtime / "sot.duckdb"

    def dir(self, name: str) -> Path:
        """runtime sub-folder (landing, bronze, contracts, agent_tasks/pending, ...), created on demand."""
        p = self.runtime / name
        p.mkdir(parents=True, exist_ok=True)
        return p


def load_settings(runtime: Path | None = None, pack: str | None = None) -> Settings:
    pack_name = pack or os.environ.get("SOT_PACK", "healthcare_snf")
    pack_dir = BACKEND_DIR / "packs" / pack_name
    values = dict(DEFAULTS)
    overrides = pack_dir / "settings.yaml"
    if overrides.exists():
        values.update(yaml.safe_load(overrides.read_text()) or {})
    as_of = os.environ.get("SOT_AS_OF")
    rt = runtime or Path(os.environ.get("SOT_RUNTIME", REPO_DIR / "runtime"))
    rt.mkdir(parents=True, exist_ok=True)
    return Settings(
        pack_name=pack_name,
        pack_dir=pack_dir,
        runtime=rt,
        agents=os.environ.get("SOT_AGENTS", "queue"),
        as_of=date.fromisoformat(as_of) if as_of else date.today(),
        values=values,
    )
