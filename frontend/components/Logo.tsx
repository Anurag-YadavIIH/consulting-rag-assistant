/**
 * The ConsultRAG mark: a square page with three lines of text, the middle
 * one drawn as a solid redaction bar. Accent square, ink lines, on a 16-unit
 * grid with whole-pixel edges so it stays crisp at 16px. The same drawing is
 * public/logo.svg and public/favicon.svg.
 */
export function LogoMark({ size = 24, title }: { size?: number; title?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      focusable="false"
      shapeRendering="crispEdges"
    >
      <rect width="16" height="16" fill="#7CC4FF" />
      <rect x="3" y="2" width="10" height="2" fill="#15211E" />
      <rect x="3" y="6" width="10" height="4" fill="#15211E" />
      <rect x="3" y="12" width="7" height="2" fill="#15211E" />
    </svg>
  );
}

/**
 * Mark plus the two-tone wordmark. `surface="dark"` (the sidebar and phone
 * bar) shows "RAG" in the accent; on main surfaces it uses `brand-strong`,
 * which is bold ink in the light theme (the accent on white is only 1.88:1)
 * and the accent in the dark theme.
 */
export function Wordmark({ surface = "main", size = 24 }: { surface?: "main" | "dark"; size?: number }) {
  const consult = surface === "dark" ? "text-side-text" : "text-ink";
  const rag = surface === "dark" ? "text-accent" : "text-brand-strong";
  return (
    <span className="inline-flex items-center gap-2">
      <LogoMark size={size} />
      <span className="font-display text-xl font-semibold tracking-tight">
        <span className={consult}>Consult</span>
        <span className={`${rag} font-bold`}>RAG</span>
      </span>
    </span>
  );
}
