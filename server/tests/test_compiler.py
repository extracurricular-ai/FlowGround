import math

import pytest
from loopgraph.bus.eventbus import EventBus
from loopgraph.concurrency import SemaphorePolicy
from loopgraph.core.types import NodeKind
from loopgraph.scheduler.scheduler import Scheduler

from app.compiler import (_fn_double, _fn_square, _loop_times, build_registry,
                          compile_flow)
from app.schema import FlowValidationError, parse_flow

from flowdefs import (doubly_nested_subgraph_flow, duplicate_id_subgraph_flow,
                      edge, flow, node, self_loop_flow, shared_loops_flow,
                      split_merge_flow, split_merge_loop_subgraph_flow,
                      starter_flow, subgraph_flow, unconnected_subgraph_flow)

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

    def __init__(self, llm=None):
        self.vars = {}
        self.loop_counts = {}
        self.steps = 0
        self.reports = []
        self.llm = llm or {}

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


# ---------- split / merge / subgraph ----------

async def _run(flow_def):
    compiled = compile_flow(parse_flow(flow_def))
    ctx = StubCtx()
    registry = build_registry(compiled, ctx)
    scheduler = Scheduler(registry, EventBus(), SemaphorePolicy(limit=1))
    await scheduler.run(compiled.graph, initial_payload={})
    return compiled, ctx


def test_split_compiles_as_fan_out_task():
    compiled = compile_flow(parse_flow(split_merge_flow()))
    graph = compiled.graph
    assert graph.nodes["n3"].kind is NodeKind.TASK  # split: TASK, not SWITCH
    assert graph.nodes["n6"].kind is NodeKind.AGGREGATE  # merge
    assert compiled.edge_map[("n3", "a")] == ("e3", "n4")
    assert compiled.edge_map[("n3", "b")] == ("e4", "n5")
    # split's out-edges carry no "route" metadata — both fire unconditionally.
    assert "route" not in graph.edges["e3"].metadata
    assert "route" not in graph.edges["e4"].metadata


async def test_split_merge_runs_both_branches_and_joins():
    compiled, ctx = await _run(split_merge_flow())
    order = [r.node_id for r in ctx.reports]
    # both branches run (deterministic graph-definition order), then merge
    assert order == ["n1", "n2", "n3", "n4", "n5", "n6", "n7", "n8"]
    split_report = ctx.reports[2]
    assert split_report.fan_out is True
    merge_report = ctx.reports[5]
    assert merge_report.fan_out is False
    assert ctx.reports[-1].vars == {"num": 4.0, "squared": 16.0}
    assert ctx.reports[-1].halt == "end"


def test_subgraph_compiles_nested_graph_and_scopes_ids():
    compiled = compile_flow(parse_flow(subgraph_flow()))
    graph = compiled.graph
    assert graph.nodes["n3"].kind is NodeKind.SUBGRAPH
    assert graph.nodes["n3"].handler == ""
    assert "graph" in graph.nodes["n3"].config
    child = graph.nodes["n3"].config["graph"]
    assert {n["id"] for n in child["nodes"]} == \
        {"sg_start", "sg_loop", "sg_say", "sg_end"}
    # every nested node/edge is registered globally, and scoped to n3
    assert set(compiled.nodes) == {"n1", "n2", "n3", "n4",
                                   "sg_start", "sg_loop", "sg_say", "sg_end"}
    assert compiled.node_scope["sg_loop"] == "n3"
    assert compiled.node_scope["n2"] == "n2"
    assert compiled.top_level_ids == {"n1", "n2", "n3", "n4"}
    # the nested "end" block does NOT halt the whole run
    assert "sg_end" not in compiled.top_level_ids


async def test_subgraph_loop_reenters_child_each_visit_without_halting():
    compiled, ctx = await _run(subgraph_flow())
    order = [r.node_id for r in ctx.reports]
    # outer loop visits the subgraph twice; each visit runs the inner 2x loop
    assert order.count("n3") == 0  # subgraph node itself has no handler
    assert order.count("sg_start") == 2
    assert order.count("sg_say") == 4  # 2 inner rounds × 2 outer visits
    # only the OUTERMOST "end" halts the run
    halts = [r.halt for r in ctx.reports]
    assert halts.count("end") == 1
    assert ctx.reports[-1].node_id == "n4"
    assert ctx.reports[-1].halt == "end"
    # the nested end block completed normally, without halting
    sg_end_reports = [r for r in ctx.reports if r.node_id == "sg_end"]
    assert len(sg_end_reports) == 2
    assert all(r.halt is None for r in sg_end_reports)


