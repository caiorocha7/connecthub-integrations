"""ConnectHub Failure Simulator — a controllable HTTP destination used to demonstrate resilience.

Modes:
- ``normal``      → 200 OK
- ``error``       → configurable 5xx (default 500)
- ``timeout``     → sleeps ``delay_seconds`` before answering (forces client timeout)
- ``rate_limit``  → 429 with ``Retry-After``

``fail_next`` makes the simulator fail only the next N requests and then return to normal.
State is kept in memory (single process) on purpose: this is a demo/testing tool.
"""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from collections import deque
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

Mode = Literal["normal", "error", "timeout", "rate_limit"]
MAX_STORED = 500
RECORDED_HEADERS = (
    "content-type",
    "user-agent",
    "idempotency-key",
    "x-connecthub-event-id",
    "x-connecthub-delivery-id",
    "x-connecthub-attempt",
    "x-connecthub-signature",
    "x-api-version",
)


class ControlConfig(BaseModel):
    mode: Mode = "normal"
    status_code: int = Field(default=500, ge=500, le=599)
    delay_seconds: float = Field(default=30.0, ge=0, le=120)
    retry_after: int = Field(default=5, ge=0, le=3600)
    fail_next: int | None = Field(default=None, ge=1, le=1000)


class ControlState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.config = ControlConfig()
        self.remaining_failures: int | None = None
        self.requests: deque[dict[str, Any]] = deque(maxlen=MAX_STORED)
        self.total_received = 0

    def effective_mode(self) -> Mode:
        with self.lock:
            if self.config.mode == "normal":
                return "normal"
            if self.remaining_failures is not None:
                if self.remaining_failures <= 0:
                    self.config = ControlConfig()
                    self.remaining_failures = None
                    return "normal"
                self.remaining_failures -= 1
            return self.config.mode


state = ControlState()

app = FastAPI(
    title="ConnectHub Failure Simulator",
    version="1.0.0",
    description="Destino HTTP controlável para demonstrar retentativas, timeouts e rate limit.",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _control_view() -> dict[str, Any]:
    return {**state.config.model_dump(), "remaining_failures": state.remaining_failures}


@app.get("/control")
def get_control() -> dict[str, Any]:
    return _control_view()


@app.put("/control")
def set_control(config: ControlConfig) -> dict[str, Any]:
    with state.lock:
        state.config = config
        state.remaining_failures = config.fail_next if config.mode != "normal" else None
    return _control_view()


@app.post("/control/reset")
def reset() -> dict[str, Any]:
    with state.lock:
        state.config = ControlConfig()
        state.remaining_failures = None
        state.requests.clear()
        state.total_received = 0
    return _control_view()


@app.api_route("/hooks/{name}", methods=["POST", "PUT", "PATCH"])
async def receive(name: str, request: Request) -> JSONResponse:
    raw = await request.body()
    try:
        body: Any = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        body = raw.decode(errors="replace")[:2000]
    mode = state.effective_mode()
    record: dict[str, Any] = {
        "id": uuid.uuid4().hex,
        "received_at": datetime.now(UTC).isoformat(),
        "hook": name,
        "method": request.method,
        "headers": {k: v for k, v in request.headers.items() if k.lower() in RECORDED_HEADERS},
        "body": body,
        "mode": mode,
    }
    if mode == "error":
        status, content, headers = state.config.status_code, {"error": "simulated failure"}, {}
    elif mode == "rate_limit":
        status = 429
        content = {"error": "simulated rate limit"}
        headers = {"Retry-After": str(state.config.retry_after)}
    elif mode == "timeout":
        record["response_status"] = None
        record["note"] = f"sleeping {state.config.delay_seconds}s"
        with state.lock:
            state.requests.appendleft(record)
            state.total_received += 1
        await asyncio.sleep(state.config.delay_seconds)
        return JSONResponse({"status": "late response"}, status_code=200)
    else:
        status, content, headers = 200, {"status": "received", "hook": name}, {}
    record["response_status"] = status
    with state.lock:
        state.requests.appendleft(record)
        state.total_received += 1
    return JSONResponse(content, status_code=status, headers=headers)


@app.get("/requests")
def list_requests(
    limit: int = Query(50, ge=1, le=MAX_STORED),
    event_id: str | None = None,
) -> dict[str, Any]:
    with state.lock:
        items = list(state.requests)
        total = state.total_received
    if event_id:
        items = [r for r in items if r["headers"].get("x-connecthub-event-id") == event_id]
    succeeded = [r for r in items if r.get("response_status") and 200 <= r["response_status"] < 300]
    return {
        "total_received": total,
        "matched": len(items),
        "succeeded": len(succeeded),
        "unique_successful_deliveries": len({r["headers"].get("idempotency-key") for r in succeeded}),
        "items": items[:limit],
    }


@app.delete("/requests")
def clear_requests() -> dict[str, str]:
    with state.lock:
        state.requests.clear()
        state.total_received = 0
    return {"status": "cleared"}
