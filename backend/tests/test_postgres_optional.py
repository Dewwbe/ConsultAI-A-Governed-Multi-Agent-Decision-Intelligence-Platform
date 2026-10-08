"""Runs the restart-survival scenario against a real PostgreSQL. Skipped unless TEST_POSTGRES_URL is set:

    docker compose up -d postgres
    set TEST_POSTGRES_URL=postgresql://consultai:consultai@localhost:5432/consultai
    python -m pytest tests/test_postgres_optional.py
"""
import os

import pytest

from app.config import Settings
from app.security.auth import Principal
from app.workflow.graph import RUNTIMES
from app.workflow.service import EngagementService

URL = os.environ.get("TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_POSTGRES_URL not set")
REQ = {"business_problem": "Should we expand into the UAE market?", "industry": "Retail",
       "constraints": ["Budget under $10M"]}


def test_paused_run_survives_restart_on_postgres():
    settings = Settings(database_url=URL, llm_provider="stub")
    first = EngagementService(settings)
    wid = first.start(**REQ)["workflow_id"]
    assert first.get(wid)["status"] == "awaiting_approval"
    RUNTIMES.pop(wid)
    second = EngagementService(settings)  # new process, same database
    assert second.get(wid)["status"] == "awaiting_approval"
    done = second.approve(wid, "approve", reason="ok", approver=Principal("p", "Pat", ("Partner",)))
    assert done["status"] == "completed"
    assert [a["decision"] for a in second.approvals(wid)] == ["approve"]
