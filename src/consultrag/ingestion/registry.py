"""Dispatches a file to the right loader by extension."""

from __future__ import annotations

from pathlib import Path

from .base import RawSection
from .loaders import AudioLoader, PdfLoader, PptxLoader, TextLoader


class LoaderRegistry:
    def __init__(self):
        self._by_ext: dict[str, object] = {}
        for loader in (TextLoader(), PptxLoader(), PdfLoader(), AudioLoader()):
            for ext in loader.extensions:
                self._by_ext[ext] = loader

    def supported_extensions(self) -> list[str]:
        return sorted(self._by_ext)

    def load(self, path: Path) -> list[RawSection]:
        loader = self._by_ext.get(path.suffix.lower())
        if loader is None:
            raise ValueError(
                f"No loader for '{path.suffix}'. "
                f"Supported: {', '.join(self.supported_extensions())}"
            )
        return loader.load(path)

    def load_directory(self, root: Path) -> list[RawSection]:
        sections: list[RawSection] = []
        for p in sorted(root.rglob("*")):
            if p.is_file() and p.suffix.lower() in self._by_ext:
                sections.extend(self.load(p))
        return sections
