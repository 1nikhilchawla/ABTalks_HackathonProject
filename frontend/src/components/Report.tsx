import { useState } from "react";
import type { Feedback, Report as ReportData } from "../lib/types";
import { RadarChart, ScoreRing } from "./charts";
import {
  Badge,
  Button,
  FLAG_LABEL,
  KIND_LABEL,
  Meter,
  Panel,
  SIGNAL_TONE,
  SectionTitle,
  cx,
  scoreColor,
} from "./ui";

export function Report({
  report,
  feedback,
  candidateName,
  onRestart,
}: {
  report: ReportData;
  feedback: Feedback;
  candidateName: string;
  onRestart: () => void;
}) {
  const [tab, setTab] = useState<"assessment" | "replay" | "evidence">("assessment");
  const [copied, setCopied] = useState(false);

  const copyJson = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify({ feedback, report }, null, 2));
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6">
      {/* ---------------- headline ---------------- */}
      <Panel className="p-6 animate-rise">
        <div className="flex flex-col gap-6 sm:flex-row sm:items-center">
          <div className="shrink-0">
            <ScoreRing score={report.overall} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="mb-1.5 flex flex-wrap items-center gap-2">
              <Badge tone={report.overall >= 72 ? "strong" : report.overall >= 52 ? "mid" : "weak"}>
                {report.readiness.label}
              </Badge>
              <Badge>{report.coverage.questionsAsked} questions</Badge>
              <Badge>{report.coverage.daysCovered.length} curriculum days</Badge>
              {report.degraded && <Badge tone="mid">generated in degraded mode</Badge>}
            </div>
            <h1 className="text-[22px] font-semibold tracking-[-0.01em]">
              {candidateName} — interview assessment
            </h1>
            <p className="mt-1.5 text-[14px] leading-relaxed" style={{ color: "var(--text-dim)" }}>
              {report.headline || report.readiness.note}
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <Button variant="ghost" onClick={copyJson}>
                {copied ? "Copied" : "Copy report JSON"}
              </Button>
              <Button variant="ghost" onClick={() => window.print()}>
                Print / save PDF
              </Button>
              <Button onClick={onRestart}>New interview</Button>
            </div>
          </div>
        </div>
      </Panel>

      {/* ---------------- tabs ---------------- */}
      <div className="mt-5 flex gap-1 border-b" style={{ borderColor: "var(--line)" }}>
        {(
          [
            ["assessment", "Assessment"],
            ["replay", `Replay (${report.timeline.length})`],
            ["evidence", "Evidence & grounding"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className="relative px-3 py-2 text-[13px] font-medium transition-colors duration-150"
            style={{ color: tab === key ? "var(--text)" : "var(--text-faint)" }}
          >
            {label}
            {tab === key && (
              <span className="absolute inset-x-2 -bottom-px h-[2px] rounded-full" style={{ background: "var(--accent)" }} />
            )}
          </button>
        ))}
      </div>

      {tab === "assessment" && <Assessment report={report} feedback={feedback} />}
      {tab === "replay" && <Replay report={report} />}
      {tab === "evidence" && <Evidence report={report} />}
    </div>
  );
}

