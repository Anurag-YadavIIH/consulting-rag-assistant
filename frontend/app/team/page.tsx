"use client";

import { useCallback, useEffect, useState } from "react";
import {
  createInvitation,
  listEngagements,
  listInvitations,
  listMembers,
  removeMember,
  revokeInvitation,
  updateMember,
  type InvitationInfo,
  type InviteRequest,
  type MemberInfo,
} from "../../lib/api";
import { engagementRoleFor } from "../../lib/team";
import { useMeContext } from "../../lib/meContext";
import { ErrorBanner } from "../../components/ErrorBanner";
import { InvitationTable, InviteForm, MemberEditor, MemberTable } from "../../components/team/TeamParts";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { EmptyState } from "../../components/ui/EmptyState";
import { Panel } from "../../components/ui/Panel";
import { Spinner } from "../../components/ui/Spinner";

type Pending =
  | { kind: "revoke"; invitation: InvitationInfo }
  | { kind: "remove"; member: MemberInfo }
  | null;

/**
 * Team: members, pending invitations, invite, edit and remove. Shown only to
 * admins; every call is also checked on the server (admin in the token and
 * in the database).
 */
export default function TeamPage() {
  const { meInfo } = useMeContext();
  const [members, setMembers] = useState<MemberInfo[] | null>(null);
  const [invitations, setInvitations] = useState<InvitationInfo[]>([]);
  const [engagements, setEngagements] = useState<string[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<MemberInfo | null>(null);
  const [pending, setPending] = useState<Pending>(null);

  const refresh = useCallback(async () => {
    try {
      const [m, i, e] = await Promise.all([listMembers(), listInvitations(), listEngagements()]);
      setMembers(m.members);
      setInvitations(i.invitations);
      setEngagements(e.engagements);
    } catch (err) {
      setError(err);
    }
  }, []);

  useEffect(() => {
    if (meInfo.is_admin) void refresh();
  }, [meInfo.is_admin, refresh]);

  async function run(action: () => Promise<unknown>, done: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
      setNotice(done);
      await refresh();
      return true;
    } catch (err) {
      setError(err);
      return false;
    } finally {
      setBusy(false);
    }
  }

  if (!meInfo.is_admin) {
    return (
      <div className="max-w-md">
        <EmptyState title="Admins only">Team access is managed by administrators.</EmptyState>
      </div>
    );
  }

  return (
    <div className="max-w-6xl space-y-8">
      <header>
        <h1 className="text-title text-ink">Team</h1>
        <p className="mt-2 max-w-prose text-base text-muted">
          Give people access by engagement and clearance. Role presets are shortcuts for a clearance
          level; they grant nothing on their own. Changes take effect at each person&apos;s next
          sign-in or token refresh, within 15 minutes.
        </p>
      </header>

      {notice ? (
        <p role="status" className="rounded-sm border border-ok bg-ok-bg px-4 py-2 text-sm text-ok">
          {notice}
        </p>
      ) : null}
      {error ? <ErrorBanner error={error} /> : null}

      <Panel title="Invite someone">
        <InviteForm
          knownEngagements={engagements}
          busy={busy}
          onInvite={(invite: InviteRequest) =>
            void run(() => createInvitation(invite), `Invitation created. Share the app link with them.`)
          }
        />
      </Panel>

      <Panel title={`Pending invitations${invitations.length ? ` (${invitations.length})` : ""}`}>
        <InvitationTable invitations={invitations} onRevoke={(inv) => setPending({ kind: "revoke", invitation: inv })} />
      </Panel>

      <Panel title="Members">
        {members === null ? (
          <Spinner label="Loading members..." />
        ) : (
          <MemberTable
            members={members}
            currentUserId={meInfo.user_id}
            onEdit={(m) => setEditing(m)}
            onRemove={(m) => setPending({ kind: "remove", member: m })}
          />
        )}
      </Panel>

      {editing ? (
        <Panel title="Edit access">
          <MemberEditor
            key={editing.user_id}
            member={editing}
            isSelf={editing.user_id === meInfo.user_id}
            knownEngagements={engagements}
            busy={busy}
            onCancel={() => setEditing(null)}
            onSave={(u) =>
              void run(
                () =>
                  updateMember(editing.user_id, {
                    clearance: u.clearance,
                    is_admin: u.is_admin,
                    engagements: u.engagements.map((e) => ({ engagement: e, role: engagementRoleFor(u.role) })),
                  }),
                "Access updated."
              ).then((ok) => ok && setEditing(null))
            }
          />
        </Panel>
      ) : null}

      <ConfirmDialog
        open={pending !== null}
        title={pending?.kind === "remove" ? "Remove this person's access?" : "Revoke this invitation?"}
        confirmLabel={pending?.kind === "remove" ? "Remove access" : "Revoke invitation"}
        busy={busy}
        onCancel={() => setPending(null)}
        onConfirm={() => {
          const p = pending;
          if (!p) return;
          void (p.kind === "remove"
            ? run(() => removeMember(p.member.user_id), "Access removed.")
            : run(() => revokeInvitation(p.invitation.id), "Invitation revoked.")
          ).then(() => setPending(null));
        }}
      >
        {pending?.kind === "remove" ? (
          <p>
            <span className="break-all text-ink">{pending.member.email}</span> loses every engagement,
            admin rights and clearance above 1, and is signed out of new sessions. A page they already
            have open can keep working for up to 15 minutes.
          </p>
        ) : pending?.kind === "revoke" ? (
          <p>
            The invitation for <span className="break-all text-ink">{pending.invitation.email}</span> stops
            working. You can invite them again later.
          </p>
        ) : null}
      </ConfirmDialog>
    </div>
  );
}
