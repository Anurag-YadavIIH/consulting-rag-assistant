"""
Shared types for ingestion. Each loader turns a source file into one or more
`RawSection` objects (text + provenance metadata). Provenance matters: when the
assistant answers a question, we can cite the exact file and slide/page it came
from, which is what makes the output trustworthy for an analyst.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class RawSection:
    text: str
    source_path: str
    # locator describes *where* in the file: "slide 4", "page 12", "00:03:15".
    locator: str = ""
    modality: str = "text"          # text | slides | pdf | audio | image
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Every loader passes str(path), which uses OS separators on Windows.
        # Normalize once here so source_path, chunk IDs, citations, and
        # everything downstream (PgVector keys, audit entries) are portable
        # regardless of which OS did the ingesting.
        self.source_path = Path(self.source_path).as_posix()

    def metadata(self) -> dict:
        return {
            "source_path": self.source_path,
            "locator": self.locator,
            "modality": self.modality,
            **self.extra,
        }


class Loader(Protocol):
    """A loader knows which extensions it handles and how to read them."""
    extensions: tuple[str, ...]

    def load(self, path: Path) -> list[RawSection]:
        ...
