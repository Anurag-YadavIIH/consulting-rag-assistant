"""
Team access management: sign-in grants (INITIAL_ADMIN_EMAILS and
invitations), and the admin operations behind the Team page.

What these change, and what that means:
  * Permissions come only from a global admin row (engagement NULL, role
    'admin') and from engagement memberships, plus the user's clearance.
    Membership role labels ('analyst', 'manager', 'senior_management') are
    descriptive presets and grant nothing on their own. New code never
    writes 'admin' as an engagement label (repository.get_user_authz would
    turn it into a global role).
  * Changes reach a user at their next token refresh at the latest (refresh
    re-reads Postgres). Removing someone also revokes their refresh tokens;
    an access token already issued stays valid for up to 15 minutes.
  * Every change is written to audit_events in the same transaction, with
    the actor's user ID, the target user ID or invitation ID, the action,
    engagement and clearance. Never an email.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from ..audit import insert_audit_event
from ..auth.access_settings import is_valid_email, normalize_email
from ..security.access import MAX_CLEARANCE, MIN_CLEARANCE

logger = logging.getLogger(__name__)

# Presets over (engagement label, clearance, admin). Admins are still
# subject to clearance when reading documents, so the Admin preset's
# clearance matters too.
PRESETS: dict[str, dict] = {
    "analyst": {"label": "Analyst", "clearance": 1, "is_admin": False},
    "manager": {"label": "Manager", "clearance": 2, "is_admin": False},
    "senior_management": {"label": "Senior management", "clearance": 3, "is_admin": False},
    "admin": {"label": "Admin", "clearance": 3, "is_admin": True},
}
# Labels allowed on engagement memberships. Never 'admin' (see above).
ENGAGEMENT_ROLES = ("analyst", "manager", "senior_management")
_ENGAGEMENT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class TeamError(Exception):
    """A refused team change. `status` is the HTTP status to answer with."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def engagement_role_for(role: str) -> str:
    """The label stored on engagement memberships for a preset."""
    return "senior_management" if role == "admin" else role


def validate_clearance(clearance: int) -> int:
    if not isinstance(clearance, int) or isinstance(clearance, bool) or not (
        MIN_CLEARANCE <= clearance <= MAX_CLEARANCE
    ):
        raise TeamError(422, f"clearance must be a whole number from {MIN_CLEARANCE} to {MAX_CLEARANCE}")
    return clearance


def validate_engagements(engagements: list[str]) -> list[str]:
    out: list[str] = []
    for e in engagements:
        name = (e or "").strip().lower()
        if not _ENGAGEMENT_RE.match(name):
            raise TeamError(
                422, "engagement names use lowercase letters, numbers, hyphens and underscores (max 64)"
            )
        if name not in out:
            out.append(name)
    return out


def _audit(cur, actor: str, action: str, *, target_user_id=None, invitation_id=None,
           engagement=None, clearance=None) -> None:
    insert_audit_event(cur, {
        "event": "access", "user_id": actor, "action": action,
        "target_user_id": target_user_id, "invitation_id": invitation_id,
        "engagement": engagement, "clearance": clearance,
    })


def _admin_count(cur) -> int:
    cur.execute(
        "SELECT COUNT(DISTINCT user_id) FROM engagement_memberships "
        "WHERE engagement IS NULL AND role = 'admin'"
    )
    return cur.fetchone()[0]


def _is_admin(cur, user_id: int) -> bool:
    cur.execute(
        "SELECT 1 FROM engagement_memberships WHERE user_id = %s AND engagement IS NULL AND role = 'admin'",
        (user_id,),
    )
    return cur.fetchone() is not None


def _lock_admins(cur) -> None:
    # Serializes every change that can add or remove an admin, so two
    # concurrent demotions can't both pass the last-admin check.
    cur.execute("LOCK TABLE engagement_memberships IN SHARE ROW EXCLUSIVE MODE")


def _add_membership(cur, user_id: int, engagement: str | None, role: str) -> bool:
    if engagement is not None and role == "admin":
        # Admin is global only (engagement NULL); never write it per engagement.
        raise TeamError(422, '"admin" is a global role, not an engagement role')
    cur.execute(
        """
        INSERT INTO engagement_memberships (user_id, engagement, role)
        VALUES (%s, %s, %s)
        ON CONFLICT ON CONSTRAINT engagement_memberships_user_engagement_role_uniq DO NOTHING
        """,
        (user_id, engagement, role),
    )
    return cur.rowcount == 1


