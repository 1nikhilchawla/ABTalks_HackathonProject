import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { Persona, PlanPreview, RosterEntry } from "../lib/types";
import {
  Badge,
  Button,
  ErrorBanner,
  KIND_LABEL,
  Panel,
  SIGNAL_TONE,
  SectionTitle,
  Skeleton,
  cx,
} from "./ui";

export function Setup({
  onStart,
  starting,
  startError,
}: {
  onStart: (candidate: unknown, persona: string, label: string) => void;
  starting: boolean;
  startError: string | null;
}) {
  const [roster, setRoster] = useState<RosterEntry[] | null>(null);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [persona, setPersona] = useState("principal");
  const [preview, setPreview] = useState<PlanPreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [live, setLive] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [r, p, h] = await Promise.all([api.roster(), api.personas(), api.health()]);
        if (cancelled) return;
        setRoster(r.candidates);
        setPersonas(p.personas);
        setLive(h.llm.live);
        setSelectedId(r.candidates[0]?.id ?? null);
      } catch (error) {
        if (!cancelled) {
          setLoadError(error instanceof ApiError ? error.message : "Couldn't load the roster.");
          setRoster([]);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const selected = useMemo(
    () => roster?.find((c) => c.id === selectedId) ?? null,
    [roster, selectedId],
  );

  useEffect(() => {
    if (!selected) {
      setPreview(null);
      return;
    }
    let cancelled = false;
    setPreviewing(true);
    api
      .previewPlan(selected.raw)
      .then((p) => !cancelled && setPreview(p))
      .catch(() => !cancelled && setPreview(null))
      .finally(() => !cancelled && setPreviewing(false));
    return () => {
      cancelled = true;
    };
  }, [selected]);

  const firstTryRate = selected
    ? Math.round(
        (selected.signals.missionsFirstTry / Math.max(selected.signals.missionsCompleted, 1)) * 100,
      )
    : 0;

  return (
    <div className="mx-auto w-full max-w-6xl px-5 py-10 sm:px-8">
      <header className="mb-9 animate-rise">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <Badge tone="accent">Adaptive interview engine</Badge>
          {live === false && (
            <Badge
              tone="neutral"
              title="Running entirely offline: no API key, no network calls. Questions are composed from curriculum objectives and scores are rule-derived."
            >
              offline rubric engine
            </Badge>
          )}
        </div>
        <h1 className="text-[26px] font-semibold tracking-[-0.02em] sm:text-[32px]">
          Interviews built from what the candidate actually did.
        </h1>
        <p className="mt-2 max-w-2xl text-[15px] leading-relaxed" style={{ color: "var(--text-dim)" }}>
          CohortIQ reads a learner's 31-day cohort record — which missions they passed first try,
          which took four attempts, which they skipped — and turns it into a question plan. Every
          question can tell you which line of their record it came from.
        </p>
      </header>

      {loadError && (
        <div className="mb-5">
          <ErrorBanner message={loadError} onRetry={() => location.reload()} />
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_400px]">
        {/* ---------------- candidate picker ---------------- */}
        <section className="animate-rise" style={{ animationDelay: "40ms" }}>
          <div className="mb-3">
            <SectionTitle hint={roster ? `${roster.length} profiles` : undefined}>
              Choose a cohort graduate
            </SectionTitle>
          </div>

          {!roster && (
            <div className="grid gap-2.5 sm:grid-cols-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-[86px] w-full rounded-xl" />
              ))}
            </div>
          )}

          {roster && roster.length > 0 && (
            <div className="grid max-h-[430px] gap-2.5 overflow-y-auto pr-1 sm:grid-cols-2">
              {roster.map((c) => {
                const rate = Math.round(
                  (c.signals.missionsFirstTry / Math.max(c.signals.missionsCompleted, 1)) * 100,
                );
                const isSelected = c.id === selectedId;
                return (
                  <button
                    key={c.id}
                    onClick={() => setSelectedId(c.id)}
                    className={cx(
                      "rounded-xl p-3 text-left transition-all duration-150",
                      isSelected ? "ring-1" : "hover:brightness-[1.06]",
                    )}
                    style={{
                      background: isSelected ? "var(--accent-dim)" : "var(--panel)",
                      border: `1px solid ${isSelected ? "var(--accent)" : "var(--line)"}`,
                      // @ts-expect-error CSS custom property
                      "--tw-ring-color": "var(--accent)",
                    }}
                  >
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="truncate text-[13.5px] font-medium">{c.name}</span>
                      <span className="tnum shrink-0 text-[11px]" style={{ color: "var(--text-faint)" }}>
                        {c.years}y
                      </span>
                    </div>
                    <div className="mt-0.5 truncate text-[12px]" style={{ color: "var(--text-dim)" }}>
                      {c.role}
                    </div>
                    <div className="mt-2 flex items-center gap-1.5">
                      <Badge tone={rate >= 70 ? "strong" : rate >= 35 ? "mid" : "weak"}>
                        {rate}% first try
                      </Badge>
                      <Badge>{c.signals.commitDays}d active</Badge>
                    </div>
                  </button>
                );
              })}
            </div>
          )}

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button variant="ghost" onClick={() => setSelectedId(null)}>
              Interview without a profile
            </Button>
            <span className="text-[12px]" style={{ color: "var(--text-faint)" }}>
              Tests the cold-start path — the engine falls back to the curriculum spine.
            </span>
          </div>

          <div className="mt-7">
            <SectionTitle>Interviewer style</SectionTitle>
            <div className="mt-3 flex flex-wrap gap-2">
              {personas.map((p) => (
                <button
                  key={p.id}
                  onClick={() => setPersona(p.id)}
                  title={p.style}
                  className="rounded-lg px-3 py-1.5 text-[12.5px] font-medium transition-all duration-150"
                  style={{
                    background: persona === p.id ? "var(--accent-dim)" : "var(--panel)",
                    color: persona === p.id ? "var(--accent)" : "var(--text-dim)",
                    border: `1px solid ${persona === p.id ? "var(--accent)" : "var(--line)"}`,
                  }}
                >
                  {p.label}
                </button>
              ))}
            </div>
            <p className="mt-2 text-[12px] leading-relaxed" style={{ color: "var(--text-faint)" }}>
              Style changes tone only. The scoring rubric is identical across all five, so results
              stay comparable.
            </p>
          </div>
        </section>

        {/* ---------------- plan preview ---------------- */}
        <Panel className="h-fit p-5 animate-rise" as="aside">
          <SectionTitle hint={preview ? `${preview.plan.length} topics` : undefined}>
            The plan, before a single question
          </SectionTitle>

          {!selected && (
            <div className="mt-4">
              <p className="text-[13px] leading-relaxed" style={{ color: "var(--text-dim)" }}>
                No profile selected. The interview will cover the core curriculum spine — embeddings,
                retrieval, RAG, prompting, agents, MCP, security — and calibrate difficulty from your
                answers instead of your record.
              </p>
            </div>
          )}

          {selected && previewing && (
            <div className="mt-4 space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-11 w-full" />
              ))}
            </div>
          )}

          {selected && preview && !previewing && (
            <>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {preview.candidate.firstTryDays.length > 0 && (
                  <Badge tone="strong">{preview.candidate.firstTryDays.length} first-try days</Badge>
                )}
                {preview.candidate.struggleDays.length > 0 && (
                  <Badge tone="mid">{preview.candidate.struggleDays.length} high-attempt days</Badge>
                )}
                {preview.candidate.failedDays.length > 0 && (
                  <Badge tone="weak">{preview.candidate.failedDays.length} failed</Badge>
                )}
                {preview.candidate.skippedDays.length > 0 && (
                  <Badge tone="weak">{preview.candidate.skippedDays.length} skipped</Badge>
                )}
                <Badge>{firstTryRate}% first-try rate</Badge>
              </div>

              <ol className="mt-4 space-y-1.5">
                {preview.plan.map((slot, i) => (
                  <li
                    key={slot.slotId}
                    className="rounded-lg px-2.5 py-2 animate-rise"
                    style={{ background: "var(--panel-2)", animationDelay: `${i * 30}ms` }}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-[12.5px] font-medium">
                        <span className="tnum" style={{ color: "var(--text-faint)" }}>
                          D{slot.day}
                        </span>{" "}
                        {slot.title}
                      </span>
                      <Badge tone="neutral">{KIND_LABEL[slot.kind] ?? slot.kind}</Badge>
                    </div>
                    <div className="mt-1 flex items-center gap-1.5">
                      <Badge tone={SIGNAL_TONE[slot.signalCode] ?? "neutral"}>{slot.signal}</Badge>
                      <span className="text-[11px]" style={{ color: "var(--text-faint)" }}>
                        difficulty {slot.difficulty}/5
                      </span>
                    </div>
                  </li>
                ))}
              </ol>
            </>
          )}

          {startError && (
            <div className="mt-4">
              <ErrorBanner message={startError} />
            </div>
          )}

          <Button
            className="mt-5 w-full"
            disabled={starting || (!!selectedId && !preview)}
            onClick={() =>
              onStart(selected?.raw ?? null, persona, selected?.name ?? "Unprofiled candidate")
            }
          >
            {starting ? "Preparing the interview…" : "Start interview"}
          </Button>
          <p className="mt-2 text-center text-[11.5px]" style={{ color: "var(--text-faint)" }}>
            8–14 questions · at least 4 curriculum days · ~10 minutes
          </p>
        </Panel>
      </div>
    </div>
  );
}
