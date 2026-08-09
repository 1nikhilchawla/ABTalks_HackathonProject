import { useEffect, useRef, useState } from "react";
import type { Msg, SessionState, Trace } from "../lib/types";
import { Composer } from "./Composer";
import { Rail } from "./Rail";
import { Badge, Button, ErrorBanner, Panel, TypingDots, cx } from "./ui";

export function Interview({
  messages,
  state,
  trace,
  busy,
  error,
  draft,
  onDraftChange,
  onSend,
  onRetry,
  onEndEarly,
  onRestart,
}: {
  messages: Msg[];
  state: SessionState | null;
  trace: Trace | null;
  busy: boolean;
  error: string | null;
  draft: string;
  onDraftChange: (v: string) => void;
  onSend: (text: string) => void;
  onRetry: () => void;
  onEndEarly: () => void;
  onRestart: () => void;
}) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const [confirmExit, setConfirmExit] = useState(false);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, busy]);

  return (
    <div className="mx-auto grid w-full max-w-6xl gap-5 px-4 py-5 sm:px-6 lg:grid-cols-[minmax(0,1fr)_306px]">
      {/* ---------------- conversation ---------------- */}
      <section className="flex min-h-[calc(100vh-120px)] flex-col">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2">
            <div
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-[12px] font-semibold"
              style={{ background: "var(--accent-dim)", color: "var(--accent)" }}
            >
              IQ
            </div>
            <div className="min-w-0">
              <div className="truncate text-[13px] font-medium">
                {state?.personaLabel ?? "Interviewer"}
              </div>
              <div className="truncate text-[11.5px]" style={{ color: "var(--text-faint)" }}>
                {trace?.currentTopic
                  ? `Day ${trace.currentTopic.day} · ${trace.currentTopic.title}`
                  : state?.candidate.name}
              </div>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {state?.degraded && (
              <Badge tone="mid" title="A provider call failed and the engine fell back. The interview continued.">
                degraded
              </Badge>
            )}
            {confirmExit ? (
              <div className="flex items-center gap-1.5">
                <span className="text-[12px]" style={{ color: "var(--text-dim)" }}>
                  End now?
                </span>
                <Button variant="danger" onClick={onEndEarly}>
                  Yes, wrap up
                </Button>
                <Button variant="quiet" onClick={() => setConfirmExit(false)}>
                  Cancel
                </Button>
              </div>
            ) : (
              <Button variant="quiet" onClick={() => setConfirmExit(true)}>
                End early
              </Button>
            )}
          </div>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto pb-4 pr-1">
          {messages.map((message, index) => (
            <Bubble key={message.id} message={message} isLast={index === messages.length - 1} />
          ))}

          {busy && (
            <div className="flex items-center gap-2 pl-1 animate-fade">
              <TypingDots />
              <span className="text-[12px]" style={{ color: "var(--text-faint)" }}>
                Reading your answer…
              </span>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <div className="space-y-2 pt-1">
          {error && <ErrorBanner message={error} onRetry={onRetry} />}
          {state?.done ? (
            <div className="flex items-center justify-between gap-3 rounded-xl px-4 py-3"
                 style={{ background: "var(--panel)", border: "1px solid var(--line)" }}>
              <span className="text-[13px]" style={{ color: "var(--text-dim)" }}>
                Interview complete — your assessment is below.
              </span>
              <Button variant="ghost" onClick={onRestart}>
                New interview
              </Button>
            </div>
          ) : (
            <Composer
              draft={draft}
              onDraftChange={onDraftChange}
              onSend={onSend}
              busy={busy}
              disabled={state?.done}
            />
          )}
        </div>
      </section>

      {/* ---------------- instrumentation rail ---------------- */}
      <aside className="hidden lg:block">
        <div className="sticky top-4 max-h-[calc(100vh-32px)] overflow-y-auto pr-1">
          <Rail state={state} trace={trace} />
        </div>
      </aside>
    </div>
  );
}

function Bubble({ message, isLast }: { message: Msg; isLast: boolean }) {
  const [showWhy, setShowWhy] = useState(false);
  const isInterviewer = message.role === "interviewer";
  const trace = isInterviewer ? message.trace : undefined;

  if (!isInterviewer) {
    return (
      <div className="flex justify-end animate-rise">
        <div
          className="max-w-[85%] rounded-2xl rounded-br-md px-3.5 py-2.5 text-[14.5px] leading-relaxed whitespace-pre-wrap"
          style={{ background: "var(--panel-2)", border: "1px solid var(--line)" }}
        >
          {message.text}
        </div>
      </div>
    );
  }

  return (
    <div className="animate-rise">
      <div className="flex gap-2.5">
        <div
          className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-[10.5px] font-semibold"
          style={{ background: "var(--accent-dim)", color: "var(--accent)" }}
        >
          IQ
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-[15px] leading-[1.65] whitespace-pre-wrap">{message.text}</p>

          {trace && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              {trace.currentTopic && (
                <Badge tone="neutral" title={trace.currentTopic.module}>
                  Day {trace.currentTopic.day}
                </Badge>
              )}
              <Badge tone="neutral">{trace.decision.intent.replace(/_/g, " ").toLowerCase()}</Badge>
              <Badge tone="neutral">difficulty {trace.decision.difficulty}/5</Badge>
              <button
                onClick={() => setShowWhy((v) => !v)}
                className={cx(
                  "rounded-md px-1.5 py-0.5 text-[11px] font-medium transition-colors duration-150",
                  showWhy && "brightness-125",
                )}
                style={{
                  color: "var(--accent)",
                  background: showWhy ? "var(--accent-dim)" : "transparent",
                  border: "1px solid var(--line)",
                }}
              >
                {showWhy ? "Hide reasoning" : "Why this question?"}
              </button>
            </div>
          )}

          {trace && showWhy && (
            <Panel className="mt-2 p-3 animate-rise">
              <p className="text-[12.5px] leading-relaxed">{trace.why}</p>

              {trace.currentTopic && trace.currentTopic.objectives.length > 0 && (
                <div className="mt-2.5">
                  <p className="text-[10.5px] font-semibold uppercase tracking-[0.12em]"
                     style={{ color: "var(--text-faint)" }}>
                    Curriculum objectives behind it
                  </p>
                  <ul className="mt-1 space-y-0.5">
                    {trace.currentTopic.objectives.map((objective) => (
                      <li key={objective} className="text-[12px] leading-relaxed"
                          style={{ color: "var(--text-dim)" }}>
                        · {objective}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="mt-2.5 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
                <Field label="decision" value={trace.decision.intent} />
                <Field label="reason code" value={trace.decision.reasonCode} />
                <Field label="question type" value={trace.decision.questionType} />
                <Field label="confidence" value={trace.decision.confidence.toFixed(2)} />
                {trace.latencyMs != null && <Field label="turn latency" value={`${trace.latencyMs} ms`} />}
                <Field label="stage" value={trace.stage.toLowerCase()} />
              </div>

              {trace.provider.notes.length > 0 && (
                <p className="mt-2 text-[11px]" style={{ color: "var(--text-faint)" }}>
                  {trace.provider.notes.join(" · ")}
                </p>
              )}
            </Panel>
          )}

          {isLast && trace?.planHeadline && (
            <p className="mt-2 text-[11.5px]" style={{ color: "var(--text-faint)" }}>
              {trace.planHeadline}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span style={{ color: "var(--text-faint)" }}>{label}</span>
      <span className="truncate font-mono text-[10.5px]" style={{ color: "var(--text-dim)" }} title={value}>
        {value}
      </span>
    </div>
  );
}