# --- sign-in ------------------------------------------------------------------------


def has_invitation(conn, email: str) -> bool:
    """True if this email has a usable or an already-accepted invitation
    (used by the ALLOWED_EMAIL_DOMAINS rule)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM invitations WHERE email_norm = %s AND revoked_at IS NULL "
            "AND (accepted_at IS NOT NULL OR expires_at > now()) LIMIT 1",
            (normalize_email(email),),
        )
        found = cur.fetchone() is not None
    conn.commit()
    return found


def apply_sign_in_grants(conn, user_id: int, email: str, email_verified, initial_admins: frozenset[str]) -> list[str]:
    """At sign-in: grants from INITIAL_ADMIN_EMAILS (once per account) and
    from an open invitation (once), only when Google says the email is
    verified. Returns what was applied, for logging. One transaction."""
    if email_verified is not True:
        return []
    email_norm = normalize_email(email)
    applied: list[str] = []
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT clearance, initial_admin_applied_at FROM users WHERE id = %s FOR UPDATE", (user_id,))
            row = cur.fetchone()
            if row is None:
                conn.rollback()
                return []
            clearance, initial_applied = row

            if email_norm in initial_admins and initial_applied is None:
                _lock_admins(cur)
                _add_membership(cur, user_id, None, "admin")
                clearance = max(clearance, PRESETS["admin"]["clearance"])
                cur.execute(
                    "UPDATE users SET clearance = %s, initial_admin_applied_at = now() WHERE id = %s",
                    (clearance, user_id),
                )
                _audit(cur, "system", "initial_admin_granted", target_user_id=user_id, clearance=clearance)
                applied.append("initial_admin")

            cur.execute(
                "SELECT id, engagements, role, clearance, is_admin FROM invitations "
                "WHERE email_norm = %s AND accepted_at IS NULL AND revoked_at IS NULL "
                "AND expires_at > now() ORDER BY id DESC LIMIT 1 FOR UPDATE",
                (email_norm,),
            )
            inv = cur.fetchone()
            if inv is not None:
                inv_id, engagements, role, inv_clearance, inv_admin = inv
                if inv_admin:
                    _lock_admins(cur)
                    _add_membership(cur, user_id, None, "admin")
                for eng in engagements:
                    _add_membership(cur, user_id, eng, engagement_role_for(role))
                clearance = max(clearance, inv_clearance)
                cur.execute("UPDATE users SET clearance = %s WHERE id = %s", (clearance, user_id))
                cur.execute(
                    "UPDATE invitations SET accepted_at = now(), accepted_user_id = %s WHERE id = %s",
                    (user_id, inv_id),
                )
                for eng in engagements or [None]:
                    _audit(cur, "system", "invitation_accepted", target_user_id=user_id,
                           invitation_id=inv_id, engagement=eng, clearance=clearance)
                applied.append("invitation")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    for what in applied:
        # The user ID only; never the email.
        logger.info("sign-in grant applied: %s for user_id=%s", what, user_id)
    return applied


# --- reads for the Team page ------------------------------------------------------------


def preset_for(is_admin: bool, clearance: int) -> str:
    if is_admin:
        return "admin"
    return {1: "analyst", 2: "manager", 3: "senior_management"}.get(clearance, "custom")


def list_members(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT u.id, u.email, u.clearance, m.engagement, m.role
            FROM users u
            LEFT JOIN engagement_memberships m ON m.user_id = u.id
            ORDER BY u.id, m.engagement NULLS FIRST
            """
        )
        rows = cur.fetchall()
    conn.commit()
    members: dict[int, dict] = {}
    for uid, email, clearance, engagement, role in rows:
        m = members.setdefault(uid, {"user_id": str(uid), "email": email, "clearance": clearance,
                                     "is_admin": False, "engagements": []})
        if engagement is None and role == "admin":
            m["is_admin"] = True
        elif engagement is not None:
            m["engagements"].append({"engagement": engagement, "role": role})
    out = list(members.values())
    for m in out:
        m["preset"] = preset_for(m["is_admin"], m["clearance"])
        m["has_access"] = m["is_admin"] or bool(m["engagements"])
    return out


