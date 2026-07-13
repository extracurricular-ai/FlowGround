"""flowground.v1 fixtures used across the test files."""

import json

KIND_OF = {
    "start": "TASK", "ask": "TASK", "say": "TASK", "set": "TASK",
    "iff": "SWITCH", "loop": "SWITCH", "fn": "TASK", "end": "TERMINAL",
    "split": "TASK", "merge": "AGGREGATE", "subgraph": "SUBGRAPH",
}


def node(nid, block, config=None, x=0, y=0, kind=None):
    return {
        "id": nid,
        "kind": kind if kind is not None else KIND_OF[block],
        "block": block,
        "config": dict(config or {}),
        "position": {"x": x, "y": y},
    }


def edge(eid, source, port, target):
    return {"id": eid, "source": source, "port": port, "target": target}


def flow(entry, nodes, edges):
    return {"format": "flowground.v1", "entry": entry,
            "nodes": nodes, "edges": edges}


def starter_flow():
    """The prototype's initial canvas state."""
    return flow("n1", [
        node("n1", "start", {}, 360, 40),
        node("n2", "ask", {"name": "name", "value": "Ada"}, 360, 150),
        node("n3", "say", {"text": "Hello, {name}!"}, 360, 260),
        node("n4", "set", {"name": "lap", "expr": "1"}, 360, 370),
        node("n5", "loop", {"times": "3"}, 360, 480),
        node("n6", "say", {"text": "Lap {lap}"}, 120, 610),
        node("n7", "set", {"name": "lap", "expr": "lap + 1"}, 120, 720),
        node("n8", "end", {}, 600, 610),
    ], [
        edge("e1", "n1", "out", "n2"),
        edge("e2", "n2", "out", "n3"),
        edge("e3", "n3", "out", "n4"),
        edge("e4", "n4", "out", "n5"),
        edge("e5", "n5", "repeat", "n6"),
        edge("e6", "n6", "out", "n7"),
        edge("e7", "n7", "out", "n5"),
        edge("e8", "n5", "done", "n8"),
    ])


def iff_flow(cond):
    return flow("n1", [
        node("n1", "start"),
        node("n2", "set", {"name": "count", "expr": "1"}),
        node("n3", "iff", {"cond": cond}),
        node("n4", "say", {"text": "big"}),
        node("n5", "say", {"text": "small"}),
        node("n6", "end"),
    ], [
        edge("e1", "n1", "out", "n2"),
        edge("e2", "n2", "out", "n3"),
        edge("e3", "n3", "true", "n4"),
        edge("e4", "n3", "false", "n5"),
        edge("e5", "n4", "out", "n6"),
        edge("e6", "n5", "out", "n6"),
    ])


def while_flow():
    return flow("n1", [
        node("n1", "start"),
        node("n2", "set", {"name": "lap", "expr": "1"}),
        node("n3", "loop", {"mode": "while", "cond": "lap < 3"}),
        node("n4", "set", {"name": "lap", "expr": "lap + 1"}),
        node("n5", "end"),
    ], [
        edge("e1", "n1", "out", "n2"),
        edge("e2", "n2", "out", "n3"),
        edge("e3", "n3", "repeat", "n4"),
        edge("e4", "n4", "out", "n3"),
        edge("e5", "n3", "done", "n5"),
    ])


def fn_flow():
    return flow("n1", [
        node("n1", "start"),
        node("n2", "set", {"name": "x", "expr": "3"}),
        node("n3", "fn", {"fn": "double", "arg": "x", "result": "d"}),
        node("n4", "fn", {"fn": "square", "arg": "d", "result": "s"}),
        node("n5", "set", {"name": "w", "expr": "hi"}),
        node("n6", "fn", {"fn": "shout", "arg": "w", "result": "loud"}),
        node("n7", "end"),
    ], [
        edge("e1", "n1", "out", "n2"),
        edge("e2", "n2", "out", "n3"),
        edge("e3", "n3", "out", "n4"),
        edge("e4", "n4", "out", "n5"),
        edge("e5", "n5", "out", "n6"),
        edge("e6", "n6", "out", "n7"),
    ])


def unconnected_flow():
    """iff whose chosen "true" port has no edge."""
    return flow("n1", [
        node("n1", "start"),
        node("n2", "iff", {"cond": "true"}),
        node("n3", "say", {"text": "never"}),
        node("n4", "end"),
    ], [
        edge("e1", "n1", "out", "n2"),
        edge("e2", "n2", "false", "n3"),
        edge("e3", "n3", "out", "n4"),
    ])


