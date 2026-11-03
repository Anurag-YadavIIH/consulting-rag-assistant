"""
Sign-in access settings, parsed strictly:

  * INITIAL_ADMIN_EMAILS: comma-separated emails. An account whose Google
    email is listed (and verified) becomes a global admin the first time it
    signs in, once. For bootstrapping the first admin without shell access.
  * ALLOWED_EMAIL_DOMAINS: optional comma-separated domains. When set, only
    accounts on those domains may sign in, plus emails with an invitation
    and emails in INITIAL_ADMIN_EMAILS (so the first admin and invited
    outside collaborators aren't locked out).

Both fail closed: a malformed value raises, and the app refuses to start
(api/main.py) rather than guessing what was meant. Emails and domains are
compared lower-cased and trimmed.
"""

from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"^[^@\s,]+@[a-z0-9-]+(\.[a-z0-9-]+)+$")
_DOMAIN_RE = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def is_valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(normalize_email(email)))


def email_domain(email: str) -> str:
    return normalize_email(email).rsplit("@", 1)[-1]


def _items(raw: str | None) -> list[str]:
    return [p.strip().lower() for p in (raw or "").split(",") if p.strip()]


def parse_email_list(raw: str | None) -> frozenset[str]:
    items = _items(raw)
    bad = [i for i in items if not _EMAIL_RE.match(i)]
    if bad:
        raise ValueError(f"{len(bad)} malformed email address(es) in INITIAL_ADMIN_EMAILS")
    return frozenset(items)


def parse_domain_list(raw: str | None) -> frozenset[str]:
    items = [i.lstrip("@") for i in _items(raw)]
    bad = [i for i in items if not _DOMAIN_RE.match(i)]
    if bad:
        raise ValueError(f"{len(bad)} malformed domain(s) in ALLOWED_EMAIL_DOMAINS")
    return frozenset(items)


def ensure_access_settings_valid(initial_admin_emails: str | None, allowed_email_domains: str | None) -> None:
    """Refuses to start on a malformed setting. The message never repeats the
    values (they're personal data)."""
    try:
        parse_email_list(initial_admin_emails)
        parse_domain_list(allowed_email_domains)
    except ValueError as e:
        raise RuntimeError(f"Refusing to start: {e}. Use comma-separated values.") from e
