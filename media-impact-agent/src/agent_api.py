"""agent_api.py — FastAPI wrapper for the Media Impact Sales Agent.

Start locally:
    uvicorn src.agent_api:app --reload

Example:
    curl -X POST http://localhost:8000/ask \
         -H "Content-Type: application/json" \
         -d '{"question": "Welche Channels eignen sich für eine Auto-Kampagne?"}'

Streaming hook (add later, no agent-core change needed):
    from fastapi.responses import StreamingResponse
    from agent import stream_agent

    @app.post("/ask/stream")
    def ask_stream(request: AskRequest):
        # TODO STREAMING: yields token-by-token once stream_agent uses
        # client.messages.stream internally instead of .create
        return StreamingResponse(
            stream_agent(request.question),
            media_type="text/plain",
        )

Conversation hook (add later):
    class AskRequest(BaseModel):
        question: str
        # TODO CONVERSATION: uncomment and forward to run_agent(history=...)
        # history: list[dict] = []
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, field_validator

sys.path.insert(0, str(Path(__file__).parent))

from agent import run_agent  # noqa: E402 — sys.path must be patched first

logger = logging.getLogger(__name__)

app = FastAPI(title="Media Impact Sales Agent API", version="1.0.0")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class AskRequest(BaseModel):
    question: str

    @field_validator("question")
    @classmethod
    def question_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("question must not be empty or whitespace")
        return v


class AskResponse(BaseModel):
    answer: str


class HealthResponse(BaseModel):
    status: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness + DB reachability check."""
    try:
        with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
            conn.execute("SELECT 1")
    except Exception:
        logger.exception("Health check: DB unreachable")
        raise HTTPException(status_code=503, detail="Database unavailable")
    return HealthResponse(status="ok")


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest) -> AskResponse:
    """Answer a single sales question (stateless, no conversation history in v1).

    TODO CONVERSATION: add `history: list[dict] = []` to AskRequest and pass
    it here: run_agent(request.question, history=request.history)
    """
    try:
        answer = run_agent(request.question)
    except Exception:
        logger.exception("Agent error for question (first 80 chars): %.80s", request.question)
        raise HTTPException(status_code=500, detail="Internal server error")

    return AskResponse(answer=answer)
