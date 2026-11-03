import { Field } from "./ui/Field";
import { Select } from "./ui/Select";

export function EngagementSelector({
  options,
  value,
  onChange,
}: {
  options: string[];
  value: string | undefined;
  onChange: (engagement: string) => void;
}) {
  if (options.length === 0) {
    return (
      <p className="rounded-sm border border-side-border px-3 py-2 text-xs text-side-text">
        No engagements found, and no NEXT_PUBLIC_FALLBACK_ENGAGEMENTS configured.
      </p>
    );
  }

  return (
    <Field id="engagement-select" label="Engagement" dark>
      <Select id="engagement-select" dark value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
        {options.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </Select>
    </Field>
  );
}
