import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./lib/api";
import { messageId, newSessionId, storedDraft, storedSession, theme } from "./lib/session";
import type { Feedback, Msg, Report as ReportData, SessionState, Trace } from "./lib/types";
import { Cohort } from "./components/Cohort";
import { Compare } from "./components/Compare";
import { Interview } from "./components/Interview";
import { PlanReveal } from "./components/PlanReveal";
import { Report } from "./components/Report";
import { Setup } from "./components/Setup";
import { Button, Skeleton, cx } from "./components/ui";

type Phase = "restoring" | "setup" | "compare" | "cohort" | "reveal" | "interview";

export default function App() {
  const [phase, setPhase] = useState<Phase>("restoring");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [state, setState] = useState<SessionState | null>(null);
  const [trace, setTrace] = useState<Trace | null>(null);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [report, setReport] = useState<ReportData | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const [draft, setDraft] = useState(() => storedDraft.get());
  const [mode, setMode] = useState(() => theme.get());
  const [offline, setOffline] = useState(() => !navigator.onLine);

  const lastMessageRef = useRef<string | null>(null);

  useEffect(() => theme.apply(), []);
  useEffect(() => storedDraft.set(draft), [draft]);

  useEffect(() => {
    const online = () => setOffline(false);
    const down = () => setOffline(true);
    window.addEventListener("online", online);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", online);
      window.removeEventListener("offline", down);
    };
  }, []);

  // --- session recovery: a refresh must not lose the interview -----------
  useEffect(() => {
    const existing = storedSession.get();
    if (!existing) {
      setPhase("setup");
      return;
    }
    let cancelled = false;
    api
      .session(existing)
      .then((data) => {
        if (cancelled) return;
        setSessionId(existing);
        setState(data.state);
        setFeedback(data.feedback);
        setReport(data.report);
        setMessages(
          data.transcript
            .filter((turn) => turn.role !== "system")
            .map((turn) => ({
              id: messageId(),
              role: turn.role === "interviewer" ? "interviewer" : "candidate",
              text: turn.text,
              trace: turn.trace
                ? ({
                    why: (turn.trace.why as string) ?? "",
                    decision: {
                      intent: (turn.action as string) ?? "",
                      topic: "",
                      day: turn.day,
                      difficulty: turn.difficulty ?? 3,
                      reasonCode: (turn.trace.reasonCode as string) ?? "",
                      questionType: (turn.trace.questionType as string) ?? "",
                      confidence: 0,
                      evidence: [],
                    },
                  } as unknown as Trace)
                : undefined,
            })) as Msg[],
        );
        setPhase("interview");
      })
      .catch(() => {
        if (cancelled) return;
        storedSession.clear();
        setPhase("setup");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const applyReply = useCallback(
    (reply: Awaited<ReturnType<typeof api.reply>>) => {
      setMessages((prev) => [
        ...prev,
        { id: messageId(), role: "interviewer", text: reply.reply, trace: reply.trace },
      ]);
      if (reply.state) setState(reply.state);
      if (reply.trace) setTrace(reply.trace);
      if (reply.feedback) setFeedback(reply.feedback);
      if (reply.report) setReport(reply.report);
    },
    [],
  );

  const start = useCallback(
    async (candidate: unknown, persona: string) => {
      setStartError(null);
      setBusy(true);
      const id = newSessionId();
      try {
        const reply = await api.start(id, candidate, persona);
        setSessionId(id);
        storedSession.set(id);
        setMessages([{ id: messageId(), role: "interviewer", text: reply.reply, trace: reply.trace }]);
        if (reply.state) setState(reply.state);
        if (reply.trace) setTrace(reply.trace);
        // Everyone sees the evidence-linked plan once, full screen, before the
        // conversation starts competing for their attention.
        setPhase(reply.state?.plan?.length ? "reveal" : "interview");
      } catch (err) {
        setStartError(
          err instanceof ApiError ? err.message : "Couldn't start the interview. Try again.",
        );
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  const send = useCallback(
    async (text: string) => {
      if (!sessionId) return;
      setError(null);
      setBusy(true);
      lastMessageRef.current = text;
      setMessages((prev) => [...prev, { id: messageId(), role: "candidate", text }]);
      setDraft("");
      storedDraft.clear();
      try {
        const reply = await api.reply(sessionId, text);
        applyReply(reply);
        lastMessageRef.current = null;
      } catch (err) {
        setError(
          err instanceof ApiError
            ? err.message
            : "Something went wrong sending that. Your answer is kept — press retry.",
        );
      } finally {
        setBusy(false);
      }
    },
    [sessionId, applyReply],
  );

  const retry = useCallback(() => {
    const pending = lastMessageRef.current;
    if (!pending || !sessionId) return;
    setError(null);
    setBusy(true);
    // The message is already in the transcript; resend it without duplicating.
    api
      .reply(sessionId, pending)
      .then((reply) => {
        applyReply(reply);
        lastMessageRef.current = null;
      })
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : "Still failing. Check your connection."),
      )
      .finally(() => setBusy(false));
  }, [sessionId, applyReply]);

  const restart = useCallback(() => {
    storedSession.clear();
    setSessionId(null);
    setMessages([]);
    setState(null);
    setTrace(null);
    setFeedback(null);
    setReport(null);
    setError(null);
    setDraft("");
    setPhase("setup");
  }, []);

  const toggleTheme = () => {
    const next = mode === "dark" ? "light" : "dark";
    theme.set(next);
    setMode(next);
  };

  const done = Boolean(state?.done && feedback && report);

  const inInterview = phase === "interview" || phase === "reveal";

  return (
    <div className="min-h-full">
      <TopBar
        mode={mode}
        onToggleTheme={toggleTheme}
        offline={offline}
        onRestart={sessionId ? restart : undefined}
        phase={phase}
        onNavigate={inInterview ? undefined : setPhase}
      />

      {phase === "restoring" && (
        <div className="mx-auto max-w-3xl space-y-3 px-6 py-16">
          <Skeleton className="h-8 w-64" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-4/5" />
          <Skeleton className="h-40 w-full rounded-xl" />
        </div>
      )}

      {phase === "setup" && (
        <Setup
          onStart={(candidate, persona) => void start(candidate, persona)}
          starting={busy}
          startError={startError}
        />
      )}

      {phase === "compare" && (
        <Compare
          onBack={() => setPhase("setup")}
          onStartInterview={(candidate) => void start(candidate, "principal")}
        />
      )}

      {phase === "cohort" && <Cohort onBack={() => setPhase("setup")} />}

      {phase === "reveal" && state && (
        <PlanReveal state={state} onContinue={() => setPhase("interview")} />
      )}

      {phase === "interview" && (
        <>
          <Interview
            messages={messages}
            state={state}
            trace={trace}
            busy={busy}
            error={error}
            draft={draft}
            onDraftChange={setDraft}
            onSend={(text) => void send(text)}
            onRetry={retry}
            onEndEarly={() => void send("Let's end the interview here, please.")}
            onRestart={restart}
          />
          {done && report && feedback && (
            <div id="report" className="border-t" style={{ borderColor: "var(--line)" }}>
              <Report
                report={report}
                feedback={feedback}
                candidateName={state?.candidate.name ?? "Candidate"}
                onRestart={restart}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}

function TopBar({
  mode,
  onToggleTheme,
  offline,
  onRestart,
  phase,
  onNavigate,
}: {
  mode: string;
  onToggleTheme: () => void;
  offline: boolean;
  onRestart?: () => void;
  phase: Phase;
  onNavigate?: (phase: Phase) => void;
}) {
  const tabs: [Phase, string][] = [
    ["setup", "Interview"],
    ["compare", "Compare"],
    ["cohort", "Cohort insights"],
  ];
  return (
    <header
      className="sticky top-0 z-20 border-b backdrop-blur"
      style={{ background: "color-mix(in srgb, var(--bg) 82%, transparent)", borderColor: "var(--line)" }}
    >
      <div className="mx-auto flex w-full max-w-6xl items-center justify-between gap-3 px-4 py-2.5 sm:px-6">
        <div className="flex items-center gap-2.5">
          <div
            className="flex h-7 w-7 items-center justify-center rounded-lg text-[11px] font-bold"
            style={{ background: "var(--accent)", color: "#fff" }}
          >
            IQ
          </div>
          <div className="leading-tight">
            <div className="text-[13.5px] font-semibold tracking-[-0.01em]">CohortIQ</div>
            <div className="text-[10.5px]" style={{ color: "var(--text-faint)" }}>
              Interview intelligence for the AI Cohort
            </div>
          </div>
        </div>

        {onNavigate && (
          <nav className="hidden items-center gap-1 sm:flex">
            {tabs.map(([target, label]) => (
              <button
                key={target}
                onClick={() => onNavigate(target)}
                className="rounded-lg px-2.5 py-1.5 text-[12.5px] font-medium transition-colors duration-150"
                style={{
                  color: phase === target ? "var(--accent)" : "var(--text-dim)",
                  background: phase === target ? "var(--accent-dim)" : "transparent",
                }}
              >
                {label}
              </button>
            ))}
          </nav>
        )}

        <div className="flex items-center gap-2">
          {offline && (
            <span
              className={cx("rounded-md px-2 py-1 text-[11px] font-medium")}
              style={{ background: "color-mix(in srgb, var(--weak) 14%, transparent)", color: "var(--weak)" }}
            >
              offline — answers are kept locally
            </span>
          )}
          {onRestart && (
            <Button variant="quiet" onClick={onRestart}>
              Restart
            </Button>
          )}
          <button
            onClick={onToggleTheme}
            title={`Switch to ${mode === "dark" ? "light" : "dark"} theme`}
            className="flex h-8 w-8 items-center justify-center rounded-lg"
            style={{ background: "var(--panel)", border: "1px solid var(--line)", color: "var(--text-dim)" }}
          >
            {mode === "dark" ? (
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="4" />
                <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
              </svg>
            ) : (
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
              </svg>
            )}
          </button>
        </div>
      </div>
    </header>
  );
}
