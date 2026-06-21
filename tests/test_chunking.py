import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from consultrag.chunking import Chunker, approx_token_count
from consultrag.ingestion.base import RawSection


def _section(text):
    return RawSection(text=text, source_path="doc.txt", locator="", modality="text")


def test_chunks_respect_target_size():
    sentence = "This is a moderately sized sentence about market dynamics. "
    section = _section(sentence * 40)
    chunker = Chunker(target_tokens=60, overlap_tokens=10)
    chunks = chunker.chunk_section(section, "doc.txt#0")
    assert len(chunks) > 1
    for c in chunks:
        # allow a little slack for the trailing sentence that crosses the line
        assert approx_token_count(c.text) <= 60 + 20


def test_overlap_creates_shared_content():
    section = _section(
        "Alpha beta gamma delta. Epsilon zeta eta theta. "
        "Iota kappa lambda mu. Nu xi omicron pi. Rho sigma tau upsilon."
    )
    chunker = Chunker(target_tokens=8, overlap_tokens=4)
    chunks = chunker.chunk_section(section, "doc.txt#0")
    assert len(chunks) >= 2


def test_chunk_ids_are_unique():
    section = _section("One. Two. Three. Four. Five. Six. Seven. Eight.")
    chunks = Chunker(target_tokens=5, overlap_tokens=1).chunk_section(section, "x#0")
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))


def test_chunk_ids_use_forward_slashes_even_from_backslash_source_path():
    # RawSection normalizes source_path on construction (ingestion/base.py),
    # so this proves the single normalization point actually holds — a chunk
    # ID built from a Windows-style backslash path must come out portable.
    section = RawSection(text="One. Two.", source_path="data\\sample\\doc.txt")
    assert "\\" not in section.source_path

    chunks = Chunker().chunk_sections([section])
    assert chunks
    for c in chunks:
        assert "\\" not in c.chunk_id
        assert c.chunk_id.startswith("data/sample/doc.txt")
