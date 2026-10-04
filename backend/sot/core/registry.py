"""Parser registry for the auction (IMPLEMENTATION §7). Parsers register with @register_parser.

Sources:
- https://docs.python.org/3/library/typing.html#typing.Protocol (a parser is any object with sniff and extract)
- https://docs.python.org/3/library/typing.html#typing.TYPE_CHECKING (type-only imports avoid a cycle with models)
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Protocol

if TYPE_CHECKING:
    from sot.config import Settings
    from sot.core.models import AgentTask, FileRef, RawTable, SniffResult
    from sot.core.pack import Pack


@dataclass
class ExtractContext:
    """What a parser may use while extracting."""

    settings: Settings
    pack: Pack
    run_id: str
    sniff_details: dict
    submit_task: Callable[[AgentTask], None] | None = None  # scan parser -> page_reader tasks


class Parser(Protocol):
    name: ClassVar[str]

    def sniff(self, head: bytes, path: Path) -> SniffResult: ...

    def extract(self, file: FileRef, ctx: ExtractContext) -> list[RawTable]: ...


_PARSERS: list[Parser] = []


def register_parser(cls: type) -> type:
    _PARSERS.append(cls())
    return cls


def all_parsers() -> list[Parser]:
    import sot.parsers  # noqa: F401  (imports every parser module so they register)

    return list(_PARSERS)
