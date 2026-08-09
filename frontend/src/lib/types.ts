export type Verdict = "strong" | "adequate" | "weak" | "non_answer";

export interface Dimensions {
  technical_accuracy: number;
  conceptual_depth: number;
  specificity: number;
  communication: number;
  practical_evidence: number;
  relevance: number;
}

export interface Evaluation {
  verdict: Verdict;
  composite: number;
  dimensions: Dimensions;
  rationale: string;
  flags: string[];
  evidenceQuote?: string;
  missingPoints?: string[];
  source?: string;
}

export interface DecisionTrace {
  intent: string;
  topic: string;
  day: number | null;
  difficulty: number;
  reasonCode: string;
  questionType: string;
  confidence: number;
  evidence: string[];
}

export interface Trace {
  decision: DecisionTrace;
  why: string;
  stage: string;
  difficulty: number;
  questionsAsked: number;
  coverage: {
    daysCovered: number[];
    minDays: number;
    minQuestions: number;
    maxQuestions: number;
  };
  currentTopic: {
    day: number;
    title: string;
    module: string;
    kind: string;
    signal: string;
    signalCode: string;
    objectives: string[];
  } | null;
  provider: { primary: string; live: boolean; degraded: boolean; notes: string[] };
  usage: {
    calls: number;
    inputTokens: number;
    outputTokens: number;
    avgLatencyMs: number;
    failures: number;
    fallbacks: number;
    byProvider: Record<string, number>;
  };
  evaluation?: Evaluation;
  injectionAttempts: number;
  latencyMs?: number;
  planHeadline?: string;
  final?: boolean;
}

export interface PlanSlot {
  slotId: string;
  day: number;
  title: string;
  module: string;
  kind: string;
  signal: string;
  signalCode: string;
  difficulty: number;
  questionsAsked: number;
  closed: boolean;
  active: boolean;
}

export interface SessionState {
  sessionId: string;
  stage: string;
  persona: string;
  personaLabel: string;
  difficulty: number;
  questionsAsked: number;
  minQuestions: number;
  maxQuestions: number;
  daysCovered: number[];
  minDays: number;
  done: boolean;
  degraded: boolean;
  candidate: {
    name: string;
    role: string;
    years: number;
    isPlaceholder: boolean;
    parseNotes: string[];
  };
  plan: PlanSlot[];
  claims: { text: string; status: string; topic: string }[];
  scores: { turn: number; day: number | null; composite: number | null; verdict: string | null }[];
}

export interface Feedback {
  summary: string;
  strengths: string[];
  gaps: string[];
  next: string[];
}

export interface TimelineEntry {
  turn: number;
  question: string;
  day: number | null;
  action: string | null;
  difficulty: number | null;
  reasonCode?: string;
  why?: string;
  answer?: string;
  utterance?: string | null;
  score?: number;
  verdict?: Verdict;
  flags?: string[];
  rationale?: string;
  dimensions?: Dimensions;
}

export interface Report {
  overall: number;
  readiness: { label: string; note: string };
  dimensions: Dimensions;
  perTopic: {
    slotId: string;
    day: number;
    topic: string;
    module: string;
    kind: string;
    signal: string;
    signalCode: string;
    score: number;
    questions: number;
    flags: string[];
  }[];
  coverage: { questionsAsked: number; daysCovered: number[]; modules: string[] };
  headline: string;
  behaviours: string[];
  timeline: TimelineEntry[];
  claims: { text: string; topic: string; status: string; turn: number; evidence: string[] }[];
  missedObjectives: string[];
  groundingWarnings: string[];
  generatedBy: string;
  degraded: boolean;
}

export interface InterviewReply {
  reply: string;
  done: boolean;
  feedback?: Feedback;
  trace?: Trace;
  state?: SessionState;
  report?: Report;
}

export interface RosterEntry {
  id: string;
  name: string;
  role: string;
  years: number;
  signals: { commitDays: number; missionsCompleted: number; missionsFirstTry: number };
  missionCount: number;
  raw: unknown;
}

export interface PlanPreview {
  candidate: {
    name: string;
    role: string;
    firstTryDays: number[];
    struggleDays: number[];
    failedDays: number[];
    skippedDays: number[];
    firstTryRate: number;
    parseNotes: string[];
  };
  plan: Omit<PlanSlot, "questionsAsked" | "closed" | "active">[];
}

export interface Persona {
  id: string;
  label: string;
  style: string;
}

export type Msg =
  | { role: "interviewer"; text: string; trace?: Trace; id: string }
  | { role: "candidate"; text: string; id: string };

export interface CohortDay {
  day: number;
  title: string;
  module: string;
  interviews: number;
  meanScore: number;
  minScore: number;
  maxScore: number;
  belowBar: number;
  weakestQuote: string;
  weakestCandidate: string;
  commonFlags: string[];
}

export interface CohortInsights {
  interviews: number;
  meanOverall: number;
  daysCovered: number;
  days: CohortDay[];
  weakestDays: CohortDay[];
  strongestDays: CohortDay[];
  signalMix: Record<string, number>;
  commonFlags: Record<string, number>;
  injectionAttempts: number;
  minSamplesForRanking: number;
}
