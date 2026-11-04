import Link from "next/link";
import { Field } from "./ui/Field";
import { Select } from "./ui/Select";

export function EngagementSelector({
  options,
  value,
  onChange,
  isAdmin = false,
  loadFailed = false,
  onRetry,
}: {
  options: string[];
  value: string | undefined;
  onChange: (engagement: string) => void;
  isAdmin?: boolean;
  /** Admins only: GET /admin/engagements failed. */
  loadFailed?: boolean;
  onRetry?: () => void;
}) {
  const failure = loadFailed ? (
    <div role="alert" className="space-y-2 rounded-sm border border-side-border px-3 py-2 text-xs text-side-text">
      <p>
        Couldn&apos;t load the full engagement list.
        {options.length > 0 ? " Showing your own engagements only." : ""}
      </p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="min-h-target rounded-sm border border-side-border px-3 text-xs font-medium text-side-text transition-colors hover:bg-side-raised"
        >
          Try again
        </button>
      ) : null}
    </div>
  ) : null;

  if (options.length === 0) {
    if (failure) return failure;
    return (
      <div className="rounded-sm border border-side-border px-3 py-2 text-xs text-side-text">
        {isAdmin ? (
          <p>
            No engagements yet. An engagement appears here once someone has access to it or a
            document in it. Add one on the{" "}
            <Link href="/team/" className="font-medium text-accent underline">
              Team page
            </Link>
            .
          </p>
        ) : (
          <p>No engagements available.</p>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <Field id="engagement-select" label="Engagement" dark>
        <Select id="engagement-select" dark value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
          {options.map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </Select>
      </Field>
      {failure}
    </div>
  );
}
