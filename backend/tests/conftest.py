from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Each test session gets an isolated database and a deterministic provider.
os.environ.setdefault("DB_PATH", str(Path(tempfile.gettempdir()) / f"cohortiq-test-{uuid.uuid4().hex}.db"))
os.environ.setdefault("LLM_PROVIDER", "heuristic")
os.environ.setdefault("LOG_LEVEL", "WARNING")


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def roster():
    from app.data.candidates import demo_candidates

    return demo_candidates()


@pytest.fixture
def limits():
    from app.config import InterviewLimits

    return InterviewLimits()
