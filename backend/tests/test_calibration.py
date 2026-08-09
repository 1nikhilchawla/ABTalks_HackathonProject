"""Scoring quality, measured rather than asserted.

The rubric is the product's core output, so its behaviour is pinned here
against a hand-labelled golden set. These thresholds are deliberately loose:
they exist to catch regressions, not to claim human-level agreement.
"""

from __future__ import annotations

import asyncio
import importlib
import pkgutil
import re

import pytest

from tools.calibrate import run as run_calibration


@pytest.fixture(scope="module")
def report():
    return asyncio.run(run_calibration(runs=2, provider="heuristic"))


def test_offline_engine_is_perfectly_repeatable(report):
    assert report["summary"]["meanCompositeSd"] == 0.0
    assert report["summary"]["meanVerdictStability"] == 1.0


def test_scores_land_in_the_labelled_band(report):
    assert report["summary"]["bandAccuracy"] >= 0.8, report["results"]


def test_bands_are_ordered_the_way_a_human_would_order_them(report):
    assert report["summary"]["bandOrderingAgreement"] >= 0.85


def test_strong_answers_outscore_weak_answers(report):
    by_band: dict[str, list[float]] = {}
    for row in report["results"]:
        by_band.setdefault(row["expectedBand"], []).append(row["compositeMean"])
    assert min(by_band["strong"]) > max(by_band["weak"])


def test_harness_reports_which_provider_produced_the_numbers(report):
    assert report["summary"]["provider"] == "heuristic"


# --------------------------------------------------------------------------
# Regression guard for a bug class that bit twice during development
# --------------------------------------------------------------------------
def test_no_compiled_pattern_contains_a_literal_backspace():
    r"""A mangled ``\b`` becomes ``\x08`` and silently never matches.

    Regexes fail open — the feature just stops working, no error. This walks
    every compiled pattern in the app and fails loudly instead.
    """
    import app

    offenders: list[str] = []
    for module_info in pkgutil.walk_packages(app.__path__, prefix="app."):
        module = importlib.import_module(module_info.name)
        for name, value in vars(module).items():
            if isinstance(value, re.Pattern) and "\x08" in value.pattern:
                offenders.append(f"{module_info.name}.{name}")
    assert not offenders, f"literal backspace in patterns: {offenders}"
