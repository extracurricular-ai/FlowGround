import math

import pytest
from loopgraph.bus.eventbus import EventBus
from loopgraph.concurrency import SemaphorePolicy
from loopgraph.core.types import NodeKind
from loopgraph.scheduler.scheduler import Scheduler

from app.compiler import (_fn_double, _fn_square, _loop_times, build_registry,
                          compile_flow)
from app.schema import FlowValidationError, parse_flow

from flowdefs import (edge, flow, node, self_loop_flow, shared_loops_flow,
                      starter_flow)

STARTER_ORDER = ["n1", "n2", "n3", "n4", "n5", "n6", "n7",
                 "n5", "n6", "n7", "n5", "n6", "n7", "n5", "n8"]


def test_starter_flow_compiles():
    compiled = compile_flow(parse_flow(starter_flow()))
    graph = compiled.graph
    assert set(graph.nodes) == {f"n{i}" for i in range(1, 9)}
    # kind mapping
    assert graph.nodes["n1"].kind is NodeKind.TASK
    assert graph.nodes["n5"].kind is NodeKind.SWITCH
    assert graph.nodes["n8"].kind is NodeKind.TERMINAL
    # loop headers need partial-upstream readiness (n5 has 2 incoming edges)
    assert graph.nodes["n5"].allow_partial_upstream is True
    # switch edges carry route metadata for the engine's router
    assert graph.edges["e5"].metadata["route"] == "repeat"
    assert graph.edges["e8"].metadata["route"] == "done"
    assert "route" not in graph.edges["e1"].metadata
    # static edge map
    assert compiled.edge_map[("n5", "repeat")] == ("e5", "n6")
    assert compiled.edge_map[("n5", "done")] == ("e8", "n8")
    assert compiled.edge_map[("n1", "out")] == ("e1", "n2")
    assert ("n8", "out") not in compiled.edge_map


def test_kind_block_mismatch_rejected():
    bad = starter_flow()
    bad["nodes"][4] = node("n5", "loop", {"times": "3"}, kind="TASK")
    with pytest.raises(FlowValidationError) as exc:
        parse_flow(bad)
    assert any('"loop" block (n5) must have kind SWITCH' in e
               for e in exc.value.errors)


def test_unknown_block_rejected():
    bad = flow("n1", [node("n1", "start"),
                      {"id": "n2", "kind": "TASK", "block": "teleport",
                       "config": {}}],
               [edge("e1", "n1", "out", "n2")])
    with pytest.raises(FlowValidationError) as exc:
        parse_flow(bad)
    assert any('Unknown block type "teleport"' in e for e in exc.value.errors)


def test_bad_port_and_duplicate_port_rejected():
    bad = starter_flow()
    bad["edges"].append(edge("e9", "n3", "done", "n8"))
    with pytest.raises(FlowValidationError) as exc:
        parse_flow(bad)
    assert any('has no "done" arrow' in e for e in exc.value.errors)

    dup = starter_flow()
    dup["edges"].append(edge("e9", "n1", "out", "n8"))
    with pytest.raises(FlowValidationError) as exc:
        parse_flow(dup)
    assert any("connected twice" in e for e in exc.value.errors)


def test_loopgraph_self_loop_rejection_is_friendly():
    with pytest.raises(FlowValidationError) as exc:
        compile_flow(parse_flow(self_loop_flow()))
    assert any("straight back into itself" in e for e in exc.value.errors)


def test_loopgraph_shared_loops_rejection_is_friendly():
    with pytest.raises(FlowValidationError) as exc:
        compile_flow(parse_flow(shared_loops_flow()))
    assert any("loops that share blocks" in e for e in exc.value.errors)


# ---------- JS Number() coercion in block semantics ----------

def test_loop_times_infinity_is_not_clamped():
    # JS: Math.max(0, Math.floor(Number('Infinity') || 0)) === Infinity —
    # the loop must run until the step cap, not zero times.
    assert _loop_times("Infinity") == math.inf
    assert _loop_times("+Infinity") == math.inf
    assert _loop_times("-Infinity") == 0
    assert _loop_times("NaN") == 0
    assert _loop_times("banana") == 0
    assert _loop_times(None) == 0
    assert _loop_times("") == 0
    assert _loop_times("3.9") == 3
    assert _loop_times("-5") == 0
    assert _loop_times("1e2") == 100
    assert _loop_times("0x10") == 16


def test_fn_double_of_string_is_nan_not_error():
    # JS: 'Ada' * 2 → NaN; the NaN must flow into vars without erroring.
    assert math.isnan(_fn_double("Ada"))
    assert math.isnan(_fn_square("Ada"))
    assert _fn_double("3") == 6.0
    assert _fn_double("") == 0.0          # Number('') → 0
    assert _fn_square("0x10") == 256.0    # Number('0x10') → 16


class StubCtx:
    """Run context with an always-open credit gate."""

    def __init__(self):
        self.vars = {}
        self.loop_counts = {}
        self.steps = 0
        self.reports = []

    async def acquire_credit(self):
        return None

    def record(self, report):
        self.reports.append(report)


async def test_real_scheduler_executes_starter_flow_in_order():
    """Drive the compiled graph through the actual LoopGraph Scheduler and
    check the engine's real execution order."""
    compiled = compile_flow(parse_flow(starter_flow()))
    ctx = StubCtx()
    registry = build_registry(compiled, ctx)
    scheduler = Scheduler(registry, EventBus(), SemaphorePolicy(limit=1))
    await scheduler.run(compiled.graph, initial_payload={})

    assert [r.node_id for r in ctx.reports] == STARTER_ORDER
    assert ctx.reports[-1].halt == "end"
    assert ctx.reports[-1].vars == {"name": "Ada", "lap": 4}
    ports = [r.port for r in ctx.reports]
    assert ports[4] == "repeat" and ports[13] == "done" and ports[14] is None
