import { useEffect, useRef, useState } from "react";
import { Button, cx } from "./ui";

/**
 * Answer input.
 *
 * Dictation is opt-in and strictly additive: the Web Speech API is only offered
 * when the browser exposes it, every failure path falls back to typing, and the
 * transcript lands in the same textarea so nothing is submitted that the
 * candidate has not seen.
 */

type SpeechRecognitionLike = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  start(): void;
  stop(): void;
  onresult: ((event: any) => void) | null;
  onerror: ((event: any) => void) | null;
  onend: (() => void) | null;
};

function getRecognition(): SpeechRecognitionLike | null {
  const ctor =
    (window as any).SpeechRecognition ?? (window as any).webkitSpeechRecognition ?? null;
  if (!ctor) return null;
  try {
    const recognition: SpeechRecognitionLike = new ctor();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = navigator.language || "en-US";
    return recognition;
  } catch {
    return null;
  }
}

const MAX_CHARS = 6000;

export function Composer({
  onSend,
  busy,
  disabled,
  draft,
  onDraftChange,
}: {
  onSend: (text: string) => void;
  busy: boolean;
  disabled?: boolean;
  draft: string;
  onDraftChange: (value: string) => void;
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const baseTextRef = useRef("");
  const [listening, setListening] = useState(false);
  const [micError, setMicError] = useState<string | null>(null);
  const [speechSupported] = useState(() => typeof window !== "undefined" && !!getRecognition());

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 260)}px`;
  }, [draft]);

  useEffect(() => {
    if (!busy && !disabled) textareaRef.current?.focus();
  }, [busy, disabled]);

  useEffect(() => () => recognitionRef.current?.stop(), []);

  const submit = () => {
    const text = draft.trim();
    if (!text || busy || disabled) return;
    stopListening();
    onSend(text);
  };

  const stopListening = () => {
    recognitionRef.current?.stop();
    recognitionRef.current = null;
    setListening(false);
  };

  const toggleMic = () => {
    if (listening) {
      stopListening();
      return;
    }
    const recognition = getRecognition();
    if (!recognition) {
      setMicError("Dictation isn't available in this browser. Typing works exactly the same.");
      return;
    }
    setMicError(null);
    baseTextRef.current = draft ? `${draft.trimEnd()} ` : "";

    recognition.onresult = (event: any) => {
      let transcript = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        transcript += event.results[i][0].transcript;
      }
      onDraftChange((baseTextRef.current + transcript).slice(0, MAX_CHARS));
    };
    recognition.onerror = (event: any) => {
      const code = event?.error ?? "unknown";
      setMicError(
        code === "not-allowed" || code === "service-not-allowed"
          ? "Microphone access was blocked. Type your answer instead."
          : code === "no-speech"
            ? "I didn't hear anything — try again or type your answer."
            : "Dictation stopped unexpectedly. Your typed text is untouched.",
      );
      stopListening();
    };
    recognition.onend = () => setListening(false);

    try {
      recognition.start();
      recognitionRef.current = recognition;
      setListening(true);
    } catch {
      setMicError("Couldn't start the microphone. Type your answer instead.");
    }
  };

  const remaining = MAX_CHARS - draft.length;

  return (
    <div className="space-y-2">
      {micError && (
        <p className="text-[12px]" style={{ color: "var(--mid)" }}>
          {micError}
        </p>
      )}
      <div
        className="rounded-xl p-2.5 transition-colors duration-200"
        style={{
          background: "var(--panel)",
          border: `1px solid ${listening ? "var(--accent)" : "var(--line)"}`,
          boxShadow: "var(--shadow)",
        }}
      >
        <textarea
          ref={textareaRef}
          value={draft}
          disabled={disabled}
          maxLength={MAX_CHARS}
          onChange={(e) => onDraftChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              submit();
            }
          }}
          rows={2}
          placeholder={
            disabled ? "The interview is complete." : "Answer as you would out loud. Specifics beat adjectives."
          }
          className="w-full resize-none bg-transparent px-2 py-1.5 text-[14.5px] leading-relaxed outline-none placeholder:opacity-60"
          style={{ color: "var(--text)" }}
        />
        <div className="mt-1 flex items-center justify-between gap-3 px-1">
          <div className="flex items-center gap-2">
            {speechSupported && (
              <button
                onClick={toggleMic}
                disabled={disabled}
                title={listening ? "Stop dictation" : "Dictate your answer"}
                className={cx(
                  "flex h-8 w-8 items-center justify-center rounded-lg transition-all duration-150",
                  listening && "animate-pulse",
                )}
                style={{
                  background: listening ? "var(--accent)" : "var(--panel-2)",
                  color: listening ? "#fff" : "var(--text-dim)",
                  border: "1px solid var(--line)",
                }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z" />
                  <path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v3" />
                </svg>
              </button>
            )}
            <span className="text-[11.5px]" style={{ color: "var(--text-faint)" }}>
              {listening ? "Listening…" : "⌘/Ctrl + Enter to send"}
            </span>
          </div>
          <div className="flex items-center gap-2.5">
            {remaining < 800 && (
              <span className="tnum text-[11.5px]" style={{ color: remaining < 100 ? "var(--weak)" : "var(--text-faint)" }}>
                {remaining}
              </span>
            )}
            <Button onClick={submit} disabled={busy || disabled || !draft.trim()}>
              {busy ? "Sending…" : "Send"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
