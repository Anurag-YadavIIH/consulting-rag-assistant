/**
 * Light, Dark or System theme. The choice is the only thing this app keeps
 * in localStorage, and every access is wrapped in try/catch, so blocked
 * storage just means "System" every time.
 *
 * "light"/"dark" set html[data-theme]; "system" removes it and lets the
 * prefers-color-scheme media query in app/globals.css decide.
 * public/theme-init.js applies the saved choice before first paint; keep the
 * key and values in step with it.
 */

export type ThemeChoice = "light" | "dark" | "system";

export const THEME_STORAGE_KEY = "consultrag-theme";
export const THEME_CHOICES: ThemeChoice[] = ["light", "dark", "system"];

function isChoice(value: unknown): value is ThemeChoice {
  return value === "light" || value === "dark" || value === "system";
}

export function readThemeChoice(): ThemeChoice {
  try {
    const value = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isChoice(value) ? value : "system";
  } catch {
    return "system";
  }
}

export function saveThemeChoice(choice: ThemeChoice): void {
  try {
    if (choice === "system") window.localStorage.removeItem(THEME_STORAGE_KEY);
    else window.localStorage.setItem(THEME_STORAGE_KEY, choice);
  } catch {
    // Storage blocked: the choice still applies for this page view.
  }
}

export function applyThemeChoice(choice: ThemeChoice, root: HTMLElement = document.documentElement): void {
  if (choice === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", choice);
}
