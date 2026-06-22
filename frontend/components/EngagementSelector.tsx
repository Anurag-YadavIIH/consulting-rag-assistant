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
      <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1.5">
        No engagements found, and no NEXT_PUBLIC_FALLBACK_ENGAGEMENTS configured.
      </div>
    );
  }

  return (
    <div>
      <label className="block text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">
        Engagement
      </label>
      <select
        className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
      >
        {options.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>
    </div>
  );
}
