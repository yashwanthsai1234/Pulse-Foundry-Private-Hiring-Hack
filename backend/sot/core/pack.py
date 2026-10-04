"""Domain pack loader (IMPLEMENTATION §6). The engine knows no domain; it reads this.

Sources:
- https://pyyaml.org/wiki/PyYAMLDocumentation (safe_load of pack.yaml, templates, fields)
- https://docs.python.org/3/library/csv.html (vocab CSVs)
- https://docs.python.org/3/library/functools.html#functools.lru_cache (a pack is loaded once)
- https://docs.pydantic.dev/latest/concepts/models/
"""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class FieldSpec(BaseModel):
    id: str
    type: str
    synonyms: list[str] = Field(default_factory=list)
    validator: dict[str, Any] = Field(default_factory=dict)
    vocab: str | None = None
    repeatable: bool = False
    header_pattern: str | None = None


class TemplateSpec(BaseModel):
    id: str
    entity: str
    required: list[str]
    optional: list[str] = Field(default_factory=list)
    one_of: list[list[str]] = Field(default_factory=list)  # alternatives: one more requirement, met by any one of these field lists
    anchor: bool = False
    holder: str | None = None
    relations: list[dict[str, list[str]]] = Field(default_factory=list)  # [{"gte": [a, b]}]
    context: dict[str, Any] = Field(default_factory=dict)

    @property
    def fields(self) -> list[str]:
        return self.required + self.optional + [f for alt in self.one_of for f in alt if f not in self.optional]


class Vocab(BaseModel):
    name: str
    codes: dict[str, list[str]]  # code -> aliases (normalized lower-case)
    names: dict[str, str] = Field(default_factory=dict)  # code -> display name
    scope: dict[str, list[str]] = Field(default_factory=dict)  # role -> license types allowed


class Pack(BaseModel):
    name: str
    dir: Path
    fields: dict[str, FieldSpec]
    templates: dict[str, TemplateSpec]
    vocabs: dict[str, Vocab]
    nicknames: dict[str, str]  # nickname -> canonical given name
    survivorship: dict[str, Any]
    resolution: dict[str, Any]
    pbj: dict[str, Any]

    @property
    def checks_dir(self) -> Path:
        return self.dir / "checks"


def _yaml(path: Path) -> dict[str, Any]:
    return (yaml.safe_load(path.read_text()) or {}) if path.exists() else {}


@lru_cache(maxsize=4)
def load_pack(pack_dir: Path) -> Pack:
    fields = {fid: FieldSpec(id=fid, **spec) for fid, spec in _yaml(pack_dir / "fields.yaml")["fields"].items()}
    templates = {tid: TemplateSpec(id=tid, **spec) for tid, spec in _yaml(pack_dir / "templates.yaml")["templates"].items()}
    vocabs = {}
    for f in sorted((pack_dir / "vocab").glob("*.yaml")):
        raw = _yaml(f)
        codes = {code: sorted({a.lower() for a in aliases} | {code.lower()}) for code, aliases in raw["codes"].items()}
        vocabs[f.stem] = Vocab(name=f.stem, codes=codes, names=raw.get("names", {}), scope=raw.get("scope", {}))
    nick_file = pack_dir / "vocab" / "nicknames.csv"
    nicknames = {}
    if nick_file.exists():
        with nick_file.open() as fh:
            nicknames = {r["nickname"].lower(): r["canonical"].lower() for r in csv.DictReader(fh)}
    return Pack(
        name=pack_dir.name,
        dir=pack_dir,
        fields=fields,
        templates=templates,
        vocabs=vocabs,
        nicknames=nicknames,
        survivorship=_yaml(pack_dir / "survivorship.yaml"),
        resolution=_yaml(pack_dir / "resolution.yaml"),
        pbj=_yaml(pack_dir / "exports" / "pbj.yaml"),
    )