def list_invitations(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, email_norm, engagements, role, clearance, is_admin, created_at, expires_at "
            "FROM invitations WHERE accepted_at IS NULL AND revoked_at IS NULL AND expires_at > now() "
            "ORDER BY created_at DESC"
        )
        rows = cur.fetchall()
    conn.commit()
    return [
        {"id": r[0], "email": r[1], "engagements": list(r[2]), "role": r[3], "clearance": r[4],
         "is_admin": r[5], "created_at": r[6].isoformat(), "expires_at": r[7].isoformat()}
        for r in rows
    ]


def list_engagements(conn) -> list[str]:
    """Every engagement name known from memberships and open invitations
    (and documents, if the chunks table exists), for the invite form."""
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('chunks')")
        has_chunks = cur.fetchone()[0] is not None
        sql = (
            "SELECT engagement FROM engagement_memberships WHERE engagement IS NOT NULL "
            "UNION SELECT unnest(engagements) FROM invitations "
            "WHERE accepted_at IS NULL AND revoked_at IS NULL AND expires_at > now()"
        )
        if has_chunks:
            sql += " UNION SELECT engagement FROM chunks WHERE engagement IS NOT NULL"
        cur.execute(sql + " ORDER BY 1")
        names = [r[0] for r in cur.fetchall()]
    conn.commit()
    return names


def is_admin_in_db(conn, user_id: str) -> bool:
    """The Team routes re-check admin in Postgres (not just the token), so a
    demoted admin loses access to them immediately."""
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return False
    with conn.cursor() as cur:
        found = _is_admin(cur, uid)
    conn.commit()
    return found


# --- changes ----------------------------------------------------------------------------


@dataclass
class InviteSpec:
    email: str
    engagements: list[str] = field(default_factory=list)
    role: str = "analyst"
    clearance: int = 1
    is_admin: bool = False


