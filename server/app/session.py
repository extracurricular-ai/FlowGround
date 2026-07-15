"""Run-session actor for the ``/api/runs`` WebSocket.

One :class:`Session` per socket; at most one active :class:`Run`.  A Run owns:

- the asyncio task executing the real LoopGraph ``Scheduler.run``,
- the credit gate that paces execution (auto mode releases one credit every
  ``SPEEDS[speed]`` ms; step mode releases one credit per ``step`` message),
- the outbound message queue (shared with the socket's sender task).

Fidelity: every ``tick`` is emitted the moment a node's real handler
completes and calls :meth:`Run.record` — i.e. only after the engine's own
credit-gated dispatch actually ran that node, never before. The ``next``
field is the real activated edge's target (per LoopGraph's documented
deterministic, graph-definition-order dispatch, a (node, port) pair maps to
exactly one edge by construction, so this is not a prediction). This
replaced an earlier design that paired each report with the *following*
``NODE_SCHEDULED`` event: that pairing broke for a genuine merge (two
branches both completing before their shared ``AGGREGATE`` target is
scheduled just once) — a 1:1 report↔event assumption that fan-out/fan-in
topologies violate. Emitting immediately at completion never drops or
misattributes a report, for any topology.
"""

from __future__ import annotations

import asyncio
import json
import math
from typing import Any, Dict, List, Optional, Tuple