def bad_expr_flow():
    return flow("n1", [
        node("n1", "start"),
        node("n2", "iff", {"cond": "nope + 1"}),
        node("n3", "say", {"text": "a"}),
        node("n4", "say", {"text": "b"}),
    ], [
        edge("e1", "n1", "out", "n2"),
        edge("e2", "n2", "true", "n3"),
        edge("e3", "n2", "false", "n4"),
    ])


def empty_expr_flow():
    return flow("n1", [
        node("n1", "start"),
        node("n2", "set", {"name": "x", "expr": ""}),
        node("n3", "end"),
    ], [
        edge("e1", "n1", "out", "n2"),
        edge("e2", "n2", "out", "n3"),
    ])


def infinite_flow():
    """while-true loop: hits the 150-step cap."""
    return flow("n1", [
        node("n1", "start"),
        node("n2", "loop", {"mode": "while", "cond": "true"}),
        node("n3", "say", {"text": "again"}),
        node("n4", "end"),
    ], [
        edge("e1", "n1", "out", "n2"),
        edge("e2", "n2", "repeat", "n3"),
        edge("e3", "n3", "out", "n2"),
        edge("e4", "n2", "done", "n4"),
    ])


def infinity_loop_flow():
    """count-mode loop with times='Infinity': loops until the 150-step cap."""
    return flow("n1", [
        node("n1", "start"),
        node("n2", "loop", {"times": "Infinity"}),
        node("n3", "say", {"text": "again"}),
        node("n4", "end"),
    ], [
        edge("e1", "n1", "out", "n2"),
        edge("e2", "n2", "repeat", "n3"),
        edge("e3", "n3", "out", "n2"),
        edge("e4", "n2", "done", "n4"),
    ])


def nan_fn_flow():
    """double('Ada') is NaN in JS; the NaN flows into vars and the following
    iff condition over it routes to the false port (NaN > 0 is false)."""
    return flow("n1", [
        node("n1", "start"),
        node("n2", "ask", {"name": "name", "value": "Ada"}),
        node("n3", "fn", {"fn": "double", "arg": "name", "result": "d"}),
        node("n4", "iff", {"cond": "d > 0"}),
        node("n5", "say", {"text": "positive"}),
        node("n6", "say", {"text": "not positive"}),
        node("n7", "end"),
    ], [
        edge("e1", "n1", "out", "n2"),
        edge("e2", "n2", "out", "n3"),
        edge("e3", "n3", "out", "n4"),
        edge("e4", "n4", "true", "n5"),
        edge("e5", "n4", "false", "n6"),
        edge("e6", "n5", "out", "n7"),
        edge("e7", "n6", "out", "n7"),
    ])


def shared_loops_flow():
    """Two cycles through the same iff node — LoopGraph rejects this."""
    return flow("n1", [
        node("n1", "start"),
        node("n2", "iff", {"cond": "true"}),
        node("n3", "say", {"text": "a"}),
        node("n4", "say", {"text": "b"}),
    ], [
        edge("e1", "n1", "out", "n2"),
        edge("e2", "n2", "true", "n3"),
        edge("e3", "n2", "false", "n4"),
        edge("e4", "n3", "out", "n2"),
        edge("e5", "n4", "out", "n2"),
    ])


def split_merge_flow():
    """start -> split into two branches -> merge -> end."""
    return flow("n1", [
        node("n1", "start"),
        node("n2", "set", {"name": "num", "expr": "4"}),
        node("n3", "split"),
        node("n4", "say", {"text": "branch a"}),
        node("n5", "fn", {"fn": "square", "arg": "num", "result": "squared"}),
        node("n6", "merge"),
        node("n7", "say", {"text": "merged, squared={squared}"}),
        node("n8", "end"),
    ], [
        edge("e1", "n1", "out", "n2"),
        edge("e2", "n2", "out", "n3"),
        edge("e3", "n3", "a", "n4"),
        edge("e4", "n3", "b", "n5"),
        edge("e5", "n4", "out", "n6"),
        edge("e6", "n5", "out", "n6"),
        edge("e7", "n6", "out", "n7"),
        edge("e8", "n7", "out", "n8"),
    ])


def inner_loop_subflow(prefix="sg"):
    """A tiny 2-round count-loop, in nested flowground.v1 shape — the body
    of a "subgraph" block's config["graph"] (JSON-encoded)."""
    return flow(f"{prefix}_start", [
        node(f"{prefix}_start", "start"),
        node(f"{prefix}_loop", "loop", {"mode": "count", "times": "2"}),
        node(f"{prefix}_say", "say", {"text": "inner round"}),
        node(f"{prefix}_end", "end"),
    ], [
        edge(f"{prefix}_e1", f"{prefix}_start", "out", f"{prefix}_loop"),
        edge(f"{prefix}_e2", f"{prefix}_loop", "repeat", f"{prefix}_say"),
        edge(f"{prefix}_e3", f"{prefix}_say", "out", f"{prefix}_loop"),
        edge(f"{prefix}_e4", f"{prefix}_loop", "done", f"{prefix}_end"),
    ])


