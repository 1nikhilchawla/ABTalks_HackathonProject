/**
 * Local durability.
 *
 * The server owns interview state; this only remembers *which* interview the
 * tab was in and what the candidate had half-typed, so a refresh, a crash or a
 * dropped connection never loses a partially written answer.
 */

const SESSION_KEY = "cohortiq.session";
const DRAFT_KEY = "cohortiq.draft";
const THEME_KEY = "cohortiq.theme";

function safeGet(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null; // private mode / storage disabled
  }
}

function safeSet(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* storage full or blocked — the app still works, it just forgets */
  }
}

function safeRemove(key: string) {
  try {
    window.localStorage.removeItem(key);
  } catch {
    /* ignore */
  }
}

export function newSessionId(): string {
  const random =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : Math.random().toString(36).slice(2) + Date.now().toString(36);
  return `iq-${random}`;
}

export const storedSession = {
  get: () => safeGet(SESSION_KEY),
  set: (id: string) => safeSet(SESSION_KEY, id),
  clear: () => {
    safeRemove(SESSION_KEY);
    safeRemove(DRAFT_KEY);
  },
};

export const storedDraft = {
  get: () => safeGet(DRAFT_KEY) ?? "",
  set: (value: string) => (value ? safeSet(DRAFT_KEY, value) : safeRemove(DRAFT_KEY)),
  clear: () => safeRemove(DRAFT_KEY),
};

export type Theme = "dark" | "light";

export const theme = {
  get(): Theme {
    const stored = safeGet(THEME_KEY);
    if (stored === "light" || stored === "dark") return stored;
    return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
  },
  set(value: Theme) {
    safeSet(THEME_KEY, value);
    document.documentElement.setAttribute("data-theme", value);
  },
  apply() {
    document.documentElement.setAttribute("data-theme", theme.get());
  },
};

export function messageId(): string {
  return Math.random().toString(36).slice(2, 10);
}
