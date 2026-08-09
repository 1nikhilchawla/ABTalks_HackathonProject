"""Scoring calibration and variance harness.

Answers the question every serious reader asks about an assessment product:
*run the same answer ten times — how much does the score move, and does it agree
with a human label?*

Usage
-----
    python -m tools.calibrate                # whatever provider is configured
    python -m tools.calibrate --runs 5       # fewer repeats
    python -m tools.calibrate --provider heuristic --json out.json

Reports, per rubric dimension:
  * mean and standard deviation across repeats (score stability)
  * verdict stability (how often the same answer gets the same verdict)
  * band accuracy against the hand-labelled golden set
  * agreement between the configured model and the offline rubric engine

Nothing here is inferred: if the run used the offline engine, the report says so
and the variance figures are trivially zero by construction.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import APP_ROOT, Settings  # noqa: E402
from app.engine import prompts  # noqa: E402
from app.engine.evaluator import _normalise  # noqa: E402
from app.data.curriculum import get_curriculum  # noqa: E402
from app.llm.router import LLMRouter  # noqa: E402
from app.llm.schemas import ANSWER_EVALUATION_SCHEMA  # noqa: E402

DIMENSIONS = (
    "technical_accuracy", "conceptual_depth", "specificity",
    "communication", "practical_evidence", "relevance",
)
BAND_ORDER = {"weak": 0, "adequate": 1, "strong": 2}
BAND_RANGES = {"weak": (0, 51), "adequate": (45, 75), "strong": (66, 100)}


def load_cases() -> list[dict[str, Any]]:
    raw = json.loads((APP_ROOT / "data" / "golden.json").read_text(encoding="utf-8"))
    return raw["cases"]


async def score_once(router: LLMRouter, case: dict[str, Any]) -> dict[str, Any]:
    day = get_curriculum().day(case["day"])
    routed = await router.structured(
        system=prompts.EVALUATOR_SYSTEM,
        user=prompts.evaluator_user(
            question=case["question"], answer=case["answer"], day=day, slot=None,
            prior_claims=[], difficulty=3,
        ),
        schema=ANSWER_EVALUATION_SCHEMA,
        schema_name="answer_evaluation",
        context={"answer": case["answer"], "question": case["question"], "day": case["day"]},
        max_tokens=800,
        temperature=0.1,
    )
    evaluation = _normalise(routed.data, answer=case["answer"], source=routed.provider)
    return {
        "provider": routed.provider,
        "composite": evaluation.composite,
        "verdict": evaluation.verdict,
        "dimensions": evaluation.scores.as_dict(),
    }


async def run(runs: int, provider: str | None) -> dict[str, Any]:
    settings = Settings(llm_provider=provider) if provider else Settings()
    router = LLMRouter(settings)
    baseline = LLMRouter(Settings(llm_provider="heuristic"))
    cases = load_cases()

    results: list[dict[str, Any]] = []
    for case in cases:
        samples = [await score_once(router, case) for _ in range(runs)]
        rubric = await score_once(baseline, case)

        composites = [s["composite"] for s in samples]
        verdicts = [s["verdict"] for s in samples]
        modal_verdict = max(set(verdicts), key=verdicts.count)

        per_dimension = {}
        for dimension in DIMENSIONS:
            values = [s["dimensions"][dimension] for s in samples]
            per_dimension[dimension] = {
                "mean": round(statistics.fmean(values), 1),
                "sd": round(statistics.pstdev(values), 2),
            }

        lo, hi = BAND_RANGES[case["band"]]
        results.append(
            {
                "id": case["id"],
                "expectedBand": case["band"],
                "provider": samples[0]["provider"],
                "compositeMean": round(statistics.fmean(composites), 1),
                "compositeSd": round(statistics.pstdev(composites), 2),
                "verdictStability": round(verdicts.count(modal_verdict) / len(verdicts), 2),
                "modalVerdict": modal_verdict,
                "inExpectedRange": lo <= statistics.fmean(composites) <= hi,
                "rubricEngineComposite": rubric["composite"],
                "dimensions": per_dimension,
            }
        )

    await router.aclose()
    await baseline.aclose()

    ranked_model = sorted(results, key=lambda r: r["compositeMean"])
    ranked_expected = sorted(results, key=lambda r: (BAND_ORDER[r["expectedBand"]], r["id"]))
    rank_agreement = _rank_agreement(
        [r["id"] for r in ranked_model], [r["id"] for r in ranked_expected], results
    )

    summary = {
        "provider": results[0]["provider"] if results else "none",
        "runsPerCase": runs,
        "cases": len(results),
        "meanCompositeSd": round(statistics.fmean([r["compositeSd"] for r in results]), 2),
        "meanVerdictStability": round(
            statistics.fmean([r["verdictStability"] for r in results]), 2
        ),
        "bandAccuracy": round(
            sum(1 for r in results if r["inExpectedRange"]) / max(len(results), 1), 2
        ),
        "bandOrderingAgreement": rank_agreement,
        "rubricEngineCorrelation": _correlation(
            [r["compositeMean"] for r in results], [r["rubricEngineComposite"] for r in results]
        ),
    }
    return {"summary": summary, "results": results}


def _rank_agreement(model_order: list[str], expected_order: list[str], results: list[dict]) -> float:
    """Fraction of case pairs ordered consistently with the human bands."""
    band = {r["id"]: BAND_ORDER[r["expectedBand"]] for r in results}
    score = {r["id"]: r["compositeMean"] for r in results}
    ids = list(band)
    comparable = concordant = 0
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            if band[a] == band[b]:
                continue
            comparable += 1
            if (band[a] - band[b]) * (score[a] - score[b]) > 0:
                concordant += 1
    return round(concordant / comparable, 2) if comparable else 0.0


def _correlation(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    try:
        return round(statistics.correlation(xs, ys), 2)
    except statistics.StatisticsError:
        return 0.0


def render(report: dict[str, Any]) -> str:
    s = report["summary"]
    offline = s["provider"] == "heuristic"

    # Label the tautologies. On the offline engine three of these numbers are
    # properties of the harness, not evidence about scoring quality, and a
    # reader skimming the block must not mistake them for the latter.
    sd_note = "TAUTOLOGY: engine is deterministic" if offline else "lower is more stable"
    stability_note = "TAUTOLOGY: engine is deterministic" if offline else "1.0 = same verdict every run"
    corr_note = (
        "TAUTOLOGY: baseline compared with itself" if offline else "model vs offline baseline"
    )

    lines = [
        "",
        f"  Provider ............... {s['provider']}",
        f"  Cases x runs ........... {s['cases']} x {s['runsPerCase']}",
        f"  Mean composite SD ...... {s['meanCompositeSd']}   ({sd_note})",
        f"  Verdict stability ...... {s['meanVerdictStability']}   ({stability_note})",
        f"  Band accuracy .......... {s['bandAccuracy']}   (vs OUR OWN labels, n={s['cases']})",
        f"  Band ordering .......... {s['bandOrderingAgreement']}   (vs OUR OWN labels, n={s['cases']})",
        f"  Rubric-engine corr ..... {s['rubricEngineCorrelation']}   ({corr_note})",
        "",
        f"  {'case':<5} {'band':<9} {'mean':>6} {'sd':>6} {'verdict':<10} {'in band':<8} rubric",
        f"  {'-'*5} {'-'*9} {'-'*6} {'-'*6} {'-'*10} {'-'*8} ------",
    ]
    for r in report["results"]:
        lines.append(
            f"  {r['id']:<5} {r['expectedBand']:<9} {r['compositeMean']:>6} {r['compositeSd']:>6} "
            f"{r['modalVerdict']:<10} {'yes' if r['inExpectedRange'] else 'NO':<8} "
            f"{r['rubricEngineComposite']}"
        )
    if offline:
        lines += [
            "",
            "  READ THIS BEFORE QUOTING ANY NUMBER ABOVE",
            "  This run used the offline rubric engine. Three of these figures are",
            "  tautological and prove nothing about scoring quality:",
            "    - SD 0.0 and stability 1.0: the engine is deterministic by design.",
            "    - Correlation 1.0: the baseline was compared with itself.",
            "  Band accuracy and ordering are measured against labels we wrote",
            f"  ourselves, on {s['cases']} cases. That is a regression guard, not validity",
            "  evidence. The number worth quoting needs one run with a real API key",
            "  (and, properly, labels from independent human interviewers).",
        ]
    else:
        lines += [
            "",
            f"  Band figures are against labels we wrote ourselves ({s['cases']} cases).",
            "  Agreement with independent human interviewers is still unmeasured.",
        ]
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="CohortIQ scoring calibration harness")
    parser.add_argument("--runs", type=int, default=5, help="repeats per case (default 5)")
    parser.add_argument("--provider", default=None, help="anthropic | openai | groq | heuristic")
    parser.add_argument("--json", dest="json_out", default=None, help="write the raw report here")
    args = parser.parse_args()

    report = asyncio.run(run(max(1, args.runs), args.provider))
    print(render(report))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"  raw report written to {args.json_out}\n")


if __name__ == "__main__":
    main()
