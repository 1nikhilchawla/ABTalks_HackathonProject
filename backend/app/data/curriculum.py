"""Curriculum loading + a tiny lexical retrieval index.

We deliberately avoid a vector database here. The corpus is 31 documents of
~60 words each; BM25 over that beats an embedding round-trip on latency, cost
and determinism, and it never needs a network call. The retrieval interface is
kept narrow (``search`` / ``day``) so swapping in Chroma later is a one-file
change.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from ..config import get_settings

_TOKEN_RE = re.compile(r"[a-z0-9+#.]+")

_STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "of", "for", "in", "on", "with", "using",
    "your", "you", "it", "is", "are", "be", "that", "this", "into", "from", "by",
    "at", "as", "we", "i", "my", "our", "so", "then", "than", "was", "were", "can",
    "will", "would", "should", "do", "did", "does", "have", "has", "had", "not",
}

# Synonyms let a candidate's natural phrasing hit the right curriculum day.
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "rag": ("retrieval", "augmented", "generation", "grounded"),
    "vectordb": ("vector", "database", "chroma", "pinecone"),
    "chroma": ("chromadb", "vector"),
    "chromadb": ("chroma", "vector"),
    "embedding": ("embeddings", "vector"),
    "embeddings": ("embedding", "vector"),
    "llm": ("model", "openai", "ollama"),
    "mcp": ("model", "context", "protocol"),
    "agent": ("agents", "agentic", "react", "langchain"),
    "agents": ("agent", "agentic"),
    "k8s": ("kubernetes",),
    "prompt": ("prompting", "prompts"),
    "finetune": ("fine", "tuning", "lora", "qlora", "peft"),
    "guardrail": ("guardrails", "security", "injection"),
    "observability": ("monitoring", "logging", "prometheus", "grafana"),
    "chunking": ("chunk", "chunks", "splitter", "splitters"),
    "reranking": ("rerank", "retrieval", "matching"),
}


# A day's interview value follows from what kind of day it is. Shipping and
# core-concept days generate the questions worth asking; setup days do not.
_TYPE_WEIGHT: dict[str, float] = {
    "SETUP": 0.35,
    "LEARN": 0.95,
    "BUILD": 1.05,
    "OPTIMIZE": 1.05,
    "AI_CORE": 1.30,
    "SHIP_IT": 1.25,
    "CAPSTONE": 1.15,
}

# Concept families that make a day interview-relevant for an AI engineering role.
# Each family counts once, so a day listing six vector-database tools does not
# out-weigh a day that genuinely spans retrieval, agents and evaluation.
_SIGNAL_CONCEPTS: tuple[tuple[str, ...], ...] = (
    ("embedding", "vector", "chroma", "pinecone"),
    ("retriev", "rag", "search", "rerank"),
    ("prompt", "few-shot", "chain-of-thought"),
    ("agent", "react", "langgraph", "crewai", "orchestrat"),
    ("mcp", "model context protocol", "tool call", "function calling"),
    ("eval", "benchmark", "accuracy", "grounding"),
    ("security", "guardrail", "injection", "privacy"),
    ("deploy", "docker", "kubernetes", "production", "monitor", "observab"),
    ("fine-tun", "lora", "qlora", "peft"),
    ("memory", "context management", "summaris", "summariz"),
)


def _singular(token: str) -> str | None:
    """Crude de-pluralisation so "chunks" matches the objective's "chunk".

    A real stemmer would be overkill for a 31-document corpus, and would also
    make the vocabulary check in grounding.py harder to reason about.
    """
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith(("ses", "xes", "ches", "shes")):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return None


def tokenize(text: str) -> list[str]:
    raw = _TOKEN_RE.findall((text or "").lower())
    out: list[str] = []
    for tok in raw:
        if tok in _STOPWORDS or len(tok) < 2:
            continue
        out.append(tok)
        out.extend(_SYNONYMS.get(tok, ()))
        singular = _singular(tok)
        if singular and singular not in _STOPWORDS:
            out.append(singular)
    return out


@dataclass(frozen=True)
class Day:
    day: int
    title: str
    type: str
    tools: tuple[str, ...]
    objectives: tuple[str, ...]
    module_n: int
    module_title: str

    @property
    def label(self) -> str:
        return f"Day {self.day} — {self.title}"

    def as_dict(self) -> dict:
        return {
            "day": self.day,
            "title": self.title,
            "type": self.type,
            "tools": list(self.tools),
            "objectives": list(self.objectives),
            "module": self.module_title,
        }

    def searchable_text(self) -> str:
        return " ".join([self.title, self.module_title, *self.tools, *self.objectives])

    @property
    def interview_weight(self) -> float:
        """How much interview signal this day carries, derived from its own metadata.

        Earlier this was a hand-tuned table of 31 floats, which was both a wall
        of magic numbers and a hard coupling to one specific curriculum. Deriving
        it from `type` plus concept density means a different cohort's JSON works
        without touching Python.
        """
        base = _TYPE_WEIGHT.get(self.type.upper(), 1.0)
        haystack = f"{self.title} {' '.join(self.tools)} {' '.join(self.objectives)}".lower()
        concepts = sum(1 for family in _SIGNAL_CONCEPTS if any(k in haystack for k in family))
        return round(base + min(concepts * 0.12, 0.45), 3)


@dataclass
class Curriculum:
    cohort: str
    days: dict[int, Day]
    modules: list[dict]
    _df: Counter = field(default_factory=Counter)
    _doc_tokens: dict[int, Counter] = field(default_factory=dict)
    _doc_len: dict[int, int] = field(default_factory=dict)
    _avg_len: float = 1.0
    _vocab: frozenset[str] = frozenset()
    # Second, finer index: one document per learning objective.
    _obj_df: Counter = field(default_factory=Counter)
    _obj_tokens: dict[tuple[int, int], Counter] = field(default_factory=dict)
    _obj_len: dict[tuple[int, int], int] = field(default_factory=dict)
    _obj_avg_len: float = 1.0

    # ---- lifecycle ----------------------------------------------------
    def build_index(self) -> None:
        vocab: set[str] = set()
        for day_no, day in self.days.items():
            toks = tokenize(day.searchable_text())
            counts = Counter(toks)
            self._doc_tokens[day_no] = counts
            self._doc_len[day_no] = max(len(toks), 1)
            for t in counts:
                self._df[t] += 1
            vocab.update(counts)
            vocab.update(t.lower() for tool in day.tools for t in _TOKEN_RE.findall(tool.lower()))

            for i, objective in enumerate(day.objectives):
                obj_toks = tokenize(f"{objective} {day.title} {' '.join(day.tools)}")
                obj_counts = Counter(obj_toks)
                self._obj_tokens[(day_no, i)] = obj_counts
                self._obj_len[(day_no, i)] = max(len(obj_toks), 1)
                for t in obj_counts:
                    self._obj_df[t] += 1

        self._avg_len = sum(self._doc_len.values()) / max(len(self._doc_len), 1)
        self._obj_avg_len = sum(self._obj_len.values()) / max(len(self._obj_len), 1)
        self._vocab = frozenset(vocab)

    # ---- access -------------------------------------------------------
    def day(self, n: int) -> Day | None:
        return self.days.get(n)

    def all_days(self) -> list[Day]:
        return [self.days[k] for k in sorted(self.days)]

    def module_for(self, day_no: int) -> str:
        d = self.days.get(day_no)
        return d.module_title if d else "Unknown module"

    @property
    def vocabulary(self) -> frozenset[str]:
        """Every technical term the curriculum legitimises. Used for grounding."""
        return self._vocab

    def tool_names(self) -> set[str]:
        return {t for d in self.days.values() for t in d.tools}

    # ---- retrieval ----------------------------------------------------
    def search(self, query: str, top_k: int = 3, restrict: set[int] | None = None) -> list[tuple[Day, float]]:
        """BM25 over the day corpus. Returns (day, score) best-first."""
        q_tokens = tokenize(query)
        if not q_tokens:
            return []
        n_docs = max(len(self._doc_tokens), 1)
        k1, b = 1.5, 0.75
        scored: list[tuple[Day, float]] = []
        for day_no, counts in self._doc_tokens.items():
            if restrict is not None and day_no not in restrict:
                continue
            score = 0.0
            dl = self._doc_len[day_no]
            for tok in q_tokens:
                tf = counts.get(tok, 0)
                if not tf:
                    continue
                df = self._df.get(tok, 0)
                idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
                score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / self._avg_len))
            if score > 0:
                scored.append((self.days[day_no], score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def best_day_for(self, text: str, restrict: set[int] | None = None) -> Day | None:
        hits = self.search(text, top_k=1, restrict=restrict)
        return hits[0][0] if hits else None

    def score_day(self, day_no: int, text: str) -> float:
        """BM25 score of `text` against one day. Used to compare topics head-to-head."""
        hits = self.search(text, top_k=1, restrict={day_no})
        return hits[0][1] if hits else 0.0

    def rank_objectives(self, day_no: int, covered_text: str) -> list[tuple[str, float]]:
        """Rank a day's objectives by how *little* the given text covers them.

        This is what turns retrieval into a live component rather than a lookup:
        the interviewer asks about the objective the candidate has said least
        about so far, instead of walking the list in file order.
        """
        day = self.days.get(day_no)
        if day is None:
            return []
        q_tokens = tokenize(covered_text)
        n_docs = max(len(self._obj_tokens), 1)
        k1, b = 1.5, 0.75

        ranked: list[tuple[str, float]] = []
        for i, objective in enumerate(day.objectives):
            counts = self._obj_tokens.get((day_no, i))
            if counts is None:
                ranked.append((objective, 0.0))
                continue
            dl = self._obj_len[(day_no, i)]
            score = 0.0
            for tok in q_tokens:
                tf = counts.get(tok, 0)
                if not tf:
                    continue
                df = self._obj_df.get(tok, 0)
                idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
                score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / self._obj_avg_len))
            ranked.append((objective, score))

        # Least-covered first; stable on ties so the order stays deterministic.
        ranked.sort(key=lambda x: x[1])
        return ranked

    def least_covered_objective(self, day_no: int, covered_text: str) -> str | None:
        ranked = self.rank_objectives(day_no, covered_text)
        return ranked[0][0] if ranked else None


def _parse(raw: dict) -> Curriculum:
    modules = raw.get("modules") or []
    module_lookup: dict[int, tuple[int, str]] = {}
    for mod in modules:
        span = mod.get("days") or []
        if len(span) == 2:
            start, end = int(span[0]), int(span[1])
        elif len(span) == 1:
            start = end = int(span[0])
        else:
            continue
        for d in range(start, end + 1):
            module_lookup[d] = (int(mod.get("n", 0)), str(mod.get("title", "")))

    days: dict[int, Day] = {}
    for entry in raw.get("days") or []:
        try:
            n = int(entry["day"])
        except (KeyError, TypeError, ValueError):
            continue
        mod_n, mod_title = module_lookup.get(n, (0, "Unassigned"))
        days[n] = Day(
            day=n,
            title=str(entry.get("title", f"Day {n}")),
            type=str(entry.get("type", "BUILD")),
            tools=tuple(str(t) for t in entry.get("tools", [])),
            objectives=tuple(str(o) for o in entry.get("objectives", [])),
            module_n=mod_n,
            module_title=mod_title,
        )

    cur = Curriculum(cohort=str(raw.get("cohort", "AI Cohort")), days=days, modules=modules)
    cur.build_index()
    return cur


@lru_cache(maxsize=1)
def get_curriculum() -> Curriculum:
    path: Path = get_settings().curriculum_path
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # A broken curriculum file must not take the service down; the engine
        # degrades to a single generic topic instead.
        raw = {"cohort": "AI Cohort", "modules": [], "days": []}
    return _parse(raw)
