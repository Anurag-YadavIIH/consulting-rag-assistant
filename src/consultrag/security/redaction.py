"""
PII / PHI redaction.

Runs BEFORE any text is embedded or indexed, so confidential client and
patient identifiers never leave the source documents in plaintext form inside
the vector store. This is the core of the confidentiality guarantee: the index
contains redacted text only.

The default detectors are dependency-free (regex + checksum validation). For
production you can swap in Microsoft Presidio (a named-entity PII engine) behind
the same `Redactor` interface — see `redact_with_presidio` for the hook.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Pattern


@dataclass(frozen=True)
class RedactionRule:
    """A single detector: a name, a compiled pattern, and an optional validator."""
    label: str
    pattern: Pattern[str]
    validator: Callable[[str], bool] | None = None

    def placeholder(self) -> str:
        return f"[REDACTED_{self.label}]"


def _luhn_valid(number: str) -> bool:
    """Luhn checksum — avoids redacting random 16-digit strings that aren't cards."""
    digits = [int(d) for d in re.sub(r"\D", "", number)]
    if len(digits) < 13:
        return False
    checksum = 0
    parity = len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


# Order matters: more specific patterns first so they win.
DEFAULT_RULES: list[RedactionRule] = [
    RedactionRule(
        "EMAIL",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    ),
    RedactionRule(
        "SSN",
        re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b"),
    ),
    RedactionRule(
        "CREDIT_CARD",
        re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
        validator=_luhn_valid,
    ),
    RedactionRule(
        # US-style and international phone numbers, fairly permissive.
        "PHONE",
        re.compile(r"\b(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?){2,4}\d{2,4}\b"),
        validator=lambda s: len(re.sub(r"\D", "", s)) >= 8,
    ),
    RedactionRule(
        # US Medical Record Number style tags often seen in healthcare docs.
        "MRN",
        re.compile(r"\bMRN[:#]?\s?\d{5,10}\b", re.IGNORECASE),
    ),
    RedactionRule(
        "NPI",  # National Provider Identifier (US healthcare), 10 digits.
        re.compile(r"\bNPI[:#]?\s?\d{10}\b", re.IGNORECASE),
    ),
    RedactionRule(
        "IP_ADDRESS",
        re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    ),
]


@dataclass
class RedactionReport:
    """What was removed — written to the audit log, never the index."""
    counts: dict[str, int] = field(default_factory=dict)

    def add(self, label: str) -> None:
        self.counts[label] = self.counts.get(label, 0) + 1

    @property
    def total(self) -> int:
        return sum(self.counts.values())


class Redactor:
    """Applies a set of rules to text, returning redacted text + a report."""

    def __init__(self, rules: list[RedactionRule] | None = None,
                 extra_terms: list[str] | None = None):
        self.rules = list(rules) if rules is not None else list(DEFAULT_RULES)
        # extra_terms = client names, project codenames, etc. you want masked.
        if extra_terms:
            for term in extra_terms:
                self.rules.append(
                    RedactionRule(
                        "CUSTOM",
                        re.compile(re.escape(term), re.IGNORECASE),
                    )
                )

    def redact(self, text: str) -> tuple[str, RedactionReport]:
        report = RedactionReport()

        def _sub(rule: RedactionRule):
            def replace(match: re.Match[str]) -> str:
                value = match.group(0)
                if rule.validator and not rule.validator(value):
                    return value  # leave it — failed validation, probably a false positive
                report.add(rule.label)
                return rule.placeholder()
            return replace

        for rule in self.rules:
            text = rule.pattern.sub(_sub(rule), text)
        return text, report


def redact_with_presidio(text: str):  # pragma: no cover - optional dependency
    """
    Production hook. Requires `pip install presidio-analyzer presidio-anonymizer`.
    Presidio adds ML-based NER for names, locations, and org entities that regex
    can't catch. Kept optional so the core system has zero heavy dependencies.
    """
    from presidio_analyzer import AnalyzerEngine
    from presidio_anonymizer import AnonymizerEngine

    analyzer = AnalyzerEngine()
    anonymizer = AnonymizerEngine()
    results = analyzer.analyze(text=text, language="en")
    anonymized = anonymizer.anonymize(text=text, analyzer_results=results)
    return anonymized.text
