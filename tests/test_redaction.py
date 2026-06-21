import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from consultrag.security.redaction import Redactor


def test_redacts_email_and_phone():
    r = Redactor()
    text = "Contact jane.doe@acme.com or call +1 415-555-0132 about the deal."
    out, report = r.redact(text)
    assert "jane.doe@acme.com" not in out
    assert "[REDACTED_EMAIL]" in out
    assert report.counts.get("EMAIL") == 1
    assert report.counts.get("PHONE", 0) >= 1


def test_credit_card_luhn_validation():
    r = Redactor()
    # 4111111111111111 is a valid Luhn test number; the other is not.
    out, report = r.redact("card 4111 1111 1111 1111 vs 1234 5678 9012 3456")
    assert "[REDACTED_CREDIT_CARD]" in out
    assert report.counts.get("CREDIT_CARD") == 1


def test_custom_terms_masked():
    r = Redactor(extra_terms=["Project Helios", "Acme Corp"])
    out, _ = r.redact("Project Helios is Acme Corp's secret initiative.")
    assert "Project Helios" not in out
    assert "Acme Corp" not in out


def test_redacted_values_not_leaked_in_report():
    r = Redactor()
    _, report = r.redact("ssn 123-45-6789")
    # report holds counts only, never the value
    assert "123-45-6789" not in str(report.counts)
    assert report.counts.get("SSN") == 1