from loopgraph.bus.eventbus import EventBus
from loopgraph.concurrency import SemaphorePolicy
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
                 mode: str, speed: int, run_id: Optional[str] = None,
                 llm: Optional[Dict[str, str]] = None):
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
        #: global AI settings (apiKey/baseUrl/mode/model) for llm_generate/
        #: llm_judge blocks — a sibling of "flow" on the start message, NEVER
        #: part of the flow itself, so an exported/pasted flow never carries
        #: a plaintext key (PROTOCOL.md "llm" field).
        self.llm: Dict[str, str] = llm or {}

        # A single-slot gate, not a counting Semaphore: at most one credit is
        # ever "pending" at a time. With a Semaphore, the ticker keeps
        # release()-ing every SPEEDS[speed] ms regardless of whether the
        # previous credit has been claimed yet — harmless for the original
        # blocks (sub-millisecond handlers) but wrong once a handler can
        # genuinely take a while (llm_generate/llm_judge's network call):
        # credits would bank up while it's in flight, then the scheduler
        # burns through several already-banked credits back-to-back the
        # moment it resolves, bursting through several nodes with no visible
        # pacing between them — the opposite of "watch it run at your chosen
        # speed". set() on an already-set Event is a no-op, so this can never
        # accumulate past one.
        self._credit_ready = asyncio.Event()
        #: the most recently recorded report — only used by the "engine
        #: stopped without a proper halt" fallback paths below.
        self._last_report: Optional[Report] = None
        self.finished = False

        self.bus = EventBus()
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
                rep = self._last_report
                if rep is not None:
                    self._finish(Report(rep.node_id, rep.port,
                                        rep.logs + [("err", "The flow stopped unexpectedly.")],
                                        rep.vars, rep.step, "error"))
                else:
                    self._finish(Report(self.compiled.flow.entry, None,
                                        [("err", "The flow stopped unexpectedly.")],
                                        dict(self.vars), self.steps, "error"))

    def _finish_engine_error(self, exc: Exception) -> None:
        rep = self._last_report
        message = ("err", f"The LoopGraph engine stopped this flow: {exc}")
        if rep is not None:
            self._finish(Report(rep.node_id, rep.port, rep.logs + [message],
                                rep.vars, rep.step, "error"))
        else:
            self._finish(Report(self.compiled.flow.entry, None, [message],
                                dict(self.vars), self.steps, "error"))

    # ---- run-context API (used by compiled handlers) ----

    async def acquire_credit(self) -> None:
        await self._credit_ready.wait()
        self._credit_ready.clear()

    def record(self, report: Report) -> None:
        if self.finished:
            return
        self._last_report = report
        if report.halt is not None:
            self._finish(report)
            return
        for i, (executed, port, edge_id, target) in enumerate(self._activated_edges(report)):
            self.session.send({
                "type": "tick",
                "runId": self.run_id,
                "executed": executed,
                # the node whose HANDLER actually just finished — usually
                # identical to `executed`, but differs for a nested subgraph's
                # own exit transition (`executed` is overridden to the
                # enclosing SUBGRAPH node so its edge can animate). Clients
                # must clear a previously-active edge once ITS target is
                # reached, using `completed`, not `executed` — otherwise the
                # edge leading into a subgraph's inner TERMINAL, whose own
                # completion never appears as `executed` on any tick, can
                # never be recognized as reached and never turns off.
                "completed": report.node_id,
                "port": port,
                "next": target,
                "edgeId": edge_id,
                "step": report.step,
                # only the first tick for a report carries its logs — a
                # fan-out (or two branches converging on one merge) must
                # never narrate the same completion twice.
                "logs": _logs_json(report.logs) if i == 0 else [],
                "vars": _json_vars(report.vars),
            })

    def _activated_edges(
        self, report: Report
    ) -> List[Tuple[str, Optional[str], str, str]]:
        """(executed node id, port, edge id, target node id) for every edge
        this report's node activates. A "split" activates all of its
        out-edges at once; every other block activates exactly the one edge
        for its returned port. ``next``/``executed`` are the real node ids —
        including nested-subgraph ones — so the client can highlight a
        subgraph block's own inner nodes and edges, not just the block
        itself."""
        node_id = report.node_id
        if report.fan_out:
            return [(node_id, port, edge_id, target)
                    for (source, port), (edge_id, target)
                    in self.compiled.edge_map.items() if source == node_id]
        edge = self.compiled.edge_map.get((node_id, report.port))
        if edge is not None:
            return [(node_id, report.port, edge[0], edge[1])]
        # No static out-edge from this exact node: this is a nested
        # subgraph's own "end"/TERMINAL block, which never has out-edges of
        # its own. LoopGraph completes the enclosing SUBGRAPH node with the
        # child's payload and fires ITS downstream edge instead. Report
        # `executed` as the SUBGRAPH node itself, not the raw inner terminal
        # id — LoopGraph's own contract is that "a sub-workflow is just
        # another task" from the parent's perspective, so this is the
        # faithful framing of this transition, and it's also the only one
        # the client can resolve to a real edge (no local edge originates
        # from an inner node's id). This must be the DIRECT parent
        # (parent_scope), not the outermost top-level ancestor (node_scope)
        # — those differ once subgraphs nest two or more levels deep, and
        # using the wrong one would skip the intermediate subgraph's own
        # transition entirely.
        parent = self.compiled.parent_scope.get(node_id)
        if parent is not None:
            parent_node = self.compiled.nodes.get(parent)
            if parent_node is not None:
                for port in parent_node.ports:
                    edge = self.compiled.edge_map.get((parent, port))
                    if edge is not None:
                        return [(parent, port, edge[0], edge[1])]
        return []

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
            self._credit_ready.set()

    def step(self) -> None:
        self.auto = False
        self._stop_ticker()
        if not self.finished:
            self._credit_ready.set()

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
        llm = _parse_llm_settings(message.get("llm"))

        self.reset()  # start while a run is active = implicit reset
        run = Run(self, compiled, mode, speed, run_id, llm)
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


#: keys the compiled llm_generate/llm_judge handlers actually read
#: (server/app/compiler.py's ``_call_llm_or_block_error``).
_LLM_SETTING_KEYS = ("apiKey", "baseUrl", "mode", "model")


def _parse_llm_settings(value: Any) -> Dict[str, str]:
    """Best-effort read of the optional "llm" field: malformed input is
    silently dropped to {} rather than failing the whole start — these
    blocks only fail (with a friendly per-node message) if a flow actually
    uses one and the settings turn out to be missing/wrong."""
    if not isinstance(value, dict):
        return {}
    return {k: v for k, v in value.items()
           if k in _LLM_SETTING_KEYS and isinstance(v, str)}
