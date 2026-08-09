import type { SessionState, Trace } from "../lib/types";
import { Sparkline } from "./charts";
import {
  Badge,
  DIMENSION_LABEL,
  Difficulty,
  FLAG_LABEL,
  KIND_LABEL,
  Meter,
  Panel,
  SIGNAL_TONE,
  SectionTitle,
  scoreColor,
} from "./ui";

/** Live interview instrumentation. Everything here is real state, not decoration. */
export function Rail({ state, trace }: { state: SessionState | null; trace: Trace | null }) {
  if (!state) return null;

  const coverageDays = state.daysCovered.length;
  const questionPct = Math.min(100, (state.questionsAsked / state.minQuestions) * 100);
  const dayPct = Math.min(100, (coverageDays / state.minDays) * 100);
  const evaluation = trace?.evaluation;

  return (
    <div className="flex flex-col gap-3">
      {/* progress ------------------------------------------------------- */}
      <Panel className="p-4">
        <SectionTitle hint={state.stage.toLowerCase()}>Progress</SectionTitle>
        <div className="mt-3 space-y-3">
          <div>
            <div className="mb-1 flex items-baseline justify-between">
              <span className="text-[12px]" style={{ color: "var(--text-dim)" }}>
                Questions
              </span>
              <span className="tnum text-[12px] font-medium">
                {state.questionsAsked}
                <span style={{ color: "var(--text-faint)" }}> / {state.minQuestions} min</span>
              </span>
            </div>
            <Meter value={questionPct} color="var(--accent)" />
          </div>
          <div>
            <div className="mb-1 flex items-baseline justify-between">
              <span className="text-[12px]" style={{ color: "var(--text-dim)" }}>
                Curriculum days
              </span>
              <span className="tnum text-[12px] font-medium">
                {coverageDays}
                <span style={{ color: "var(--text-faint)" }}> / {state.minDays} min</span>
              </span>
            </div>
            <Meter value={dayPct} color="var(--accent)" />
          </div>
          <div className="flex items-center justify-between pt-0.5">
            <span className="text-[12px]" style={{ color: "var(--text-dim)" }}>
              Difficulty
            </span>
            <Difficulty level={state.difficulty} />
          </div>
        </div>

        {state.scores.length > 1 && (
          <div className="mt-4">
            <SectionTitle hint="per answer">Score trajectory</SectionTitle>
            <div className="mt-1.5">
              <Sparkline points={state.scores} />
            </div>
          </div>
        )}
      </Panel>

      {/* last evaluation ------------------------------------------------ */}
      {evaluation && (
        <Panel className="p-4 animate-rise">
          <SectionTitle hint={evaluation.source === "heuristic" ? "offline rubric" : evaluation.source}>
            Last answer
          </SectionTitle>
          <div className="mt-2.5 flex items-center gap-2">
            <span className="tnum text-[26px] font-semibold leading-none" style={{ color: scoreColor(evaluation.composite) }}>
              {evaluation.composite}
            </span>
            <Badge
              tone={
                evaluation.verdict === "strong"
                  ? "strong"
                  : evaluation.verdict === "adequate"
                    ? "mid"
                    : "weak"
              }
            >
              {evaluation.verdict.replace("_", " ")}
            </Badge>
          </div>

          <div className="mt-3 space-y-1.5">
            {Object.entries(evaluation.dimensions).map(([key, value]) => (
              <div key={key} className="grid grid-cols-[1fr_28px] items-center gap-2">
                <div>
                  <div className="mb-[3px] text-[11px]" style={{ color: "var(--text-dim)" }}>
                    {DIMENSION_LABEL[key] ?? key}
                  </div>
                  <Meter value={value} height={4} />
                </div>
                <span className="tnum text-right text-[11px]" style={{ color: scoreColor(value) }}>
                  {value}
                </span>
              </div>
            ))}
          </div>

          {evaluation.flags.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1">
              {evaluation.flags.map((flag) => (
                <Badge key={flag} tone="weak">
                  {FLAG_LABEL[flag] ?? flag.replace(/_/g, " ")}
                </Badge>
              ))}
            </div>
          )}

          {evaluation.rationale && (
            <p className="mt-3 text-[12px] leading-relaxed" style={{ color: "var(--text-dim)" }}>
              {evaluation.rationale}
            </p>
          )}
        </Panel>
      )}

      {/* plan ----------------------------------------------------------- */}
      <Panel className="p-4">
        <SectionTitle hint={`${state.plan.filter((s) => s.questionsAsked > 0).length}/${state.plan.length}`}>
          Interview plan
        </SectionTitle>
        <ol className="mt-2.5 space-y-1">
          {state.plan.map((slot) => {
            const done = slot.questionsAsked > 0 && !slot.active;
            return (
              <li
                key={slot.slotId}
                className="rounded-lg px-2 py-1.5 transition-colors duration-200"
                style={{
                  background: slot.active ? "var(--accent-dim)" : "transparent",
                  border: `1px solid ${slot.active ? "var(--accent)" : "transparent"}`,
                  opacity: done ? 0.55 : 1,
                }}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="flex min-w-0 items-center gap-1.5">
                    <span
                      className="h-1.5 w-1.5 shrink-0 rounded-full"
                      style={{
                        background: slot.active
                          ? "var(--accent)"
                          : done
                            ? "var(--strong)"
                            : "var(--line)",
                      }}
                    />
                    <span className="truncate text-[12px]">
                      <span className="tnum" style={{ color: "var(--text-faint)" }}>
                        D{slot.day}
                      </span>{" "}
                      {slot.title}
                    </span>
                  </span>
                  <span className="shrink-0 text-[10.5px]" style={{ color: "var(--text-faint)" }}>
                    {KIND_LABEL[slot.kind] ?? slot.kind}
                  </span>
                </div>
                {slot.active && (
                  <div className="mt-1 pl-3">
                    <Badge tone={SIGNAL_TONE[slot.signalCode] ?? "neutral"}>{slot.signal}</Badge>
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      </Panel>

      {/* claim ledger --------------------------------------------------- */}
      {state.claims.length > 0 && (
        <Panel className="p-4">
          <SectionTitle hint={`${state.claims.length}`}>Claim ledger</SectionTitle>
          <p className="mt-1.5 text-[11.5px] leading-relaxed" style={{ color: "var(--text-faint)" }}>
            Statements the candidate made about their own work, and whether they held up.
          </p>
          <ul className="mt-2.5 space-y-2">
            {state.claims.slice(-6).map((claim, i) => (
              <li key={i} className="text-[12px] leading-relaxed">
                <Badge
                  tone={
                    claim.status === "SUBSTANTIATED"
                      ? "strong"
                      : claim.status === "CONTRADICTED" || claim.status === "UNSUPPORTED"
                        ? "weak"
                        : claim.status === "PROBED"
                          ? "accent"
                          : "neutral"
                  }
                >
                  {claim.status.toLowerCase()}
                </Badge>
                <span className="ml-1.5" style={{ color: "var(--text-dim)" }}>
                  {claim.text.length > 110 ? `${claim.text.slice(0, 110)}…` : claim.text}
                </span>
              </li>
            ))}
          </ul>
        </Panel>
      )}

      {/* engine status -------------------------------------------------- */}
      {trace && (
        <Panel className="p-4">
          <SectionTitle>Engine</SectionTitle>
          <dl className="mt-2.5 space-y-1.5 text-[11.5px]">
            <Row label="Provider" value={trace.provider.primary} />
            <Row label="Model calls" value={String(trace.usage.calls)} />
            {trace.usage.inputTokens > 0 && (
              <Row
                label="Tokens"
                value={`${trace.usage.inputTokens.toLocaleString()} in / ${trace.usage.outputTokens.toLocaleString()} out`}
              />
            )}
            <Row label="Avg latency" value={`${trace.usage.avgLatencyMs} ms`} />
            {trace.usage.fallbacks > 0 && <Row label="Fallbacks" value={String(trace.usage.fallbacks)} tone="mid" />}
            {trace.injectionAttempts > 0 && (
              <Row label="Injection attempts blocked" value={String(trace.injectionAttempts)} tone="weak" />
            )}
          </dl>
          {!trace.provider.live && (
            <p className="mt-2.5 text-[11.5px] leading-relaxed" style={{ color: "var(--text-dim)" }}>
              Running on the offline rubric engine — no API key, no network. Questions are composed
              from curriculum objectives and scores are rule-derived, both tagged as such.
            </p>
          )}
        </Panel>
      )}
    </div>
  );
}

function Row({ label, value, tone }: { label: string; value: string; tone?: "mid" | "weak" }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt style={{ color: "var(--text-faint)" }}>{label}</dt>
      <dd
        className="tnum font-medium"
        style={{ color: tone === "weak" ? "var(--weak)" : tone === "mid" ? "var(--mid)" : "var(--text-dim)" }}
      >
        {value}
      </dd>
    </div>
  );
}