def subgraph_flow():
    """start -> loop(2x) whose body is a subgraph node (itself a 2x loop)
    -> end. Mirrors the frontend's example demo's outer-loop/subgraph shape."""
    return flow("n1", [
        node("n1", "start"),
        node("n2", "loop", {"mode": "count", "times": "2"}),
        node("n3", "subgraph", {"graph": json.dumps(inner_loop_subflow())}),
        node("n4", "end"),
    ], [
        edge("e1", "n1", "out", "n2"),
        edge("e2", "n2", "repeat", "n3"),
        edge("e3", "n3", "out", "n2"),
        edge("e4", "n2", "done", "n4"),
    ])


def split_merge_loop_subgraph_flow():
    """The full example-demo shape: parallel run -> merge -> loop whose body
    is a subgraph node that is itself a loop."""
    return flow("n1", [
        node("n1", "start"),
        node("n2", "set", {"name": "num", "expr": "4"}),
        node("n3", "split"),
        node("n4", "say", {"text": "branch a"}),
        node("n5", "fn", {"fn": "square", "arg": "num", "result": "squared"}),
        node("n6", "merge"),
        node("n7", "loop", {"mode": "count", "times": "2"}),
        node("n8", "subgraph", {"graph": json.dumps(inner_loop_subflow())}),
        node("n9", "end"),
    ], [
        edge("e1", "n1", "out", "n2"),
        edge("e2", "n2", "out", "n3"),
        edge("e3", "n3", "a", "n4"),
        edge("e4", "n3", "b", "n5"),
        edge("e5", "n4", "out", "n6"),
        edge("e6", "n5", "out", "n6"),
        edge("e7", "n6", "out", "n7"),
        edge("e8", "n7", "repeat", "n8"),
        edge("e9", "n8", "out", "n7"),
        edge("e10", "n7", "done", "n9"),
    ])


def doubly_nested_subgraph_flow():
    """A subgraph node (n2) whose body itself contains a subgraph node
    (a_sub) — exercises parent_scope vs. the flattened node_scope, which
    diverge once nesting is 2+ levels deep."""
    inner_b = flow("b_start", [
        node("b_start", "start"),
        node("b_end", "end"),
    ], [
        edge("be1", "b_start", "out", "b_end"),
    ])
    inner_a = flow("a_start", [
        node("a_start", "start"),
        node("a_sub", "subgraph", {"graph": json.dumps(inner_b)}),
        node("a_mid", "say", {"text": "back in A"}),
        node("a_end", "end"),
    ], [
        edge("ae1", "a_start", "out", "a_sub"),
        edge("ae2", "a_sub", "out", "a_mid"),
        edge("ae3", "a_mid", "out", "a_end"),
    ])
    return flow("n1", [
        node("n1", "start"),
        node("n2", "subgraph", {"graph": json.dumps(inner_a)}),
        node("n3", "end"),
    ], [
        edge("e1", "n1", "out", "n2"),
        edge("e2", "n2", "out", "n3"),
    ])


def unconnected_subgraph_flow():
    """A subgraph block whose "out" port has no edge — must be rejected at
    compile time, since a subgraph node never gets a runtime handler to
    catch this the way every other block does."""
    return flow("n1", [
        node("n1", "start"),
        node("n2", "subgraph", {"graph": json.dumps(inner_loop_subflow())}),
    ], [
        edge("e1", "n1", "out", "n2"),
    ])


def duplicate_id_subgraph_flow():
    """A subgraph block reuses a top-level node id — must be rejected."""
    inner = flow("n2", [
        node("n2", "start"),
        node("t", "end"),
    ], [
        edge("ie1", "n2", "out", "t"),
    ])
    return flow("n1", [
        node("n1", "start"),
        node("n2", "subgraph", {"graph": json.dumps(inner)}),
        node("n3", "end"),
    ], [
        edge("e1", "n1", "out", "n2"),
        edge("e2", "n2", "out", "n3"),
    ])


def self_loop_flow():
    """A loop block arrowed straight back into itself — LoopGraph rejects."""
    return flow("n1", [
        node("n1", "start"),
        node("n2", "loop", {"times": "3"}),
        node("n3", "end"),
    ], [
        edge("e1", "n1", "out", "n2"),
        edge("e2", "n2", "repeat", "n2"),
        edge("e3", "n2", "done", "n3"),
    ])
