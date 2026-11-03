"use client";

import { useState } from "react";
import type { InvitationInfo, InviteRequest, MemberInfo, TeamRole } from "../../lib/api";
import { MAX_CLEARANCE, MIN_CLEARANCE, PRESETS, PRESET_ORDER, roleLabel } from "../../lib/team";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { Field, inputClass } from "../ui/Field";
import { Select } from "../ui/Select";

function formatDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(undefined, { dateStyle: "medium" });
}

/** Engagement checkboxes, plus a box to add an engagement not listed yet. */
export function EngagementPicker({
  idPrefix,
  known,
  selected,
  onChange,
}: {
  idPrefix: string;
  known: string[];
  selected: string[];
  onChange: (next: string[]) => void;
}) {
  const [extra, setExtra] = useState("");
  const all = Array.from(new Set([...known, ...selected])).sort();
  const toggle = (e: string) =>
    onChange(selected.includes(e) ? selected.filter((x) => x !== e) : [...selected, e]);
  return (
    <fieldset>
      <legend className="mb-1.5 text-sm font-medium text-ink">Engagements</legend>
      {all.length === 0 ? <p className="text-sm text-muted">No engagements yet; add one below.</p> : null}
      <div className="flex flex-wrap gap-2">
        {all.map((e) => (
          <label
            key={e}
            className={`inline-flex min-h-target cursor-pointer items-center gap-2 rounded-sm border px-3 text-sm transition-colors focus-within:outline focus-within:outline-[3px] focus-within:outline-offset-2 focus-within:outline-focus ${
              selected.includes(e) ? "border-accent bg-accent text-on-accent" : "border-field bg-panel text-ink hover:bg-raised"
            }`}
          >
            <input type="checkbox" className="sr-only" checked={selected.includes(e)} onChange={() => toggle(e)} />
            <span className="font-mono">{e}</span>
          </label>
        ))}
      </div>
      <div className="mt-2 flex max-w-sm gap-2">
        <label htmlFor={`${idPrefix}-new-engagement`} className="sr-only">
          Add an engagement
        </label>
        <input
          id={`${idPrefix}-new-engagement`}
          className={inputClass}
          placeholder="Add an engagement, e.g. meridian"
          value={extra}
          onChange={(ev) => setExtra(ev.target.value)}
        />
        <Button
          variant="secondary"
          disabled={!extra.trim()}
          onClick={() => {
            const name = extra.trim().toLowerCase();
            if (name && !selected.includes(name)) onChange([...selected, name]);
            setExtra("");
          }}
        >
          Add
        </Button>
      </div>
    </fieldset>
  );
}

export function InviteForm({
  knownEngagements,
  busy,
  onInvite,
}: {
  knownEngagements: string[];
  busy: boolean;
  onInvite: (invite: InviteRequest) => void;
}) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<TeamRole>("analyst");
  const [clearance, setClearance] = useState(PRESETS.analyst.clearance);
  const [engagements, setEngagements] = useState<string[]>([]);
  const isAdmin = PRESETS[role].isAdmin;

  return (
    <form
      className="space-y-5"
      onSubmit={(e) => {
        e.preventDefault();
        onInvite({ email: email.trim(), engagements, role, clearance, is_admin: isAdmin });
      }}
    >
      <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_14rem_8rem]">
        <Field id="invite-email" label="Google account email">
          <input
            id="invite-email"
            type="email"
            required
            autoComplete="off"
            className={inputClass}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </Field>
        <Field id="invite-role" label="Role preset">
          <Select
            id="invite-role"
            value={role}
            onChange={(e) => {
              const next = e.target.value as TeamRole;
              setRole(next);
              setClearance(PRESETS[next].clearance);
            }}
          >
            {PRESET_ORDER.map((k) => (
              <option key={k} value={k}>
                {PRESETS[k].label} (clearance {PRESETS[k].clearance})
              </option>
            ))}
          </Select>
        </Field>
        <Field id="invite-clearance" label="Clearance">
          <input
            id="invite-clearance"
            type="number"
            min={MIN_CLEARANCE}
            max={MAX_CLEARANCE}
            className={inputClass}
            value={clearance}
            onChange={(e) => setClearance(Number(e.target.value))}
          />
        </Field>
      </div>
      <EngagementPicker idPrefix="invite" known={knownEngagements} selected={engagements} onChange={setEngagements} />
      <p className="max-w-prose text-sm text-muted">
        Presets only set the clearance{isAdmin ? " and the admin role" : ""}; access comes from the
        engagements chosen. No email is sent: share the app link with them. The invitation applies
        once, the first time they sign in with this Google account, and expires after 14 days unless
        configured otherwise.
      </p>
      <Button type="submit" disabled={busy || !email.trim() || (!isAdmin && engagements.length === 0)} className="min-w-[10rem]">
        {busy ? "Inviting..." : "Create invitation"}
      </Button>
    </form>
  );
}

