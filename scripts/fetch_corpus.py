#!/usr/bin/env python3
"""Download a starter corpus of PUBLIC documents into data/corpus/, driven by
scripts/corpus_sources.yaml. Public sources only — nothing confidential,
nothing from real client work.

  - SEC 10-K filings: resolved dynamically (latest filing per CIK) via SEC's
    submissions JSON API, fetched as HTML, converted to plain text. Best
    effort: a filing that doesn't convert to clean text is reported as a
    failure and NOT written/ingested — see _looks_clean().
  - FDA PDFs: downloaded as-is, ingested later through the existing PdfLoader
    unmodified — real loader behavior on real PDFs, no preprocessing.
  - PubMed abstracts: NCBI E-utilities esearch + efetch, saved as plain text.

Usage:
  python scripts/fetch_corpus.py
  python scripts/fetch_corpus.py --config scripts/corpus_sources.yaml --out data/corpus
"""

from __future__ import annotations

import argparse
import html as html_module
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

import yaml

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t]+")
_BLANKLINES_RE = re.compile(r"\n{3,}")

_NOISE_MARKERS = ("xmlns:", "schemaref", "<?xml", "ix:nonnumeric", "ix:nonfraction")
# Inline-XBRL fact tags (us-gaap:/dei: taxonomy URLs, duration-code runs like
# "P3Y P8Y P5Y...") get their <ix:nonNumeric>/<ix:nonFraction> TAGS stripped
# by the generic tag stripper, but the VALUE inside often IS the taxonomy
# noise itself (a raw schema URL, an enumeration code) rather than real
# prose. These can cluster densely in one section (e.g. SEC's cover-page
# fact block) while the rest of a 500K-char filing is clean -- a whole-
# document average dilutes that cluster below any reasonable threshold, so
# this is checked in fixed-size windows instead.
_XBRL_NOISE_RE = re.compile(r"http://fasb\.org/|http://xbrl\.sec\.gov/|(?:P\d{1,2}Y\s+){2,}P\d{1,2}Y")


def html_to_text(raw_html: str) -> str:
    text = _SCRIPT_STYLE_RE.sub(" ", raw_html)
    text = _TAG_RE.sub(" ", text)
    text = html_module.unescape(text)
    text = _WS_RE.sub(" ", text)
    text = _BLANKLINES_RE.sub("\n\n", text)
    return text.strip()


def looks_clean(
    text: str,
    min_alpha_ratio: float = 0.5,
    max_tag_chars: int = 50,
    window_size: int = 800,
    max_window_noise_ratio: float = 0.15,
) -> tuple[bool, str]:
    """Hard gate before writing/ingesting a converted SEC filing. Returns
    (is_clean, reason). A filing that fails this is skipped entirely, not
    ingested — bad conversion quality must not poison the index."""
    if not text or not text.strip():
        return False, "empty after conversion"
    tag_chars = text.count("<") + text.count(">")
    if tag_chars > max_tag_chars:
        return False, f"{tag_chars} stray angle-bracket characters remain after stripping"

    alpha = sum(1 for c in text if c.isalpha())
    ratio = alpha / len(text)
    if ratio < min_alpha_ratio:
        return False, f"alpha-character ratio too low ({ratio:.2f} < {min_alpha_ratio})"

    lowered = text.lower()
    noise_hits = sum(lowered.count(m) for m in _NOISE_MARKERS)
    if noise_hits > 20:
        return False, f"{noise_hits} XBRL/XML noise markers remain — conversion likely failed"

    # Windowed check: catches a concentrated junk block even when it's a
    # small fraction of a long, otherwise-clean document.
    for start in range(0, len(text), window_size):
        window = text[start : start + window_size]
        noise_chars = sum(len(m.group(0)) for m in _XBRL_NOISE_RE.finditer(window))
        if noise_chars / max(len(window), 1) > max_window_noise_ratio:
            return False, (
                f"concentrated XBRL/taxonomy noise near offset {start} "
                f"({noise_chars}/{len(window)} chars in that window) — conversion left "
                f"un-stripped inline-XBRL fact values"
            )
    return True, "ok"


