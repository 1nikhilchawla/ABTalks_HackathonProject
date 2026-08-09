import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import type { PlanPreview, RosterEntry } from "../lib/types";
import { Badge, Button, KIND_LABEL, Panel, SIGNAL_TONE, SectionTitle, Skeleton, cx } from "./ui";

/**
 * Side-by-side plan comparison.
 *
 * The fastest possible proof that the interview is derived from the learning
 * record: two candidates, same engine, same persona, structurally different
 * plans — before a single question is asked. Nothing here is generated; both
 * columns come from the same planner the interview uses.
 */
export function Compare({
  onStartInterview,
  onBack,
}: {
  onStartInterview: (candidate: unknown) => void;
  onBack: () => void;
}) {
  const [roster, setRoster] = useState<RosterEntry[] | null>(null);
  const [leftId, setLeftId] = useState<string | null>(null);
  const [rightId, setRightId] = useState<string | null>(null);
  const [left, setLeft] = useState<PlanPreview | null>(null);
  const [right, setRight] = useState<PlanPreview | null>(null);

  useEffect(() => {
    api.roster().then(({ candidates }) => {
      setRoster(candidates);
      const rate = (c: RosterEntry) =>
        c.signals.missionsFirstTry / Math.max(c.signals.missionsCompleted, 1);
      const sorted = [...candidates].sort((a, b) => rate(b) - rate(a));
      setLeftId(sorted[0]?.id ?? null);
      setRightId(sorted[sorted.length - 1]?.id ?? null);
    });
  }, []);

  const pick = (id: string | null) => roster?.find((c) => c.id === id) ?? null;
  const leftCandidate = useMemo(() => pick(leftId), [roster, leftId]);
  const rightCandidate = useMemo(() => pick(rightId), [roster, rightId]);

  useEffect(() => {
    if (leftCandidate) api.previewPlan(leftCandidate.raw).then(setLeft).catch(() => setLeft(null));
  }, [leftCandidate]);
  useEffect(() => {
    if (rightCandidate) api.previewPlan(rightCandidate.raw).then(setRight).catch(() => setRight(null));
  }, [rightCandidate]);

  const sharedDays = useMemo(() => {
    if (!left || !right) return new Set<number>();
    const r = new Set(right.plan.map((s) => s.day));
    return new Set(left.plan.filter((s) => r.has(s.day)).map((s) => s.day));
  }, [left, right]);

  const avg = (p: PlanPreview | null) =>
    p && p.plan.length
      ? (p.plan.reduce((sum, s) => sum + s.difficulty, 0) / p.plan.length).toFixed(1)
      : "—";

  return (
    <div className="mx-auto w-full max-w-6xl px-5 py-9 sm:px-8">
      <header className="mb-7 animate-rise">
        <Badge tone="accent">Same engine · same persona · same curriculum</Badge>
        <h1 className="mt-3 text-[26px] font-semibold tracking-[-0.02em]">
          Two learning records, two different interviews.
        </h1>
        <p className="mt-2 max-w-2xl text-[14.5px] leading-relaxed" style={{ color: "var(--text-dim)" }}>
          Nothing below is generated. Both columns come from the same planner the live interview
          uses — the difference is entirely in what each candidate's cohort record says.
        </p>
      </header>

      <div className="grid gap-5 md:grid-cols-2">
        {[
          { side: "left" as const, id: leftId, setId: setLeftId, preview: left, candidate: leftCandidate },
          { side: "right" as const, id: rightId, setId: setRightId, preview: right, candidate: rightCandidate },
        ].map(({ side, id, setId, preview, candidate }) => (
          <Panel key={side} className="p-5 animate-rise">
            <select
              value={id ?? ""}
              onChange={(e) => setId(e.target.value)}
              className="mb-3 w-full rounded-lg px-2.5 py-2 text-[13.5px] font-medium outline-none"
              style={{ background: "var(--panel-2)", border: "1px solid var(--line)", color: "var(--text)" }}
            >
              {(roster ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} — {c.role}
                </option>
              ))}
            </select>

            {!preview && (
              <div className="space-y-2">
                {Array.from({ length: 7 }).map((_, i) => (
                  <Skeleton key={i} className="h-12 w-full" />
                ))}
              </div>
            )}

            {preview && (
              <>
                <div className="mb-3 flex flex-wrap gap-1.5">
                  <Badge tone={preview.candidate.firstTryRate >= 0.7 ? "strong" : preview.candidate.firstTryRate >= 0.35 ? "mid" : "weak"}>
                    {Math.round(preview.candidate.firstTryRate * 100)}% first try
                  </Badge>
                  {preview.candidate.failedDays.length > 0 && (
                    <Badge tone="weak">{preview.candidate.failedDays.length} failed</Badge>
                  )}
                  {preview.candidate.skippedDays.length > 0 && (
                    <Badge tone="weak">{preview.candidate.skippedDays.length} skipped</Badge>
                  )}
                  <Badge>avg difficulty {avg(preview)}/5</Badge>
                </div>

                <ol className="space-y-1.5">
                  {preview.plan.map((slot, i) => {
                    const unique = !sharedDays.has(slot.day);
                    return (
                      <li
                        key={slot.slotId}
                        className={cx("rounded-lg px-2.5 py-2 animate-rise")}
                        style={{
                          background: unique ? "var(--accent-dim)" : "var(--panel-2)",
                          border: `1px solid ${unique ? "var(--accent)" : "transparent"}`,
                          animationDelay: `${i * 35}ms`,
                        }}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate text-[12.5px] font-medium">
                            <span className="tnum" style={{ color: "var(--text-faint)" }}>
                              D{slot.day}
                            </span>{" "}
                            {slot.title}
                          </span>
                          <span className="flex shrink-0 items-center gap-1.5">
                            <Badge>{KIND_LABEL[slot.kind] ?? slot.kind}</Badge>
                            <span className="tnum text-[11px] font-semibold" style={{ color: "var(--accent)" }}>
                              {slot.difficulty}/5
                            </span>
                          </span>
                        </div>
                        <div className="mt-1">
                          <Badge tone={SIGNAL_TONE[slot.signalCode] ?? "neutral"}>{slot.signal}</Badge>
                        </div>
                      </li>
                    );
                  })}
                </ol>

                <Button
                  variant="ghost"
                  className="mt-4 w-full"
                  onClick={() => candidate && onStartInterview(candidate.raw)}
                >
                  Interview {candidate?.name.split(" ")[0]}
                </Button>
              </>
            )}
          </Panel>
        ))}
      </div>

      <Panel className="mt-5 p-4 animate-rise">
        <SectionTitle>How to read this</SectionTitle>
        <p className="mt-2 text-[13px] leading-relaxed" style={{ color: "var(--text-dim)" }}>
          Highlighted rows are topics only <em>that</em> candidate gets. A first-try pass earns a{" "}
          <strong>harder</strong> question, not an easier one — the record says they own that ground.
          A mission passed on the fourth attempt becomes a low-difficulty probe, because the useful
          question there is whether they understood it or brute-forced it. Skipped missions become
          honest gap checks.
        </p>
      </Panel>

      <div className="mt-5">
        <Button variant="quiet" onClick={onBack}>
          ← Back to setup
        </Button>
      </div>
    </div>
  );
}
