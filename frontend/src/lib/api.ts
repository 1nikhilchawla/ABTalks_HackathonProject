import type {
  CohortInsights,
  InterviewReply,
  Persona,
  PlanPreview,
  RosterEntry,
  SessionState,
  Feedback,
  Report,
} from "./types";

const BASE = "/api";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly retryable: boolean,
  ) {
    super(message);
  }
}

/** One fetch with a timeout, bounded retries, and a typed failure. */
async function request<T>(
  path: string,
  init: RequestInit = {},
  { retries = 2, timeoutMs = 90_000 }: { retries?: number; timeoutMs?: number } = {},
): Promise<T> {
  let lastError: unknown;

  for (let attempt = 0; attempt <= retries; attempt++) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(`${BASE}${path}`, {
        ...init,
        signal: controller.signal,
        headers: { "content-type": "application/json", ...(init.headers ?? {}) },
      });
      window.clearTimeout(timer);

      if (response.status === 429) {
        const wait = Number(response.headers.get("retry-after") ?? 2) * 1000;
        if (attempt < retries) {
          await sleep(Math.min(wait, 5000));
          continue;
        }
        throw new ApiError("Too many requests — slow down a moment.", 429, true);
      }
      if (!response.ok) {
        const retryable = response.status >= 500;
        if (retryable && attempt < retries) {
          await sleep(400 * 2 ** attempt);
          continue;
        }
        throw new ApiError(`Server responded ${response.status}`, response.status, retryable);
      }
      return (await response.json()) as T;
    } catch (error) {
      window.clearTimeout(timer);
      lastError = error;
      if (error instanceof ApiError && !error.retryable) throw error;
      const aborted = error instanceof DOMException && error.name === "AbortError";
      if (attempt < retries) {
        await sleep(400 * 2 ** attempt);
        continue;
      }
      if (aborted) {
        throw new ApiError("That took too long. Your answer is safe — try sending again.", 408, true);
      }
      throw new ApiError(
        navigator.onLine
          ? "Couldn't reach the interview service."
          : "You're offline. Your answer is saved locally — reconnect and resend.",
        0,
        true,
      );
    }
  }
  throw lastError instanceof Error ? lastError : new ApiError("Unknown error", 0, true);
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export const api = {
  start: (sessionId: string, candidate: unknown, persona: string) =>
    request<InterviewReply>("/interview", {
      method: "POST",
      body: JSON.stringify({
        sessionId,
        candidate: candidate && typeof candidate === "object" ? { ...candidate, persona } : { persona },
      }),
    }),

  reply: (sessionId: string, message: string) =>
    request<InterviewReply>("/interview", {
      method: "POST",
      body: JSON.stringify({ sessionId, message }),
    }),

  roster: () => request<{ candidates: RosterEntry[] }>("/candidates", {}, { retries: 1 }),

  personas: () => request<{ personas: Persona[] }>("/personas", {}, { retries: 1 }),

  previewPlan: (candidate: unknown) =>
    request<PlanPreview>("/preview-plan", { method: "POST", body: JSON.stringify({ candidate }) }, { retries: 1 }),

  session: (sessionId: string) =>
    request<{
      state: SessionState;
      transcript: {
        role: string;
        text: string;
        day: number | null;
        action: string | null;
        difficulty: number | null;
        trace: Record<string, unknown> | null;
      }[];
      done: boolean;
      feedback: Feedback | null;
      report: Report | null;
    }>(`/session/${encodeURIComponent(sessionId)}`, {}, { retries: 0 }),

  cohort: () => request<CohortInsights>("/cohort/insights", {}, { retries: 1 }),

  health: () =>
    request<{ status: string; llm: { primary: string; live: boolean; chain: string[] } }>(
      "/health",
      {},
      { retries: 1 },
    ),
};