async def test_split_merge_loop_subgraph_full_demo_shape():
    """The example-demo topology end to end: fan-out+merge -> loop whose
    body is a subgraph node that is itself a loop."""
    compiled, ctx = await _run(split_merge_loop_subgraph_flow())
    order = [r.node_id for r in ctx.reports]
    assert order[:3] == ["n1", "n2", "n3"]
    assert set(order[3:5]) == {"n4", "n5"}  # both branches, order deterministic
    assert order[5] == "n6"  # merge
    assert order.count("n7") == 3  # 2x "repeat" + 1x "done"
    assert order.count("sg_start") == 2  # subgraph visited twice
    assert ctx.reports[-1].node_id == "n9"
    assert ctx.reports[-1].halt == "end"


def test_duplicate_id_across_scopes_is_rejected():
    with pytest.raises(FlowValidationError) as exc:
        compile_flow(parse_flow(duplicate_id_subgraph_flow()))
    assert any('share the id "n2"' in e for e in exc.value.errors)


def test_unconnected_subgraph_out_port_rejected_at_compile_time():
    # A subgraph node has no handler of its own, so nothing at runtime ever
    # checks its "out" port the way _make_handler does for every other
    # block — this must be caught at compile time instead.
    with pytest.raises(FlowValidationError) as exc:
        compile_flow(parse_flow(unconnected_subgraph_flow()))
    assert any('"out" arrow of this Subgraph block (n2) isn' in e
              for e in exc.value.errors)


def test_doubly_nested_subgraph_scopes_are_correct():
    compiled = compile_flow(parse_flow(doubly_nested_subgraph_flow()))
    # node_scope flattens all the way to the top-level ancestor...
    assert compiled.node_scope["b_end"] == "n2"
    assert compiled.node_scope["a_mid"] == "n2"
    # ...but parent_scope stays ONE level up, which is what matters for
    # resolving "what fires next" when a's own body's b_end completes.
    assert compiled.parent_scope["b_end"] == "a_sub"
    assert compiled.parent_scope["a_mid"] == "n2"
    assert compiled.parent_scope["a_start"] == "n2"
    assert "n1" not in compiled.parent_scope  # top-level ids have no parent


async def test_doubly_nested_subgraph_exit_ticks_resolve_to_direct_parent():
    """The regression this guards: b_end (2 levels deep) completing must be
    reported via its DIRECT parent (a_sub, whose own edge goes -> a_mid),
    NOT via the flattened top-level ancestor n2 (whose edge goes -> n3) —
    that would skip a_sub's real intermediate transition entirely. Ticks
    carry real node ids throughout (no remapping), so the client can render
    each nested level's own structure."""
    from app.session import Run, Session

    compiled = compile_flow(parse_flow(doubly_nested_subgraph_flow()))
    sent = []

    class StubSession:
        def send(self, message):
            sent.append(message)

    run = Run(StubSession(), compiled, "run", speed=2, run_id="r1")
    run.credits._value = 10**6  # let every acquire_credit() through immediately
    await run.scheduler.run(compiled.graph, initial_payload={})

    ticks = [t for t in sent if t["type"] == "tick"]
    by_executed = {}
    for t in ticks:
        by_executed.setdefault(t["executed"], []).append(t)

    # b_end's completion is reported as its DIRECT parent "a_sub" firing its
    # own real edge (-> a_mid) — not as "n2" (which would incorrectly skip
    # straight to n2's own edge, -> n3).
    assert "a_sub" in by_executed
    assert "b_end" not in by_executed  # b_end itself never resolves an edge
    a_sub_tick = by_executed["a_sub"][0]
    assert (a_sub_tick["port"], a_sub_tick["next"]) == ("out", "a_mid")
    assert a_sub_tick["edgeId"]
    # `completed` must still be the literal "b_end" — a client clears the
    # edge INTO b_end using this, not `executed` ("a_sub"); otherwise that
    # edge can never be recognized as reached and animates forever.
    assert a_sub_tick["completed"] == "b_end"

    # a_end (only 1 level deep) resolves via its direct parent "n2", whose
    # real edge correctly goes -> n3.
    n2_tick = by_executed["n2"][0]
    assert (n2_tick["port"], n2_tick["next"]) == ("out", "n3")
    assert n2_tick["completed"] == "a_end"

    # ordinary nested nodes carry their own true ids/edges throughout.
    assert by_executed["a_start"][0]["next"] == "a_sub"
    assert by_executed["b_start"][0]["next"] == "b_end"

    finished = [t for t in sent if t["type"] == "finished"][0]
    assert finished["reason"] == "end"
