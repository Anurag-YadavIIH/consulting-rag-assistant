"""
DEV_AUTH_BYPASS — local-only convenience that injects a fixed User instead
of requiring a real token, so you can hit the API without a Google account
during development. Fails LOUD and CLOSED:

  * Permitted only if APP_ENV is EXPLICITLY one of _DEV_ENV_VALUES — a
    whitelist, not a blacklist. An unset, empty, misspelled, or otherwise
    unrecognized APP_ENV (including "staging", "Production", or nothing at
    all) denies bypass. There is no "anything that isn't literally
    'production' is fine" fallback — a forgotten or mistyped env var must
    fail toward auth-enabled, never toward bypass-enabled.
  * If DEV_AUTH_BYPASS=true is set without APP_ENV explicitly confirming a
    dev environment, the app refuses to start (RuntimeError), not a warning.
  * When actually active, startup logs a clear, visible warning — bypassing
    authentication must never be silently invisible.
"""

from __future__ import annotations

import logging

from ..security.access import User

logger = logging.getLogger(__name__)

_DEV_ENV_VALUES = {"development", "dev"}

DEV_USER = User(user_id="dev-bypass-user", roles=frozenset({"admin"}), clearance=99)


def is_dev_auth_bypass_permitted(app_env: str | None) -> bool:
    """Whitelist, not blacklist: True only if app_env explicitly names a dev
    environment. Anything else — unset, empty, misspelled, "staging",
    "Production" — returns False."""
    return (app_env or "").strip().lower() in _DEV_ENV_VALUES


def ensure_dev_auth_bypass_is_safe(dev_auth_bypass: bool, app_env: str | None) -> None:
    """Refuses to start (raises RuntimeError) if bypass is on without APP_ENV
    explicitly confirming a dev environment. No-op if bypass is off."""
    if not dev_auth_bypass:
        return
    if not is_dev_auth_bypass_permitted(app_env):
        raise RuntimeError(
            f"DEV_AUTH_BYPASS=true requires APP_ENV to explicitly be one of "
            f"{sorted(_DEV_ENV_VALUES)!r} (got APP_ENV={app_env!r}). Refusing "
            f"to start — an unset or misspelled APP_ENV must never leave "
            f"authentication bypassed."
        )


def warn_bypass_active() -> None:
    logger.warning(
        "DEV_AUTH_BYPASS is ACTIVE — authentication is disabled; every "
        "request is treated as user_id=%s with roles=%s. This must never be "
        "set in a real deployment.",
        DEV_USER.user_id, sorted(DEV_USER.roles),
    )