def fetch_sec_filing(entry: dict, out_dir: Path, user_agent: str) -> tuple[bool, str]:
    cik_raw = entry["cik"]
    cik_int = cik_raw.lstrip("0") or "0"
    cik10 = cik_raw.zfill(10)
    form_wanted = entry.get("form", "10-K")

    req = Request(f"https://data.sec.gov/submissions/CIK{cik10}.json", headers={"User-Agent": user_agent})
    with urlopen(req, timeout=20) as resp:
        data = json.load(resp)

    recent = data["filings"]["recent"]
    idx = next((i for i, f in enumerate(recent["form"]) if f == form_wanted), None)
    if idx is None:
        return False, f"{entry['company']}: no {form_wanted} filing found for CIK {cik_raw}"

    accession = recent["accessionNumber"][idx].replace("-", "")
    primary_doc = recent["primaryDocument"][idx]
    filing_date = recent["filingDate"][idx]
    doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession}/{primary_doc}"

    req2 = Request(doc_url, headers={"User-Agent": user_agent})
    with urlopen(req2, timeout=30) as resp2:
        raw = resp2.read().decode("utf-8", errors="ignore")

    text = html_to_text(raw)
    ok, reason = looks_clean(text)
    if not ok:
        return False, (
            f"{entry['company']} {form_wanted} ({filing_date}): conversion failed — "
            f"{reason} — skipped, NOT ingested"
        )

    safe_name = f"sec_{entry['company'].lower().replace(' ', '_')}_{form_wanted.replace('-', '')}_{filing_date}.txt"
    (out_dir / safe_name).write_text(text, encoding="utf-8")
    return True, f"{entry['company']} {form_wanted} ({filing_date}) -> {safe_name} ({len(text):,} chars)"


def fetch_fda_pdf(entry: dict, out_dir: Path, user_agent: str) -> tuple[bool, str]:
    out_path = out_dir / entry["filename"]
    if out_path.exists():
        return True, f"{entry['name']} -> {entry['filename']} (already downloaded)"
    req = Request(entry["url"], headers={"User-Agent": user_agent})
    with urlopen(req, timeout=30) as resp:
        data = resp.read()
    out_path.write_bytes(data)
    return True, f"{entry['name']} -> {entry['filename']} ({len(data):,} bytes)"


def fetch_pubmed(entry: dict, out_dir: Path, user_agent: str) -> list[tuple[bool, str]]:
    results: list[tuple[bool, str]] = []
    query = entry["query"]
    max_results = entry.get("max_results", 5)

    search_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        f"?db=pubmed&term={quote(query)}&retmax={max_results}&retmode=json"
    )
    req = Request(search_url, headers={"User-Agent": user_agent})
    with urlopen(req, timeout=20) as resp:
        search_data = json.load(resp)
    pmids = search_data.get("esearchresult", {}).get("idlist", [])
    if not pmids:
        return [(False, f"PubMed query '{query}': no results")]

    for pmid in pmids:
        out_path = out_dir / f"pubmed_{pmid}.txt"
        if out_path.exists():
            results.append((True, f"PMID {pmid} (already downloaded)"))
            continue
        fetch_url = (
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
            f"?db=pubmed&id={pmid}&rettype=abstract&retmode=text"
        )
        req2 = Request(fetch_url, headers={"User-Agent": user_agent})
        with urlopen(req2, timeout=20) as resp2:
            text = resp2.read().decode("utf-8", errors="ignore")
        if not text.strip():
            results.append((False, f"PMID {pmid}: empty abstract returned"))
            continue
        out_path.write_text(text, encoding="utf-8")
        results.append((True, f"PMID {pmid} -> pubmed_{pmid}.txt ({len(text)} chars)"))
        time.sleep(0.34)  # stay under NCBI's ~3 req/sec unauthenticated rate limit
    return results


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(Path(__file__).resolve().parent / "corpus_sources.yaml"))
    ap.add_argument(
        "--out", default=str(Path(__file__).resolve().parents[1] / "data" / "corpus")
    )
    ap.add_argument("--user-agent", default="ConsultRAG-research contact@example.com")
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    out_root = Path(args.out)
    sec_dir, fda_dir, pubmed_dir = out_root / "sec", out_root / "fda", out_root / "pubmed"
    for d in (sec_dir, fda_dir, pubmed_dir):
        d.mkdir(parents=True, exist_ok=True)

    failures = 0

    print("=== SEC filings ===")
    for entry in config.get("sec_filings", []):
        try:
            ok, msg = fetch_sec_filing(entry, sec_dir, args.user_agent)
        except Exception as e:
            ok, msg = False, f"{entry.get('company', '?')}: ERROR {e}"
        print(("  OK   " if ok else "  FAIL ") + msg)
        failures += not ok

    print("\n=== FDA PDFs ===")
    for entry in config.get("fda_pdfs", []):
        try:
            ok, msg = fetch_fda_pdf(entry, fda_dir, args.user_agent)
        except Exception as e:
            ok, msg = False, f"{entry.get('name', '?')}: ERROR {e}"
        print(("  OK   " if ok else "  FAIL ") + msg)
        failures += not ok

    print("\n=== PubMed abstracts ===")
    for entry in config.get("pubmed", []):
        try:
            for ok, msg in fetch_pubmed(entry, pubmed_dir, args.user_agent):
                print(("  OK   " if ok else "  FAIL ") + msg)
                failures += not ok
        except Exception as e:
            print(f"  FAIL {entry.get('query', '?')}: ERROR {e}")
            failures += 1

    print(f"\n{failures} failure(s) total.")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
