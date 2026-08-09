import { useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { CohortInsights } from "../lib/types";
import {
  Badge,
  Button,
  EmptyState,
  ErrorBanner,
  FLAG_LABEL,
  Meter,
  Panel,
  SectionTitle,
  Skeleton,
  scoreColor,
} from "./ui";

/**
 * The staff-facing view.
 *
 * An individual report helps one learner. This answers the question the people
 * running a cohort actually have: which curriculum days can nobody defend?
 * Every number here is aggregated in Python from finished interviews — no model
 * call, nothing generated.
 */
export function Cohort({ onBack }: { onBack: () => void }) {
  const [data, setData] = useState<CohortInsights | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setError(null);
    api
      .cohort()
      .then(setData)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Couldn't load cohort insights."));
  };

  useEffect(load, []);

  return (
    <div className="mx-auto w-full max-w-5xl px-5 py-9 sm:px-8">
      <header className="mb-6 animate-rise">
        <Badge tone="accent">Computed, not generated</Badge>
        <h1 className="mt-3 text-[26px] font-semibold tracking-[-0.02em]">
          Which curriculum days the cohort can't defend
        </h1>
        <p className="mt-2 max-w-2xl text-[14.5px] leading-relaxed" style={{ color: "var(--text-dim)" }}>
          Aggregated from finished interviews. A day appears here because people scored badly on it
          under questioning — not because a model decided it looked weak.
        </p>
      </header>

      {error && <ErrorBanner message={error} onRetry={load} />}

      {!data && !error && (
        <div className="grid gap-4 sm:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-24 w-full rounded-xl" />
          ))}
        </div>
      )}

      {data && data.interviews === 0 && (
        <Panel>
          <EmptyState
            title="No finished interviews yet"
            body="Run an interview through to the report and this view fills in. It needs at least two interviews covering the same day before it ranks anything."
            action={<Button onClick={onBack}>Run an interview</Button>}
          />
        </Panel>
      )}

      {data && data.interviews > 0 && (
        <>
          <div className="grid gap-3 sm:grid-cols-4">
            <Stat label="Interviews" value={String(data.interviews)} />
            <Stat label="Mean readiness" value={`${data.meanOverall}`} tone={scoreColor(data.meanOverall)} />
            <Stat label="Days covered" value={String(data.daysCovered)} />
            <Stat
              label="Injection attempts"
              value={String(data.injectionAttempts)}
              tone={data.injectionAttempts ? "var(--weak)" : undefined}
            />
          </div>

          <Panel className="mt-5 p-5 animate-rise">
            <SectionTitle hint={`min ${data.minSamplesForRanking} interviews to rank`}>
              Weakest days
            </SectionTitle>
            {data.weakestDays.length === 0 ? (
              <p className="mt-3 text-[13px]" style={{ color: "var(--text-dim)" }}>
                Not enough overlapping interviews yet — run a couple more and the ranking appears.
              </p>
            ) : (
              <ul className="mt-3 space-y-4">
                {data.weakestDays.map((day) => (
                  <li key={day.day}>
                    <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
                      <span className="text-[13.5px] font-medium">
                        <span className="tnum" style={{ color: "var(--text-faint)" }}>
                          Day {day.day}
                        </span>{" "}
                        {day.title}
                      </span>
                      <span className="flex items-center gap-2">
                        <span className="text-[11.5px]" style={{ color: "var(--text-faint)" }}>
                          {day.belowBar}/{day.interviews} below the bar
                        </span>
                        <span
                          className="tnum text-[14px] font-semibold"
                          style={{ color: scoreColor(day.meanScore) }}
                        >
                          {day.meanScore}
                        </span>
                      </span>
                    </div>
                    <Meter value={day.meanScore} height={5} />
                    {day.weakestQuote && (
                      <blockquote
                        className="mt-2 rounded-lg px-3 py-2 text-[12.5px] leading-relaxed"
                        style={{ background: "var(--panel-2)", color: "var(--text-dim)" }}
                      >
                        “{day.weakestQuote}”
                        <span className="ml-1" style={{ color: "var(--text-faint)" }}>
                          — {day.weakestCandidate}
                        </span>
                      </blockquote>
                    )}
                    {day.commonFlags.length > 0 && (
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        {day.commonFlags.map((flag) => (
                          <Badge key={flag} tone="weak">
                            {FLAG_LABEL[flag] ?? flag.replace(/_/g, " ")}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <div className="mt-5 grid gap-5 sm:grid-cols-2">
            <Panel className="p-5 animate-rise">
              <SectionTitle>Every day interviewed</SectionTitle>
              <ul className="mt-3 space-y-2">
                {data.days.map((day) => (
                  <li key={day.day} className="grid grid-cols-[1fr_auto] items-center gap-3">
                    <div className="min-w-0">
                      <div className="mb-1 truncate text-[12.5px]">
                        <span className="tnum" style={{ color: "var(--text-faint)" }}>
                          D{day.day}
                        </span>{" "}
                        {day.title}
                      </div>
                      <Meter value={day.meanScore} height={4} />
                    </div>
                    <span className="tnum text-[12px]" style={{ color: scoreColor(day.meanScore) }}>
                      {day.meanScore}
                      <span style={{ color: "var(--text-faint)" }}> ×{day.interviews}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </Panel>

            <div className="space-y-5">
              <Panel className="p-5 animate-rise">
                <SectionTitle>Learning-record mix</SectionTitle>
                <p className="mt-1.5 text-[11.5px] leading-relaxed" style={{ color: "var(--text-faint)" }}>
                  Which record signals produced the topics that got asked.
                </p>
                <ul className="mt-2.5 space-y-1.5">
                  {Object.entries(data.signalMix).map(([signal, count]) => (
                    <li key={signal} className="flex items-baseline justify-between text-[12.5px]">
                      <span style={{ color: "var(--text-dim)" }}>{signal.replace(/_/g, " ")}</span>
                      <span className="tnum font-medium">{count}</span>
                    </li>
                  ))}
                </ul>
              </Panel>

              <Panel className="p-5 animate-rise">
                <SectionTitle>Most common answer problems</SectionTitle>
                <ul className="mt-2.5 space-y-1.5">
                  {Object.entries(data.commonFlags).map(([flag, count]) => (
                    <li key={flag} className="flex items-baseline justify-between text-[12.5px]">
                      <span style={{ color: "var(--text-dim)" }}>
                        {FLAG_LABEL[flag] ?? flag.replace(/_/g, " ")}
                      </span>
                      <span className="tnum font-medium">{count}</span>
                    </li>
                  ))}
                  {Object.keys(data.commonFlags).length === 0 && (
                    <li className="text-[12.5px]" style={{ color: "var(--text-faint)" }}>
                      Nothing flagged yet.
                    </li>
                  )}
                </ul>
              </Panel>
            </div>
          </div>
        </>
      )}

      <div className="mt-6 flex gap-2">
        <Button variant="quiet" onClick={onBack}>
          ← Back to setup
        </Button>
        {data && data.interviews > 0 && (
          <Button variant="quiet" onClick={load}>
            Refresh
          </Button>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <Panel className="px-4 py-3">
      <div className="text-[11px] uppercase tracking-[0.12em]" style={{ color: "var(--text-faint)" }}>
        {label}
      </div>
      <div className="tnum mt-1 text-[22px] font-semibold" style={{ color: tone ?? "var(--text)" }}>
        {value}
      </div>
    </Panel>
  );
}