/* ------------------------------------------------------------------ */
function Assessment({ report, feedback }: { report: ReportData; feedback: Feedback }) {
  const ranked = [...report.perTopic].sort((a, b) => b.score - a.score);

  return (
    <div className="mt-5 grid gap-5 lg:grid-cols-[320px_minmax(0,1fr)]">
      <div className="space-y-5">
        <Panel className="p-5 animate-rise">
          <SectionTitle hint="0–100">Rubric profile</SectionTitle>
          <div className="mt-1">
            <RadarChart dimensions={report.dimensions} />
          </div>
          <p className="mt-1 text-[11.5px] leading-relaxed" style={{ color: "var(--text-faint)" }}>
            Averaged across every scored answer. Six dimensions, not one number — a 78 in accuracy
            with a 41 in specificity is a very different candidate from a flat 60.
          </p>
        </Panel>

        <Panel className="p-5 animate-rise">
          <SectionTitle>Interview behaviour</SectionTitle>
          {report.behaviours.length > 0 ? (
            <ul className="mt-2.5 space-y-1.5">
              {report.behaviours.map((b) => (
                <li key={b} className="text-[12.5px] leading-relaxed" style={{ color: "var(--text-dim)" }}>
                  · {b}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-[12.5px]" style={{ color: "var(--text-faint)" }}>
              Nothing unusual — the candidate engaged with every question.
            </p>
          )}
        </Panel>
      </div>

      <div className="space-y-5">
        <Panel className="p-5 animate-rise">
          <SectionTitle>Summary</SectionTitle>
          <p className="mt-2 text-[14px] leading-[1.7]">{feedback.summary}</p>
        </Panel>

        <div className="grid gap-4 sm:grid-cols-2">
          <FeedbackList title="Strengths" items={feedback.strengths} tone="strong" />
          <FeedbackList title="Gaps" items={feedback.gaps} tone="weak" />
        </div>

        <Panel className="p-5 animate-rise">
          <SectionTitle>Preparation plan</SectionTitle>
          <ol className="mt-2.5 space-y-2.5">
            {feedback.next.map((item, i) => (
              <li key={item} className="flex gap-2.5 text-[13.5px] leading-relaxed">
                <span
                  className="tnum mt-[1px] flex h-5 w-5 shrink-0 items-center justify-center rounded-md text-[11px] font-semibold"
                  style={{ background: "var(--accent-dim)", color: "var(--accent)" }}
                >
                  {i + 1}
                </span>
                <span>{item}</span>
              </li>
            ))}
          </ol>
        </Panel>

        <Panel className="p-5 animate-rise">
          <SectionTitle hint={`${report.perTopic.length} scored`}>Topic breakdown</SectionTitle>
          <ul className="mt-3 space-y-3">
            {ranked.map((topic) => (
              <li key={topic.slotId}>
                <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-[13px] font-medium">
                    <span className="tnum" style={{ color: "var(--text-faint)" }}>
                      Day {topic.day}
                    </span>{" "}
                    {topic.topic}
                  </span>
                  <span className="tnum text-[13px] font-semibold" style={{ color: scoreColor(topic.score) }}>
                    {topic.score}
                  </span>
                </div>
                <Meter value={topic.score} height={5} />
                <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                  <Badge tone="neutral">{KIND_LABEL[topic.kind] ?? topic.kind}</Badge>
                  <Badge tone={SIGNAL_TONE[topic.signalCode] ?? "neutral"}>{topic.signal}</Badge>
                  <span className="text-[11px]" style={{ color: "var(--text-faint)" }}>
                    {topic.questions} question{topic.questions === 1 ? "" : "s"}
                  </span>
                  {topic.flags.map((flag) => (
                    <Badge key={flag} tone="weak">
                      {FLAG_LABEL[flag] ?? flag.replace(/_/g, " ")}
                    </Badge>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        </Panel>
      </div>
    </div>
  );
}

function FeedbackList({
  title,
  items,
  tone,
}: {
  title: string;
  items: string[];
  tone: "strong" | "weak";
}) {
  return (
    <Panel className="p-5 animate-rise">
      <SectionTitle>{title}</SectionTitle>
      <ul className="mt-2.5 space-y-2">
        {items.map((item) => (
          <li key={item} className="flex gap-2 text-[13px] leading-relaxed">
            <span
              className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full"
              style={{ background: tone === "strong" ? "var(--strong)" : "var(--weak)" }}
            />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

/* ------------------------------------------------------------------ */
function Replay({ report }: { report: ReportData }) {
  const [open, setOpen] = useState<number | null>(null);

  return (
    <div className="mt-5">
      <p className="mb-4 max-w-2xl text-[13px] leading-relaxed" style={{ color: "var(--text-dim)" }}>
        Every question, the decision that produced it, and how the answer landed. This is the same
        record the interviewer used while adapting — nothing is reconstructed after the fact.
      </p>

      <ol className="space-y-2">
        {report.timeline.map((entry, i) => {
          const expanded = open === i;
          const score = entry.score;
          return (
            <li key={entry.turn}>
              <button
                onClick={() => setOpen(expanded ? null : i)}
                className="w-full rounded-xl px-4 py-3 text-left transition-colors duration-150"
                style={{
                  background: expanded ? "var(--panel-2)" : "var(--panel)",
                  border: `1px solid ${expanded ? "var(--accent)" : "var(--line)"}`,
                }}
              >
                <div className="flex items-start gap-3">
                  <span
                    className="tnum mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-[11px] font-semibold"
                    style={{
                      background: score != null ? "color-mix(in srgb, currentColor 14%, transparent)" : "var(--panel-2)",
                      color: scoreColor(score),
                    }}
                  >
                    {i + 1}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-[13.5px] leading-relaxed">{entry.question}</p>
                    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                      {entry.day != null && <Badge>Day {entry.day}</Badge>}
                      {entry.action && (
                        <Badge tone="neutral">{entry.action.replace(/_/g, " ").toLowerCase()}</Badge>
                      )}
                      {entry.difficulty != null && <Badge>diff {entry.difficulty}/5</Badge>}
                      {entry.verdict && (
                        <Badge
                          tone={
                            entry.verdict === "strong"
                              ? "strong"
                              : entry.verdict === "adequate"
                                ? "mid"
                                : "weak"
                          }
                        >
                          {entry.verdict.replace("_", " ")} {score != null ? `· ${score}` : ""}
                        </Badge>
                      )}
                      {entry.utterance && entry.utterance !== "ANSWER" && (
                        <Badge tone="weak">{entry.utterance.replace(/_/g, " ").toLowerCase()}</Badge>
                      )}
                    </div>
                  </div>
                </div>
              </button>

              {expanded && (
                <Panel className="mt-1.5 p-4 animate-rise">
                  {entry.why && (
                    <div className="mb-3">
                      <SectionTitle>Why this question was asked</SectionTitle>
                      <p className="mt-1.5 text-[13px] leading-relaxed">{entry.why}</p>
                      {entry.reasonCode && (
                        <p className="mt-1 font-mono text-[11px]" style={{ color: "var(--text-faint)" }}>
                          {entry.reasonCode}
                        </p>
                      )}
                    </div>
                  )}
                  {entry.answer && (
                    <div className="mb-3">
                      <SectionTitle>Their answer</SectionTitle>
                      <p
                        className="mt-1.5 rounded-lg px-3 py-2 text-[13px] leading-relaxed whitespace-pre-wrap"
                        style={{ background: "var(--panel-2)", color: "var(--text-dim)" }}
                      >
                        {entry.answer}
                      </p>
                    </div>
                  )}
                  {entry.rationale && (
                    <div className="mb-3">
                      <SectionTitle>Assessment</SectionTitle>
                      <p className="mt-1.5 text-[13px] leading-relaxed">{entry.rationale}</p>
                    </div>
                  )}
                  {entry.dimensions && (
                    <div className="grid gap-x-5 gap-y-2 sm:grid-cols-2">
                      {Object.entries(entry.dimensions).map(([key, value]) => (
                        <div key={key} className="grid grid-cols-[1fr_26px] items-center gap-2">
                          <div>
                            <div className="mb-[3px] text-[11px]" style={{ color: "var(--text-dim)" }}>
                              {key.replace(/_/g, " ")}
                            </div>
                            <Meter value={value} height={4} />
                          </div>
                          <span className="tnum text-right text-[11px]" style={{ color: scoreColor(value) }}>
                            {value}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </Panel>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/* ------------------------------------------------------------------ */
function Evidence({ report }: { report: ReportData }) {
  return (
    <div className="mt-5 grid gap-5 lg:grid-cols-2">
      <Panel className="p-5 animate-rise">
        <SectionTitle hint={`${report.claims.length}`}>Claim ledger</SectionTitle>
        <p className="mt-1.5 text-[12px] leading-relaxed" style={{ color: "var(--text-faint)" }}>
          Every statement the candidate made about their own work, and what happened when it was
          probed. The assessment above may only draw on these.
        </p>
        {report.claims.length === 0 ? (
          <p className="mt-4 text-[13px]" style={{ color: "var(--text-dim)" }}>
            No first-person claims were recorded — usually a sign the answers stayed abstract.
          </p>
        ) : (
          <ul className="mt-3 space-y-2.5">
            {report.claims.map((claim, i) => (
              <li key={i} className="text-[12.5px] leading-relaxed">
                <div className="flex items-start gap-2">
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
                  <span style={{ color: "var(--text-dim)" }}>{claim.text}</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <div className="space-y-5">
        <Panel className="p-5 animate-rise">
          <SectionTitle>Coverage</SectionTitle>
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            {report.coverage.daysCovered.map((day) => (
              <Badge key={day} tone="accent">
                Day {day}
              </Badge>
            ))}
          </div>
          <ul className="mt-3 space-y-1">
            {report.coverage.modules.map((module) => (
              <li key={module} className="text-[12.5px]" style={{ color: "var(--text-dim)" }}>
                · {module}
              </li>
            ))}
          </ul>
        </Panel>

        <Panel className="p-5 animate-rise">
          <SectionTitle>Objectives not reached</SectionTitle>
          {report.missedObjectives.length === 0 ? (
            <p className="mt-2 text-[12.5px]" style={{ color: "var(--text-faint)" }}>
              The answers touched every objective that came up.
            </p>
          ) : (
            <ul className="mt-2.5 space-y-1.5">
              {report.missedObjectives.map((objective) => (
                <li key={objective} className="text-[12.5px] leading-relaxed" style={{ color: "var(--text-dim)" }}>
                  · {objective}
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel className={cx("p-5 animate-rise")}>
          <SectionTitle hint={report.generatedBy}>Grounding checks</SectionTitle>
          {report.groundingWarnings.length === 0 ? (
            <p className="mt-2 text-[12.5px] leading-relaxed" style={{ color: "var(--strong)" }}>
              Passed. Every technology named in this report appears in the transcript or the
              curriculum — nothing was invented.
            </p>
          ) : (
            <ul className="mt-2.5 space-y-1.5">
              {report.groundingWarnings.map((warning) => (
                <li key={warning} className="text-[12px] leading-relaxed" style={{ color: "var(--mid)" }}>
                  · {warning}
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  );
}
