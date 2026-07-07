"""Run-session actor for the ``/api/runs`` WebSocket.

One :class:`Session` per socket; at most one active :class:`Run`.  A Run owns:

- the asyncio task executing the real LoopGraph ``Scheduler.run``,
- the credit gate that paces execution (auto mode releases one credit every
  ``SPEEDS[speed]`` ms; step mode releases one credit per ``step`` message),
- the outbound message queue (shared with the socket's sender task).

Fidelity: ``tick`` ordering and the ``next`` field are derived from the
engine's own ``EventBus`` events — the tick for node A is emitted when the
engine emits ``NODE_SCHEDULED`` for the next node B, pairing A's recorded
report with the observed B.  If the engine's observed next disagrees with the
static edge map, the engine wins.
"""

from __future__ import annotations

import asyncio
import json
import math
from typing import Any, Dict, List, Optional, Tuple

from loopgraph.bus.eventbus import Event, EventBus
from loopgraph.concurrency import SemaphorePolicy
from loopgraph.core.types import EventType
from loopgraph.scheduler.scheduler import Scheduler

from .compiler import CompiledFlow, Report, build_registry, compile_flow
from .schema import FlowValidationError, parse_flow

#: auto-run intervals in ms, indexed by the client's ``speed``.
SPEEDS = [1400, 850, 420]

#: maximum accepted length of a client-chosen runId (PROTOCOL.md: ~64).
RUN_ID_MAX_LEN = 64


def _logs_json(logs: List[Tuple[str, str]]) -> List[Dict[str, str]]:
    return [{"kind": kind, "text": text} for kind, text in logs]


def _json_val(v: Any) -> Any:
    """Vars snapshots must be strictly-valid JSON (browsers' JSON.parse rejects
    bare NaN/Infinity) — encode non-finite numbers as {"__js": …} markers."""
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        if math.isnan(v):
            return {"__js": "NaN"}
        if v == math.inf:
            return {"__js": "Infinity"}
        if v == -math.inf:
            return {"__js": "-Infinity"}
        if v.is_integer() and abs(v) <= 2 ** 53:
            return int(v)  # cosmetic: 4.0 ships as 4, like JSON.stringify
    return v


def _json_vars(variables: Dict[str, Any]) -> Dict[str, Any]:
    return {k: _json_val(v) for k, v in variables.items()}


class Run:
    """One execution of one flow. Also serves as the handlers' run context."""

    def __init__(self, session: "Session", compiled: CompiledFlow,
                 mode: str, speed: int, run_id: Optional[str] = None):
        self.session = session
        self.compiled = compiled
        self.mode = mode
        self.speed = speed
        self.run_id = run_id
        self.auto = mode == "run"

        # run-context state used by the compiled handlers
        self.vars: Dict[str, Any] = {}
        self.loop_counts: Dict[str, int] = {}
        self.steps = 0

        self.credits = asyncio.Semaphore(0)
        self.pending: Optional[Report] = None
        self.finished = False

        self.bus = EventBus()
        self.bus.subscribe(None, self._on_engine_event)
        registry = build_registry(compiled, self)
        self.scheduler = Scheduler(registry, self.bus, SemaphorePolicy(limit=1))

        self.task: Optional[asyncio.Task] = None
        self.ticker: Optional[asyncio.Task] = None

    # ---- lifecycle ----

    def launch(self) -> None:
        loop = asyncio.get_running_loop()
        self.task = loop.create_task(self._runner())
        if self.auto:
            self._start_ticker()

    def cancel(self) -> None:
        """Reset/disconnect: stop everything, emit nothing more."""
        self.finished = True
        self._stop_ticker()
        if self.task is not None:
            self.task.cancel()

    async def _runner(self) -> None:
        try:
            await self.scheduler.run(self.compiled.graph, initial_payload={})
        except asyncio.CancelledError:
            if not self.finished:
                raise
        except Exception as exc:  # engine-level failure mid-run
            if not self.finished:
                self._finish_engine_error(exc)
        else:
            if not self.finished:
                # The engine ran out of work without any block halting —
                # should be unreachable for well-formed flows.
                rep = self.pending
                self.pending = None
                if rep is not None:
                    self._finish(Report(rep.node_id, rep.port,
                                        rep.logs + [("err", "The flow stopped unexpectedly.")],
                                        rep.vars, rep.step, "error"))
                else:
                    self._finish(Report(self.compiled.flow.entry, None,
                                        [("err", "The flow stopped unexpectedly.")],
                                        dict(self.vars), self.steps, "error"))

    def _finish_engine_error(self, exc: Exception) -> None:
        rep = self.pending
        self.pending = None
        message = ("err", f"The LoopGraph engine stopped this flow: {exc}")
        if rep is not None:
            self._finish(Report(rep.node_id, rep.port, rep.logs + [message],
                                rep.vars, rep.step, "error"))
        else:
            self._finish(Report(self.compiled.flow.entry, None, [message],
                                dict(self.vars), self.steps, "error"))

    # ---- run-context API (used by compiled handlers) ----

    async def acquire_credit(self) -> None:
        await self.credits.acquire()

    def record(self, report: Report) -> None:
        if self.finished:
            return
        if report.halt is not None:
            self._finish(report)
        else:
            self.pending = report

    # ---- engine observation ----

    async def _on_engine_event(self, event: Event) -> None:
        if self.finished or event.type is not EventType.NODE_SCHEDULED:
            return
        rep = self.pending
        if rep is None:
            # First scheduling of the entry node: the client already
            # highlights `entry` from the `started` message.
            return
        self.pending = None
        edge = self.compiled.edge_map.get((rep.node_id, rep.port))
        # `next` comes from the ENGINE's scheduling decision; edgeId stays the
        # static (executed, port) edge per PROTOCOL.md.
        self.session.send({
            "type": "tick",
            "runId": self.run_id,
            "executed": rep.node_id,
            "port": rep.port,
            "next": event.node_id,
            "edgeId": edge[0] if edge else None,
            "step": rep.step,
            "logs": _logs_json(rep.logs),
            "vars": _json_vars(rep.vars),
        })

    def _finish(self, report: Report) -> None:
        self.finished = True
        self._stop_ticker()
        self.session.send({
            "type": "finished",
            "runId": self.run_id,
            "reason": report.halt,
            "executed": report.node_id,
            "port": report.port,
            "step": report.step,
            "logs": _logs_json(report.logs),
            "vars": _json_vars(report.vars),
        })
        if self.task is not None:
            # Stop the engine (it may still want to schedule more nodes, e.g.
            # after the step cap or a flow error).
            self.task.cancel()

    # ---- pacing controls ----

    def _start_ticker(self) -> None:
        self._stop_ticker()
        self.ticker = asyncio.get_running_loop().create_task(self._tick_loop())

    def _stop_ticker(self) -> None:
        if self.ticker is not None:
            self.ticker.cancel()
            self.ticker = None

    async def _tick_loop(self) -> None:
        while True:
            await asyncio.sleep(SPEEDS[self.speed] / 1000.0)
            self.credits.release()

    def step(self) -> None:
        self.auto = False
        self._stop_ticker()
        if not self.finished:
            self.credits.release()

    def pause(self) -> None:
        self.auto = False
        self._stop_ticker()

    def resume(self) -> None:
        if self.finished:
            return
        self.auto = True
        self._start_ticker()

    def set_speed(self, speed: int) -> None:
        self.speed = speed
        if self.auto and not self.finished:
            self._start_ticker()  # restart the interval, like the prototype


