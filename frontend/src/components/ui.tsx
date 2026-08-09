import type { ReactNode } from "react";

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

export function scoreColor(score: number | null | undefined): string {
  if (score == null) return "var(--text-faint)";
  if (score >= 72) return "var(--strong)";
  if (score >= 52) return "var(--mid)";
  return "var(--weak)";
}

export function Panel({
  children,
  className,
  as: Tag = "div",
}: {
  children: ReactNode;
  className?: string;
  as?: "div" | "section" | "aside";
}) {
  return (
    <Tag
      className={cx("panel", className)}
      style={{ background: "var(--panel)", borderColor: "var(--line)", boxShadow: "var(--shadow)" }}
    >
      {children}
    </Tag>
  );
}

export function SectionTitle({ children, hint }: { children: ReactNode; hint?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <h3
        className="text-[11px] font-semibold uppercase tracking-[0.14em]"
        style={{ color: "var(--text-faint)" }}
      >
        {children}
      </h3>
      {hint && (
        <span className="text-[11px] tnum" style={{ color: "var(--text-faint)" }}>
          {hint}
        </span>
      )}
    </div>
  );
}

export function Badge({
  children,
  tone = "neutral",
  title,
}: {
  children: ReactNode;
  tone?: "neutral" | "accent" | "strong" | "mid" | "weak";
  title?: string;
}) {
  const map = {
    neutral: { fg: "var(--text-dim)", bg: "var(--panel-2)", bd: "var(--line)" },
    accent: { fg: "var(--accent)", bg: "var(--accent-dim)", bd: "transparent" },
    strong: { fg: "var(--strong)", bg: "color-mix(in srgb, var(--strong) 14%, transparent)", bd: "transparent" },
    mid: { fg: "var(--mid)", bg: "color-mix(in srgb, var(--mid) 16%, transparent)", bd: "transparent" },
    weak: { fg: "var(--weak)", bg: "color-mix(in srgb, var(--weak) 14%, transparent)", bd: "transparent" },
  }[tone];
  return (
    <span
      title={title}
      className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium leading-4 whitespace-nowrap"
      style={{ color: map.fg, background: map.bg, border: `1px solid ${map.bd}` }}
    >
      {children}
    </span>
  );
}

export function Button({
  children,
  onClick,
  variant = "primary",
  disabled,
  type = "button",
  className,
  title,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "ghost" | "quiet" | "danger";
  disabled?: boolean;
  type?: "button" | "submit";
  className?: string;
  title?: string;
}) {
  const styles: Record<string, React.CSSProperties> = {
    primary: { background: "var(--accent)", color: "#fff", border: "1px solid transparent" },
    ghost: { background: "var(--panel-2)", color: "var(--text)", border: "1px solid var(--line)" },
    quiet: { background: "transparent", color: "var(--text-dim)", border: "1px solid transparent" },
    danger: { background: "transparent", color: "var(--weak)", border: "1px solid var(--line)" },
  };
  return (
    <button
      type={type}
      title={title}
      onClick={onClick}
      disabled={disabled}
      className={cx(
        "rounded-lg px-3.5 py-2 text-sm font-medium transition-all duration-150",
        "hover:brightness-110 active:scale-[0.985] disabled:cursor-not-allowed disabled:opacity-45",
        className,
      )}
      style={styles[variant]}
    >
      {children}
    </button>
  );
}

export function Meter({
  value,
  max = 100,
  color,
  height = 6,
}: {
  value: number;
  max?: number;
  color?: string;
  height?: number;
}) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div
      className="w-full overflow-hidden rounded-full"
      style={{ background: "var(--line-soft)", height }}
      role="presentation"
    >
      <div
        className="h-full rounded-full transition-[width] duration-500 ease-out"
        style={{ width: `${pct}%`, background: color ?? scoreColor(value) }}
      />
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("skeleton", className)} />;
}

export function EmptyState({ title, body, action }: { title: string; body: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      <p className="text-sm font-medium">{title}</p>
      <p className="max-w-sm text-[13px] leading-relaxed" style={{ color: "var(--text-dim)" }}>
        {body}
      </p>
      {action}
    </div>
  );
}

export function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div
      role="alert"
      className="flex items-center justify-between gap-3 rounded-lg px-3 py-2 text-[13px] animate-rise"
      style={{
        background: "color-mix(in srgb, var(--weak) 12%, transparent)",
        border: "1px solid color-mix(in srgb, var(--weak) 35%, transparent)",
        color: "var(--text)",
      }}
    >
      <span>{message}</span>
      {onRetry && (
        <button
          onClick={onRetry}
          className="shrink-0 rounded-md px-2 py-1 text-[12px] font-medium"
          style={{ background: "var(--panel-2)", border: "1px solid var(--line)" }}
        >
          Retry
        </button>
      )}
    </div>
  );
}

export function Difficulty({ level }: { level: number }) {
  return (
    <span className="inline-flex items-center gap-[3px]" title={`Difficulty ${level} of 5`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <span
          key={i}
          className="h-3 w-[3px] rounded-full transition-colors duration-300"
          style={{ background: i <= level ? "var(--accent)" : "var(--line)" }}
        />
      ))}
    </span>
  );
}

export function TypingDots() {
  return (
    <span className="inline-flex items-center gap-1" aria-label="Interviewer is thinking">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="typing-dot h-1.5 w-1.5 rounded-full"
          style={{ background: "var(--text-faint)" }}
        />
      ))}
    </span>
  );
}

export const SIGNAL_TONE: Record<string, "strong" | "mid" | "weak" | "neutral" | "accent"> = {
  first_try_pass: "strong",
  few_attempts: "neutral",
  high_attempts: "mid",
  failed: "weak",
  skipped: "weak",
  no_history: "neutral",
  capstone: "accent",
};

export const KIND_LABEL: Record<string, string> = {
  WARMUP: "Warm-up",
  CORE: "Core",
  PROBE: "Probe",
  GAP: "Gap check",
  SYNTHESIS: "Synthesis",
  BEHAVIORAL: "Behavioural",
};

export const DIMENSION_LABEL: Record<string, string> = {
  technical_accuracy: "Technical accuracy",
  conceptual_depth: "Conceptual depth",
  specificity: "Specificity",
  communication: "Communication",
  practical_evidence: "Practical evidence",
  relevance: "Relevance",
};

export const FLAG_LABEL: Record<string, string> = {
  vague_language: "vague",
  buzzword_heavy: "buzzwords",
  rambling: "rambling",
  too_short: "too short",
  no_concrete_metrics: "no metrics",
  possibly_off_topic: "off topic",
  memorised_sounding: "memorised",
  contradicts_earlier: "contradiction",
  overclaiming: "overclaiming",
  non_answer: "non-answer",
  ungrounded_quote_removed: "quote dropped",
};
