"""tests/test_agent_api.py — API tests for src/agent_api.py.

Agent core is MOCKED — no real LLM call happens.
Health endpoint uses the real test DB (mediaimpact_test, set up by conftest.py).

Run:
    pytest tests/test_agent_api.py -v
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from agent_api import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

def test_health_returns_200():
    response = client.get("/health")
    assert response.status_code == 200


def test_health_body():
    response = client.get("/health")
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# /ask — validation (no mock needed, agent is never reached)
# ---------------------------------------------------------------------------

def test_ask_empty_question_returns_422():
    response = client.post("/ask", json={"question": ""})
    assert response.status_code == 422


def test_ask_whitespace_question_returns_422():
    response = client.post("/ask", json={"question": "   "})
    assert response.status_code == 422


def test_ask_missing_question_field_returns_422():
    response = client.post("/ask", json={})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# /ask — valid request with mocked agent
# ---------------------------------------------------------------------------

def test_ask_valid_returns_200():
    with patch("agent_api.run_agent", return_value="Empfehlung: Technology-Channel, CPM 45 €."):
        response = client.post("/ask", json={"question": "Welche Channels für Auto-Kampagne?"})
    assert response.status_code == 200


def test_ask_valid_answer_is_nonempty():
    mock_answer = "Empfehlung: Technology-Channel, CPM 45 €."
    with patch("agent_api.run_agent", return_value=mock_answer):
        response = client.post("/ask", json={"question": "Welche Channels für Auto-Kampagne?"})
    data = response.json()
    assert data["answer"]


def test_ask_valid_answer_matches_mock():
    mock_answer = "Empfehlung: Technology-Channel, CPM 45 €."
    with patch("agent_api.run_agent", return_value=mock_answer):
        response = client.post("/ask", json={"question": "Welche Channels für Auto-Kampagne?"})
    assert response.json()["answer"] == mock_answer


# ---------------------------------------------------------------------------
# /ask — agent error → 500 without internal details
# ---------------------------------------------------------------------------

def test_ask_agent_error_returns_500():
    with patch("agent_api.run_agent", side_effect=RuntimeError("DB connection failed")):
        response = client.post("/ask", json={"question": "Test-Frage"})
    assert response.status_code == 500


def test_ask_agent_error_body_is_exactly_generic():
    # Strict check: response body must be exactly the generic error — no exception
    # details, no connection strings, no paths, no tracebacks.
    with patch("agent_api.run_agent", side_effect=RuntimeError("postgresql://secret:pw@host/db")):
        response = client.post("/ask", json={"question": "Test-Frage"})
    assert response.json() == {"detail": "Internal server error"}
