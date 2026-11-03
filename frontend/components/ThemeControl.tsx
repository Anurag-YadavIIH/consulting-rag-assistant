"use client";

import { useEffect, useState } from "react";
import { applyThemeChoice, readThemeChoice, saveThemeChoice, THEME_CHOICES, type ThemeChoice } from "../lib/theme";

const LABELS: Record<ThemeChoice, string> = { light: "Light", dark: "Dark", system: "System" };

/** Light / Dark / System as a radio group, for the dark sidebar. */
export function ThemeControl() {
  // "system" on the server and first render; the saved choice is read after
  // mount (public/theme-init.js has already applied it to the page).
  const [choice, setChoice] = useState<ThemeChoice>("system");

  useEffect(() => {
    setChoice(readThemeChoice());
  }, []);

  function choose(next: ThemeChoice) {
    setChoice(next);
    applyThemeChoice(next);
    saveThemeChoice(next);
  }

  return (
    <fieldset>
      <legend className="mb-1 text-xs text-side-muted">Theme</legend>
      <div className="grid grid-cols-3 border border-side-border">
        {THEME_CHOICES.map((c) => (
          <label
            key={c}
            className={`relative flex min-h-target cursor-pointer items-center justify-center text-sm transition-colors focus-within:outline focus-within:outline-[3px] focus-within:outline-offset-[-3px] focus-within:outline-accent ${
              choice === c ? "bg-accent font-medium text-on-accent" : "text-side-text hover:bg-side-raised"
            }`}
          >
            <input
              type="radio"
              name="theme"
              value={c}
              checked={choice === c}
              onChange={() => choose(c)}
              className="sr-only"
            />
            {LABELS[c]}
          </label>
        ))}
      </div>
    </fieldset>
  );
}
