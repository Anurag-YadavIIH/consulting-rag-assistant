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


# --- regressions for the false positives found on the real FDA/PubMed corpus ---
# Each string below is the literal text that was getting corrupted, copied
# from the actual ingested documents (see BENCHMARKS.md / session report),
# not constructed from memory.


def test_doi_survives_intact_not_matched_as_phone():
    r = Redactor()
    text = "doi: 10.1016/j.jvs.2026.04.044."
    out, report = r.redact(text)
    assert "10.1016/j.jvs.2026.04.044" in out
    assert "PHONE" not in report.counts


def test_four_segment_section_number_is_redacted_as_accepted_tradeoff():
    # "10.1.4.1" is exactly 4 dot-separated segments — syntactically
    # identical to a real IPv4 address. Position/keyword-based exemptions
    # (preceded by a heading, start of a line) were tried and removed after
    # stress-testing showed they suppress real IPs in those same ordinary
    # positions (see the session report). This IS now over-redacted —
    # accepted on purpose: under-redaction is the failure mode this module
    # exists to prevent, cosmetic over-redaction of a section number is not.
    r = Redactor()
    text = "Study Endpoints \n10.1.4.1. Primary Effectiveness Endpoint"
    out, report = r.redact(text)
    assert "[REDACTED_IP_ADDRESS]" in out
    assert report.counts.get("IP_ADDRESS") == 1


def test_table_reference_four_segments_is_also_redacted_as_accepted_tradeoff():
    r = Redactor()
    text = "the primary analysis of Table 10.3.4.1 which excluded subjects"
    out, report = r.redact(text)
    assert "[REDACTED_IP_ADDRESS]" in out
    assert report.counts.get("IP_ADDRESS") == 1


def test_five_segment_outline_number_is_not_redacted():
    # The one safe, structural exemption: a TRUE outline number with a 5th
    # attached segment (e.g. "10.3.5.2.1") cannot be a real IPv4 address —
    # zero leak risk, unlike the removed position/keyword exemptions.
    r = Redactor()
    text = "presented in Table 10.3.5.2.1. TETRAS scores improved over time."
    out, report = r.redact(text)
    assert "10.3.5.2.1" in out
    assert "IP_ADDRESS" not in report.counts


def test_genuine_phone_in_fda_correspondence_is_still_redacted():
    # Real text from data/corpus/fda/fda_510k_medivis_K231897.pdf.
    r = Redactor()
    text = "by email (DICE@fda.hhs.gov) or phone (1-800-638-2041 or 301-796-7100)."
    out, report = r.redact(text)
    assert "1-800-638-2041" not in out
    assert "301-796-7100" not in out
    assert report.counts.get("PHONE", 0) >= 2


def test_genuine_ip_address_in_prose_is_still_redacted():
    # No real network IP appeared in the fetched corpus (only section/table
    # references did) — a clean synthetic example, same convention already
    # used elsewhere in this file (e.g. the SSN/credit-card tests).
    r = Redactor()
    text = "Server log shows the connection originated from 192.168.1.105 at 03:00."
    out, report = r.redact(text)
    assert "192.168.1.105" not in out
    assert "[REDACTED_IP_ADDRESS]" in out
    assert report.counts.get("IP_ADDRESS") == 1


# --- stress tests: genuine IPs in the SAME positions the OLD (now-removed)
# heuristic treated as non-IPs. These used to be xfail(strict=True) — the old
# keyword/line-start/trailing-dot exemptions caused all three to leak. The
# tightening removed those exemptions entirely (see _is_real_ip), so these
# now pass as plain assertions. If any of these starts failing again, that
# means a leak has been reintroduced — stop and investigate, don't re-mark
# as xfail.


def test_genuine_ip_at_start_of_line_is_still_redacted():
    r = Redactor()
    text = "Connection log:\n192.168.1.105 was the source of the unauthorized request."
    out, report = r.redact(text)
    assert "192.168.1.105" not in out
    assert report.counts.get("IP_ADDRESS") == 1


def test_genuine_ip_preceded_by_section_keyword_is_still_redacted():
    r = Redactor()
    text = "The affected host is documented in Section 192.168.1.1 of the network appendix."
    out, report = r.redact(text)
    assert "192.168.1.1" not in out
    assert report.counts.get("IP_ADDRESS") == 1


def test_genuine_ip_at_end_of_sentence_is_still_redacted():
    r = Redactor()
    text = "Connect to 192.168.1.105."
    out, report = r.redact(text)
    assert "192.168.1.105" not in out
    assert report.counts.get("IP_ADDRESS") == 1