class Session:
    """Per-socket actor: parses client messages, owns the active Run."""

    def __init__(self, outbox: "asyncio.Queue[Dict[str, Any]]"):
        self.outbox = outbox
        self.run: Optional[Run] = None

    def send(self, message: Dict[str, Any]) -> None:
        self.outbox.put_nowait(message)

    def error(self, message: str) -> None:
        self.send({"type": "error", "message": message})

    def reset(self) -> None:
        if self.run is not None:
            self.run.cancel()
            self.run = None

    def shutdown(self) -> None:
        self.reset()

    # ---- message dispatch ----

    def handle_raw(self, raw: str) -> None:
        # A malformed frame must never kill the receive loop: json.loads can
        # raise RecursionError on deeply-nested input (not just JSONDecodeError)
        # and dispatch could fail on adversarial shapes — catch everything,
        # reply with a friendly error, keep the socket alive.
        try:
            try:
                message = json.loads(raw)
            except Exception:
                self.error("Couldn’t read that message — it isn’t valid JSON.")
                return
            if not isinstance(message, dict):
                self.error('Messages must be JSON objects like {"type": "step"}.')
                return
            self.handle(message)
        except Exception:
            self.error("Something went wrong handling that message — "
                       "please try again.")

    def handle(self, message: Dict[str, Any]) -> None:
        mtype = message.get("type")
        if mtype == "start":
            self._handle_start(message)
        elif mtype == "step":
            if self.run is not None:
                self.run.step()
        elif mtype == "pause":
            if self.run is not None:
                self.run.pause()
        elif mtype == "resume":
            if self.run is not None:
                self.run.resume()
        elif mtype == "set_speed":
            speed = _parse_speed(message.get("speed"))
            if speed is None:
                self.error("Speed must be 0 (0.5×), 1 (1×) or 2 (2×).")
                return
            if self.run is not None:
                self.run.set_speed(speed)
        elif mtype == "reset":
            self.reset()
        else:
            self.error(f'Unknown message type "{mtype}".')

    def _handle_start(self, message: Dict[str, Any]) -> None:
        mode = message.get("mode", "run")
        if mode not in ("run", "step"):
            self.error('The start mode must be "run" or "step".')
            return
        speed = _parse_speed(message.get("speed", 1))
        if speed is None:
            self.error("Speed must be 0 (0.5×), 1 (1×) or 2 (2×).")
            return
        if "flow" not in message:
            self.error('The start message needs a "flow" — the flowground.v1 JSON.')
            return
        run_id = message.get("runId")
        if run_id is not None and (
                not isinstance(run_id, str) or len(run_id) > RUN_ID_MAX_LEN):
            self.error("The runId must be a string of at most "
                       f"{RUN_ID_MAX_LEN} characters.")
            return
        try:
            flow = parse_flow(message.get("flow"))
            compiled = compile_flow(flow)
        except FlowValidationError as exc:
            self.error(" ".join(exc.errors))
            return

        self.reset()  # start while a run is active = implicit reset
        run = Run(self, compiled, mode, speed, run_id)
        self.run = run
        self.send({
            "type": "started",
            "runId": run_id,
            "entry": flow.entry,
            "mode": mode,
            "logs": [{
                "kind": "info",
                "text": "Run started" if mode == "run"
                        else "Stepping — press Step for each move",
            }],
        })
        run.launch()


def _parse_speed(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int) and 0 <= value < len(SPEEDS):
        return value
    return None