def create_invitation(conn, actor: str, spec: InviteSpec, ttl_days: int) -> dict:
    email = normalize_email(spec.email)
    if not is_valid_email(email):
        raise TeamError(422, "enter a valid email address")
    if spec.role not in PRESETS:
        raise TeamError(422, "unknown role")
    validate_clearance(spec.clearance)
    engagements = validate_engagements(spec.engagements)
    if not engagements and not spec.is_admin:
        raise TeamError(422, "choose at least one engagement (or invite an admin)")
    if ttl_days < 1:
        raise TeamError(500, "INVITATION_TTL_DAYS must be at least 1")
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM users u WHERE lower(trim(u.email)) = %s AND EXISTS (
                    SELECT 1 FROM engagement_memberships m WHERE m.user_id = u.id)
                """,
                (email,),
            )
            if cur.fetchone():
                raise TeamError(409, "this person already has access; edit their access instead")
            cur.execute(
                "SELECT 1 FROM invitations WHERE email_norm = %s AND accepted_at IS NULL "
                "AND revoked_at IS NULL AND expires_at > now()",
                (email,),
            )
            if cur.fetchone():
                raise TeamError(409, "there's already an open invitation for this email")
            # Close expired open invitations so the unique index allows a new one.
            cur.execute(
                "UPDATE invitations SET revoked_at = now() WHERE email_norm = %s "
                "AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at <= now()",
                (email,),
            )
            cur.execute(
                """
                INSERT INTO invitations (email_norm, engagements, role, clearance, is_admin,
                                         created_by, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, now() + make_interval(days => %s))
                RETURNING id, created_at, expires_at
                """,
                (email, engagements, spec.role, spec.clearance, spec.is_admin, actor, ttl_days),
            )
            inv_id, created_at, expires_at = cur.fetchone()
            for eng in engagements or [None]:
                _audit(cur, actor, "invitation_created", invitation_id=inv_id,
                       engagement=eng, clearance=spec.clearance)
            if spec.is_admin:
                _audit(cur, actor, "invitation_created_admin", invitation_id=inv_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"id": inv_id, "email": email, "engagements": engagements, "role": spec.role,
            "clearance": spec.clearance, "is_admin": spec.is_admin,
            "created_at": created_at.isoformat(), "expires_at": expires_at.isoformat()}


def revoke_invitation(conn, actor: str, invitation_id: int) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE invitations SET revoked_at = now() WHERE id = %s "
                "AND accepted_at IS NULL AND revoked_at IS NULL RETURNING id",
                (invitation_id,),
            )
            if cur.fetchone() is None:
                raise TeamError(404, "no open invitation with that ID")
            _audit(cur, actor, "invitation_revoked", invitation_id=invitation_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def update_member(conn, actor: str, target_id: int, *, clearance: int | None = None,
                  is_admin: bool | None = None, engagements: list[dict] | None = None) -> None:
    """Applies only the given fields. `engagements` replaces the member's
    engagement memberships: [{"engagement": name, "role": label}]."""
    if clearance is not None:
        validate_clearance(clearance)
    if engagements is not None:
        names = validate_engagements([e.get("engagement", "") for e in engagements])
        roles = [e.get("role", "analyst") for e in engagements]
        if any(r not in ENGAGEMENT_ROLES for r in roles):
            raise TeamError(422, "engagement role must be analyst, manager or senior_management")
        wanted = dict(zip(names, roles))
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT clearance FROM users WHERE id = %s FOR UPDATE", (target_id,))
            row = cur.fetchone()
            if row is None:
                raise TeamError(404, "no such member")
            if is_admin is not None:
                _lock_admins(cur)
                currently = _is_admin(cur, target_id)
                if currently and not is_admin:
                    if str(target_id) == str(actor):
                        raise TeamError(409, "you can't remove your own admin access; ask another admin")
                    if _admin_count(cur) <= 1:
                        raise TeamError(409, "this is the last admin; make someone else an admin first")
                    cur.execute(
                        "DELETE FROM engagement_memberships WHERE user_id = %s AND engagement IS NULL AND role = 'admin'",
                        (target_id,),
                    )
                    _audit(cur, actor, "admin_revoked", target_user_id=target_id)
                elif is_admin and not currently:
                    _add_membership(cur, target_id, None, "admin")
                    _audit(cur, actor, "admin_granted", target_user_id=target_id)
            if clearance is not None and clearance != row[0]:
                cur.execute("UPDATE users SET clearance = %s WHERE id = %s", (clearance, target_id))
                _audit(cur, actor, "clearance_changed", target_user_id=target_id, clearance=clearance)
            if engagements is not None:
                cur.execute(
                    "SELECT engagement, role FROM engagement_memberships "
                    "WHERE user_id = %s AND engagement IS NOT NULL",
                    (target_id,),
                )
                current = {e: r for e, r in cur.fetchall()}
                for eng, role in current.items():
                    if wanted.get(eng) != role:
                        cur.execute(
                            "DELETE FROM engagement_memberships WHERE user_id = %s AND engagement = %s",
                            (target_id, eng),
                        )
                        if eng not in wanted:
                            _audit(cur, actor, "membership_removed", target_user_id=target_id, engagement=eng)
                for eng, role in wanted.items():
                    if current.get(eng) != role:
                        _add_membership(cur, target_id, eng, role)
                        _audit(cur, actor, "membership_set", target_user_id=target_id, engagement=eng)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def remove_member(conn, actor: str, target_id: int) -> None:
    """Removes all of a member's access (memberships, admin, clearance back
    to 1) and revokes their refresh tokens. The user row stays, for the audit
    trail; they can be invited again."""
    if str(target_id) == str(actor):
        raise TeamError(409, "you can't remove your own access; ask another admin")
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE id = %s FOR UPDATE", (target_id,))
            if cur.fetchone() is None:
                raise TeamError(404, "no such member")
            _lock_admins(cur)
            if _is_admin(cur, target_id) and _admin_count(cur) <= 1:
                raise TeamError(409, "this is the last admin; make someone else an admin first")
            cur.execute("DELETE FROM engagement_memberships WHERE user_id = %s", (target_id,))
            cur.execute(
                "UPDATE users SET clearance = 1, refresh_version = refresh_version + 1 WHERE id = %s",
                (target_id,),
            )
            _audit(cur, actor, "access_removed", target_user_id=target_id, clearance=1)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
