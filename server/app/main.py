"""Flowground backend — FastAPI app.

- ``GET  /api/healthz``          liveness probe
- ``POST /api/flows/validate``   friendly validation (incl. LoopGraph rejections)
- ``WS   /api/runs``             run sessions (see PROTOCOL.md)
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict

from fastapi import Body, FastAPI, WebSocket, WebSocketDisconnect

from .compiler import compile_flow
from .schema import FlowValidationError, parse_flow
from .session import Session

app = FastAPI(title="Flowground backend")


@app.get("/api/healthz")
async def healthz() -> Dict[str, bool]:
    return {"ok": True}


@app.post("/api/flows/validate")
async def validate_flow(payload: Any = Body(None)) -> Dict[str, Any]:
    if not isinstance(payload, dict) or "flow" not in payload:
        return {"ok": False,
                "errors": ['Send a JSON object like {"flow": { … }}.']}
    try:
        compile_flow(parse_flow(payload["flow"]))
    except FlowValidationError as exc:
        return {"ok": False, "errors": exc.errors}
    return {"ok": True}


@app.websocket("/api/runs")
async def runs(ws: WebSocket) -> None:
    await ws.accept()
    outbox: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
    session = Session(outbox)

    async def _sender() -> None:
        while True:
            # allow_nan=False: bare NaN/Infinity are not JSON and browsers'
            # JSON.parse rejects them — non-finite numbers must already be
            # {"__js": …}-encoded upstream, so fail loudly if one leaks.
            await ws.send_text(json.dumps(await outbox.get(),
                                          allow_nan=False))

    sender = asyncio.create_task(_sender())
    try:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            raw = message.get("text")
            if raw is None:
                data = message.get("bytes") or b""
                raw = data.decode("utf-8", "replace")
            session.handle_raw(raw)
    except WebSocketDisconnect:
        pass
    finally:
        session.shutdown()
        sender.cancel()
