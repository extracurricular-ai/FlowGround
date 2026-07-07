"""flowground.v1 fixtures used across the test files."""

KIND_OF = {
    "start": "TASK", "ask": "TASK", "say": "TASK", "set": "TASK",
    "iff": "SWITCH", "loop": "SWITCH", "fn": "TASK", "end": "TERMINAL",
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