export function InvitationTable({
  invitations,
  onRevoke,
}: {
  invitations: InvitationInfo[];
  onRevoke: (inv: InvitationInfo) => void;
}) {
  if (invitations.length === 0) return <p className="text-sm text-muted">No pending invitations.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[36rem] border-collapse text-left text-sm">
        <caption className="sr-only">Pending invitations</caption>
        <thead>
          <tr className="border-b border-rule text-muted">
            <th scope="col" className="py-2 pr-4 font-medium">Email</th>
            <th scope="col" className="py-2 pr-4 font-medium">Role</th>
            <th scope="col" className="py-2 pr-4 font-medium">Engagements</th>
            <th scope="col" className="py-2 pr-4 font-medium">Expires</th>
            <th scope="col" className="py-2 font-medium"><span className="sr-only">Actions</span></th>
          </tr>
        </thead>
        <tbody>
          {invitations.map((inv) => (
            <tr key={inv.id} className="border-b border-rule last:border-b-0">
              <td className="break-all py-2 pr-4 text-ink">{inv.email}</td>
              <td className="py-2 pr-4 text-ink">
                {inv.is_admin ? "Admin" : roleLabel(false, inv.clearance)}
                <span className="text-muted"> · clearance {inv.clearance}</span>
              </td>
              <td className="py-2 pr-4 font-mono text-ink">{inv.engagements.join(", ")}</td>
              <td className="py-2 pr-4 text-muted">{formatDate(inv.expires_at)}</td>
              <td className="py-1 text-right">
                <button
                  type="button"
                  onClick={() => onRevoke(inv)}
                  aria-label={`Revoke invitation for ${inv.email}`}
                  className="inline-flex min-h-target items-center rounded-sm border border-transparent px-3 text-sm text-danger transition-colors hover:border-danger hover:bg-danger-bg"
                >
                  Revoke
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function MemberTable({
  members,
  currentUserId,
  onEdit,
  onRemove,
}: {
  members: MemberInfo[];
  currentUserId: string;
  onEdit: (m: MemberInfo) => void;
  onRemove: (m: MemberInfo) => void;
}) {
  if (members.length === 0) return <p className="text-sm text-muted">No one has signed in yet.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[44rem] border-collapse text-left text-sm">
        <caption className="sr-only">Members</caption>
        <thead>
          <tr className="border-b border-rule text-muted">
            <th scope="col" className="py-2 pr-4 font-medium">Member</th>
            <th scope="col" className="py-2 pr-4 font-medium">Role</th>
            <th scope="col" className="py-2 pr-4 font-medium">Clearance</th>
            <th scope="col" className="py-2 pr-4 font-medium">Engagements</th>
            <th scope="col" className="py-2 font-medium"><span className="sr-only">Actions</span></th>
          </tr>
        </thead>
        <tbody>
          {members.map((m) => {
            const self = m.user_id === currentUserId;
            return (
              <tr key={m.user_id} className="border-b border-rule align-top last:border-b-0">
                <td className="py-2 pr-4">
                  <span className="block break-all text-ink">{m.email}</span>
                  <span className="text-xs text-muted">
                    User # <span className="font-mono">{m.user_id}</span>
                    {self ? " (you)" : ""}
                  </span>
                </td>
                <td className="py-2 pr-4 text-ink">
                  {m.has_access ? roleLabel(m.is_admin, m.clearance) : <Badge tone="neutral">No access</Badge>}
                </td>
                <td className="py-2 pr-4 text-ink">{m.clearance}</td>
                <td className="py-2 pr-4 font-mono text-ink">
                  {m.engagements.map((e) => e.engagement).join(", ") || <span className="font-sans text-muted">None</span>}
                </td>
                <td className="whitespace-nowrap py-1 text-right">
                  <button
                    type="button"
                    onClick={() => onEdit(m)}
                    aria-label={`Edit access for ${m.email}`}
                    className="inline-flex min-h-target items-center rounded-sm border border-transparent px-3 text-sm text-link transition-colors hover:border-field hover:bg-raised"
                  >
                    Edit
                  </button>
                  {!self && m.has_access ? (
                    <button
                      type="button"
                      onClick={() => onRemove(m)}
                      aria-label={`Remove access for ${m.email}`}
                      className="inline-flex min-h-target items-center rounded-sm border border-transparent px-3 text-sm text-danger transition-colors hover:border-danger hover:bg-danger-bg"
                    >
                      Remove
                    </button>
                  ) : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function MemberEditor({
  member,
  isSelf,
  knownEngagements,
  busy,
  onSave,
  onCancel,
}: {
  member: MemberInfo;
  isSelf: boolean;
  knownEngagements: string[];
  busy: boolean;
  onSave: (update: { clearance: number; is_admin: boolean; engagements: string[]; role: TeamRole }) => void;
  onCancel: () => void;
}) {
  const initialRole: TeamRole = member.is_admin
    ? "admin"
    : (["analyst", "manager", "senior_management"] as TeamRole[]).find((k) => PRESETS[k].clearance === member.clearance) ??
      "analyst";
  const [role, setRole] = useState<TeamRole>(initialRole);
  const [clearance, setClearance] = useState(member.clearance);
  const [isAdmin, setIsAdmin] = useState(member.is_admin);
  const [engagements, setEngagements] = useState(member.engagements.map((e) => e.engagement));

  return (
    <form
      className="space-y-5"
      onSubmit={(e) => {
        e.preventDefault();
        onSave({ clearance, is_admin: isAdmin, engagements, role });
      }}
    >
      <p className="text-base text-ink">
        Editing <span className="break-all font-medium">{member.email}</span>
      </p>
      <div className="grid gap-4 sm:grid-cols-[14rem_8rem]">
        <Field id="edit-role" label="Role preset">
          <Select
            id="edit-role"
            value={role}
            onChange={(e) => {
              const next = e.target.value as TeamRole;
              setRole(next);
              setClearance(PRESETS[next].clearance);
              if (!(isSelf && isAdmin)) setIsAdmin(PRESETS[next].isAdmin);
            }}
          >
            {PRESET_ORDER.map((k) => (
              <option key={k} value={k}>
                {PRESETS[k].label}
              </option>
            ))}
          </Select>
        </Field>
        <Field id="edit-clearance" label="Clearance">
          <input
            id="edit-clearance"
            type="number"
            min={MIN_CLEARANCE}
            max={MAX_CLEARANCE}
            className={inputClass}
            value={clearance}
            onChange={(e) => setClearance(Number(e.target.value))}
          />
        </Field>
      </div>
      <label className="flex min-h-target items-center gap-3 text-sm text-ink">
        <input
          type="checkbox"
          className="h-5 w-5 accent-accent"
          checked={isAdmin}
          disabled={isSelf && member.is_admin}
          onChange={(e) => setIsAdmin(e.target.checked)}
        />
        Global admin (can manage the team and see every engagement, within their clearance)
      </label>
      {isSelf && member.is_admin ? (
        <p className="text-sm text-muted">You can&apos;t remove your own admin access. Ask another admin.</p>
      ) : null}
      <EngagementPicker idPrefix="edit" known={knownEngagements} selected={engagements} onChange={setEngagements} />
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={busy}>
          {busy ? "Saving..." : "Save changes"}
        </Button>
        <Button variant="secondary" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
      </div>
      <p className="text-sm text-muted">
        Changes reach this person at their next sign-in or token refresh, within 15 minutes.
      </p>
    </form>
  );
}
