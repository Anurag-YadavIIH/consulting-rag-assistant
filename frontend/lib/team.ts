/**
 * Role presets for the Team page. They're shortcuts over the two things that
 * actually control access, engagement membership and clearance, plus the
 * global admin role. A label grants nothing by itself. Mirrors
 * src/consultrag/authz/team.py PRESETS.
 */
import type { TeamRole } from "./api";

export const PRESETS: Record<TeamRole, { label: string; clearance: number; isAdmin: boolean }> = {
  analyst: { label: "Analyst", clearance: 1, isAdmin: false },
  manager: { label: "Manager", clearance: 2, isAdmin: false },
  senior_management: { label: "Senior management", clearance: 3, isAdmin: false },
  admin: { label: "Admin", clearance: 3, isAdmin: true },
};

export const PRESET_ORDER: TeamRole[] = ["analyst", "manager", "senior_management", "admin"];
export const MIN_CLEARANCE = 1;
export const MAX_CLEARANCE = 5;

/** The label shown for a user: Admin, a preset by clearance, or "Clearance N". */
export function roleLabel(isAdmin: boolean, clearance: number): string {
  if (isAdmin) return "Admin";
  const match = PRESET_ORDER.find((k) => k !== "admin" && PRESETS[k].clearance === clearance);
  return match ? PRESETS[match].label : `Clearance ${clearance}`;
}

/** The engagement label stored for a preset (never "admin"). */
export function engagementRoleFor(role: TeamRole): "analyst" | "manager" | "senior_management" {
  return role === "admin" ? "senior_management" : role;
}
