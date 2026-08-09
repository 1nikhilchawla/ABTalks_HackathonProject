import { useEffect, useState } from "react";
import type { SessionState } from "../lib/types";
import { Badge, Button, KIND_LABEL, SIGNAL_TONE } from "./ui";

/**
 * The plan, shown once, full-screen, before the first question.
 *
 * The evidence-linked plan is the product's whole thesis, and as a sidebar it
 * competes with the conversation for attention. Everyone sees it exactly once,
 * at the only moment when nothing else is happening, then it collapses to the
 * rail for the rest of the interview.
 */
export function PlanReveal({
  state,
  onContinue,
}: {
  state: SessionState;
  onContinue: () => void;
}) {
  const [revealed, setRevealed] = useState(0);

  useEffect(() => {
    if (revealed >= state.plan.length) return;
    const timer = window.setTimeout(() => setRevealed((n) => n + 1), revealed === 0 ? 260 : 110);
    return () => window.clearTimeout(timer);
  }, [revealed, state.plan.length]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Enter" || e.key === " " || e.key === "Escape") onContinue();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onContinue]);

  const days = [...new Set(state.plan.map((s) => s.day))].sort((a, b) => a - b);

  return (
    <div className="mx-auto w-full max-w-3xl px-5 py-10 sm:px-8">
      <div className="animate-rise">
        <Badge tone="accent">Before a single question</Badge>
        <h1 className="mt-3 text-[24px] font-semibold tracking-[-0.02em] sm:text-[28px]">
          {state.candidate.isPlaceholder
            ? "No record supplied — here's the plan anyway"
            : `Here's what I'm going to ask ${state.candidate.name.split(" ")[0]}, and why`}
        </h1>
        <p className="mt-2 text-[14.5px] leading-relaxed" style={{ color: "var(--text-dim)" }}>
          {state.candidate.isPlaceholder ? (
            <>
              Without a cohort record the interview covers the curriculum spine and calibrates from
              answers instead. Everything else works the same.
            </>
          ) : (
            <>
              Built from their cohort record — {state.plan.length} topics across days{" "}
              {days.join(", ")}. Each row names the line of the record that earned it a slot.
            </>
          )}
        </p>
      </div>

      <ol className="mt-6 space-y-2">
        {state.plan.map((slot, i) => (
          <li
            key={slot.slotId}
            className="rounded-xl px-4 py-3 transition-all duration-300"
            style={{
              background: "var(--panel)",
              border: "1px solid var(--line)",
              boxShadow: "var(--shadow)",
              opacity: i < revealed ? 1 : 0,
              transform: i < revealed ? "none" : "translateY(8px)",
            }}
          >
            <div className="flex items-center justify-between gap-3">
              <span className="flex min-w-0 items-baseline gap-2">
                <span
                  className="tnum shrink-0 rounded-md px-1.5 py-0.5 text-[11px] font-semibold"
                  style={{ background: "var(--accent-dim)", color: "var(--accent)" }}
                >
                  Day {slot.day}
                </span>
                <span className="truncate text-[14px] font-medium">{slot.title}</span>
              </span>
              <span className="flex shrink-0 items-center gap-2">
                <Badge>{KIND_LABEL[slot.kind] ?? slot.kind}</Badge>
                <span className="tnum text-[12px] font-semibold" style={{ color: "var(--accent)" }}>
                  {slot.difficulty}/5
                </span>
              </span>
            </div>
            <div className="mt-1.5 flex items-center gap-2">
              <span className="text-[11.5px]" style={{ color: "var(--text-faint)" }}>
                because the record says they
              </span>
              <Badge tone={SIGNAL_TONE[slot.signalCode] ?? "neutral"}>{slot.signal}</Badge>
            </div>
          </li>
        ))}
      </ol>

      <div className="mt-7 flex items-center gap-3">
        <Button onClick={onContinue}>Start the interview</Button>
        <span className="text-[12px]" style={{ color: "var(--text-faint)" }}>
          The plan stays visible in the sidebar and updates as topics open and close.
        </span>
      </div>
    </div>
  );
}
