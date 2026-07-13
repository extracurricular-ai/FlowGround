import json

import pytest
from fastapi.testclient import TestClient

from app.main import app

from flowdefs import (bad_expr_flow, empty_expr_flow, fn_flow, iff_flow,
                      infinite_flow, infinity_loop_flow, nan_fn_flow, node,
                      split_merge_loop_subgraph_flow, starter_flow,
                      unconnected_flow, shared_loops_flow, while_flow)

client = TestClient(app)


def receive_strict_json(ws):
    """Receive a frame and parse it as STRICT JSON — bare NaN/Infinity (which
    browsers' JSON.parse rejects) fail the test."""
    text = ws.receive_text()
    return json.loads(
        text,
        parse_constant=lambda c: pytest.fail(f"non-strict JSON constant: {c}"))


def step_run(ws, flow, max_steps=200):
    """start(mode step) + one step per node until finished/error."""
    ws.send_json({"type": "start", "flow": flow, "mode": "step", "speed": 1})
    started = ws.receive_json()
    assert started["type"] == "started", started
    events = []
    for _ in range(max_steps):
        ws.send_json({"type": "step"})
        message = ws.receive_json()
        events.append(message)
        if message["type"] != "tick":
            break
    return started, events


def all_texts(started, events):
    logs = list(started["logs"])
    for e in events:
        logs.extend(e["logs"])
    return [l["text"] for l in logs]


# ---------- the starter flow, step mode ----------

STARTER_ORDER = ["n1", "n2", "n3", "n4", "n5", "n6", "n7",
                 "n5", "n6", "n7", "n5", "n6", "n7", "n5", "n8"]

STARTER_TEXTS = [
    "Stepping — press Step for each move",
    "Flow started",
    'Asked for name → got "Ada"',
    "Hello, Ada!",
    "lap = 1",
    "Loop — round 1 of 3",
    "Lap 1",
    "lap = 2",
    "Loop — round 2 of 3",
    "Lap 2",
    "lap = 3",
    "Loop — round 3 of 3",
    "Lap 3",
    "lap = 4",
    "Loop finished — moving on",
    "Flow finished — nice!",
]


def test_starter_flow_step_mode_full_run():
    with client.websocket_connect("/api/runs") as ws:
        started, events = step_run(ws, starter_flow())

    assert started["entry"] == "n1"
    assert started["mode"] == "step"
    assert started["logs"] == [{"kind": "info",
                                "text": "Stepping — press Step for each move"}]

    assert [e["executed"] for e in events] == STARTER_ORDER
    assert [e["type"] for e in events] == ["tick"] * 14 + ["finished"]
    assert all_texts(started, events) == STARTER_TEXTS

    # tick details
    first = events[0]
    assert (first["port"], first["next"], first["edgeId"], first["step"]) == \
        ("out", "n2", "e1", 1)
    loop_first = events[4]
    assert (loop_first["executed"], loop_first["port"], loop_first["next"],
            loop_first["edgeId"]) == ("n5", "repeat", "n6", "e5")
    assert loop_first["logs"] == [{"kind": "loop", "text": "Loop — round 1 of 3"}]
    loop_done = events[13]
    assert (loop_done["port"], loop_done["next"], loop_done["edgeId"]) == \
        ("done", "n8", "e8")

    # vars snapshots are raw JSON values
    assert events[1]["vars"] == {"name": "Ada"}
    assert events[3]["vars"] == {"name": "Ada", "lap": 1}

    finished = events[-1]
    assert finished["reason"] == "end"
    assert finished["executed"] == "n8"
    assert finished["port"] is None
    assert finished["step"] == 15
    assert finished["logs"] == [{"kind": "ok", "text": "Flow finished — nice!"}]
    assert finished["vars"] == {"name": "Ada", "lap": 4}

    # log kinds match the prototype's set
    assert events[0]["logs"][0]["kind"] == "step"
    assert events[2]["logs"][0]["kind"] == "out"


# ---------- iff: both branches, two runs on one socket ----------

def test_iff_takes_both_branches_across_two_runs():
    with client.websocket_connect("/api/runs") as ws:
        started, events = step_run(ws, iff_flow("count > 3"))
        assert [e["executed"] for e in events] == ["n1", "n2", "n3", "n5", "n6"]
        branch = events[2]
        assert branch["logs"] == [{"kind": "branch",
                                   "text": "Is count > 3?  → no"}]
        assert (branch["port"], branch["next"], branch["edgeId"]) == \
            ("false", "n5", "e4")
        assert events[-1]["reason"] == "end"

        # second, flipped run on the SAME socket
        started, events = step_run(ws, iff_flow("count < 3"))
        assert [e["executed"] for e in events] == ["n1", "n2", "n3", "n4", "n6"]
        branch = events[2]
        assert branch["logs"] == [{"kind": "branch",
                                   "text": "Is count < 3?  → yes"}]
        assert (branch["port"], branch["next"], branch["edgeId"]) == \
            ("true", "n4", "e3")
        assert events[-1]["reason"] == "end"


# ---------- while-mode loop ----------

def test_while_loop_flow():
    with client.websocket_connect("/api/runs") as ws:
        started, events = step_run(ws, while_flow())

    assert [e["executed"] for e in events] == \
        ["n1", "n2", "n3", "n4", "n3", "n4", "n3", "n5"]
    assert all_texts(started, events) == [
        "Stepping — press Step for each move",
        "Flow started",
        "lap = 1",
        "While lap < 3?  → yes — around again",
        "lap = 2",
        "While lap < 3?  → yes — around again",
        "lap = 3",
        "While lap < 3?  → no — loop done",
        "Flow finished — nice!",
    ]
    assert events[-1]["reason"] == "end"
    assert events[-1]["vars"] == {"lap": 3}


# ---------- fn blocks ----------

def test_fn_double_square_shout():
    with client.websocket_connect("/api/runs") as ws:
        started, events = step_run(ws, fn_flow())

    assert all_texts(started, events) == [
        "Stepping — press Step for each move",
        "Flow started",
        "x = 3",
        "d = double(3) → 6",
        "s = square(6) → 36",
        'w = "hi"',  # set falls back to interp; fmt() quotes strings
        'loud = shout("hi") → "HI"',
        "Flow finished — nice!",
    ]
    assert events[-1]["vars"] == \
        {"x": 3, "d": 6, "s": 36, "w": "hi", "loud": "HI"}


# ---------- error cases ----------

def test_unconnected_port_halts_with_error():
    with client.websocket_connect("/api/runs") as ws:
        started, events = step_run(ws, unconnected_flow())

    assert [e["executed"] for e in events] == ["n1", "n2"]
    finished = events[-1]
    assert finished["type"] == "finished"
    assert finished["reason"] == "error"
    assert finished["port"] == "true"
    assert finished["logs"] == [
        {"kind": "branch", "text": "Is true?  → yes"},
        {"kind": "err",
         "text": 'The "true" arrow of this If block isn’t connected — '
                 "drag from its dot to the next block."},
    ]


def test_bad_expression_halts_with_error():
    with client.websocket_connect("/api/runs") as ws:
        started, events = step_run(ws, bad_expr_flow())

    finished = events[-1]
    assert finished["reason"] == "error"
    assert finished["executed"] == "n2"
    # a failed iff eval never decided: port stays null (PROTOCOL.md: the
    # `decider` achievement requires a non-null port on an iff tick)
    assert finished["port"] is None
    assert finished["logs"] == [
        {"kind": "err",
         "text": 'Stuck on the If block: can’t work out "nope + 1" — '
                 "is every variable set first?"},
    ]


def test_empty_expression_halts_with_error():
    with client.websocket_connect("/api/runs") as ws:
        started, events = step_run(ws, empty_expr_flow())

    finished = events[-1]
    assert finished["reason"] == "error"
    assert finished["executed"] == "n2"
    assert finished["logs"] == [
        {"kind": "err",
         "text": "Stuck on the Set variable block: this field is empty"},
    ]


# ---------- step limit ----------

def test_step_limit_hits_150_with_warn():
    with client.websocket_connect("/api/runs") as ws:
        started, events = step_run(ws, infinite_flow(), max_steps=300)

    assert len(events) == 150  # 149 ticks + finished
    assert all(e["type"] == "tick" for e in events[:-1])
    finished = events[-1]
    assert finished["type"] == "finished"
    assert finished["reason"] == "step_limit"
    assert finished["step"] == 150
    assert finished["executed"] == "n2"  # the while-loop switch
    assert finished["logs"] == [
        {"kind": "loop", "text": "While true?  → yes — around again"},
        {"kind": "warn",
         "text": "150 steps and still going — this might be an infinite loop!"},
    ]


# ---------- JS numeric semantics over the wire ----------

def test_nan_fn_result_flows_into_vars_as_strict_json():
    """double('Ada') → NaN lands in vars as {"__js": "NaN"} — every frame is
    strictly-valid JSON — and the following iff over NaN takes the false port."""
    with client.websocket_connect("/api/runs") as ws:
        ws.send_json({"type": "start", "flow": nan_fn_flow(),
                      "mode": "step", "speed": 1})
        assert receive_strict_json(ws)["type"] == "started"
        events = []
        for _ in range(20):
            ws.send_json({"type": "step"})
            message = receive_strict_json(ws)
            events.append(message)
            if message["type"] != "tick":
                break

    assert [e["executed"] for e in events] == \
        ["n1", "n2", "n3", "n4", "n6", "n7"]

    fn_tick = events[2]
    assert fn_tick["logs"] == [
        {"kind": "step", "text": 'd = double("Ada") → NaN'}]
    assert fn_tick["vars"] == {"name": "Ada", "d": {"__js": "NaN"}}

    # NaN > 0 is false in JS → the iff routes to the false port (and DID
    # decide: port is non-null, so the frontend's `decider` fires)
    iff_tick = events[3]
    assert iff_tick["port"] == "false"
    assert iff_tick["logs"] == [{"kind": "branch", "text": "Is d > 0?  → no"}]
    assert events[4]["logs"] == [{"kind": "out", "text": "not positive"}]

    finished = events[-1]
    assert finished["reason"] == "end"
    assert finished["vars"] == {"name": "Ada", "d": {"__js": "NaN"}}


def test_loop_times_infinity_runs_until_step_cap():
    with client.websocket_connect("/api/runs") as ws:
        started, events = step_run(ws, infinity_loop_flow(), max_steps=300)

    first_loop = events[1]
    assert first_loop["executed"] == "n2"
    assert first_loop["logs"] == [
        {"kind": "loop", "text": "Loop — round 1 of Infinity"}]

    finished = events[-1]
    assert finished["type"] == "finished"
    assert finished["reason"] == "step_limit"
    assert finished["step"] == 150
    assert finished["logs"][-1] == {
        "kind": "warn",
        "text": "150 steps and still going — this might be an infinite loop!"}


# ---------- runId echo ----------

def test_run_id_echoed_on_started_tick_finished():
    with client.websocket_connect("/api/runs") as ws:
        ws.send_json({"type": "start", "flow": while_flow(),
                      "mode": "step", "speed": 1, "runId": "r3"})
        started = ws.receive_json()
        assert started["type"] == "started"
        assert started["runId"] == "r3"
        events = []
        for _ in range(20):
            ws.send_json({"type": "step"})
            message = ws.receive_json()
            events.append(message)
            if message["type"] != "tick":
                break
        assert all(e["runId"] == "r3" for e in events)
        assert events[-1]["type"] == "finished"


def test_run_id_absent_is_null():
    with client.websocket_connect("/api/runs") as ws:
        started, events = step_run(ws, while_flow())
        assert started["runId"] is None
        assert all(e["runId"] is None for e in events)


def test_run_id_rejected_when_not_a_short_string():
    with client.websocket_connect("/api/runs") as ws:
        ws.send_json({"type": "start", "flow": while_flow(),
                      "mode": "step", "speed": 1, "runId": "x" * 65})
        message = ws.receive_json()
        assert message["type"] == "error"
        assert "runId" in message["message"]

        ws.send_json({"type": "start", "flow": while_flow(),
                      "mode": "step", "speed": 1, "runId": 42})
        message = ws.receive_json()
        assert message["type"] == "error"

        # 64 chars is accepted, and the socket is still healthy
        rid = "y" * 64
        ws.send_json({"type": "start", "flow": while_flow(),
                      "mode": "step", "speed": 1, "runId": rid})
        started = ws.receive_json()
        assert started["type"] == "started" and started["runId"] == rid
        ws.send_json({"type": "reset"})


# ---------- reset / start-while-active / sequential runs ----------

def test_reset_mid_run_then_second_run_on_same_socket():
    with client.websocket_connect("/api/runs") as ws:
        ws.send_json({"type": "start", "flow": starter_flow(),
                      "mode": "step", "speed": 1})
        assert ws.receive_json()["type"] == "started"
        for expected in ("n1", "n2"):
            ws.send_json({"type": "step"})
            tick = ws.receive_json()
            assert tick["type"] == "tick" and tick["executed"] == expected

        ws.send_json({"type": "reset"})  # cancel mid-run; no reply expected

        started, events = step_run(ws, starter_flow())
        assert started["type"] == "started"
        assert [e["executed"] for e in events] == STARTER_ORDER
        assert events[-1]["reason"] == "end"


def test_start_while_active_implicitly_resets():
    with client.websocket_connect("/api/runs") as ws:
        ws.send_json({"type": "start", "flow": starter_flow(),
                      "mode": "step", "speed": 1})
        assert ws.receive_json()["type"] == "started"
        ws.send_json({"type": "step"})
        assert ws.receive_json()["executed"] == "n1"

        # a fresh start replaces the active run
        started, events = step_run(ws, while_flow())
        assert started["entry"] == "n1"
        assert events[-1]["reason"] == "end"


# ---------- auto mode + set_speed ----------

def test_auto_run_and_set_speed_accepted():
    with client.websocket_connect("/api/runs") as ws:
        ws.send_json({"type": "start", "flow": starter_flow(),
                      "mode": "run", "speed": 2})
        started = ws.receive_json()
        assert started["type"] == "started"
        assert started["logs"] == [{"kind": "info", "text": "Run started"}]

        first = ws.receive_json()  # arrives on the auto ticker, ~420ms
        assert first["type"] == "tick" and first["executed"] == "n1"

        ws.send_json({"type": "set_speed", "speed": 2})
        second = ws.receive_json()
        assert second["type"] == "tick" and second["executed"] == "n2"

        ws.send_json({"type": "pause"})
        ws.send_json({"type": "resume"})
        third = ws.receive_json()
        assert third["type"] == "tick" and third["executed"] == "n3"

        ws.send_json({"type": "reset"})


def test_invalid_speed_rejected():
    with client.websocket_connect("/api/runs") as ws:
        ws.send_json({"type": "set_speed", "speed": 9})
        message = ws.receive_json()
        assert message["type"] == "error"
        assert "Speed must be" in message["message"]


# ---------- protocol errors never kill the socket ----------

def test_malformed_messages_get_friendly_errors_and_socket_survives():
    with client.websocket_connect("/api/runs") as ws:
        ws.send_text("this is not json")
        assert ws.receive_json()["type"] == "error"

        ws.send_json({"type": "bogus"})
        message = ws.receive_json()
        assert message["type"] == "error"
        assert "bogus" in message["message"]

        bad = starter_flow()
        bad["nodes"][4] = node("n5", "loop", {"times": "3"}, kind="TASK")
        ws.send_json({"type": "start", "flow": bad, "mode": "step", "speed": 1})
        message = ws.receive_json()
        assert message["type"] == "error"
        assert "must have kind SWITCH" in message["message"]

        # socket is still usable after all that
        started, events = step_run(ws, while_flow())
        assert events[-1]["reason"] == "end"


def test_start_without_flow_errors():
    with client.websocket_connect("/api/runs") as ws:
        ws.send_json({"type": "start", "mode": "step", "speed": 1})
        message = ws.receive_json()
        assert message["type"] == "error"


def test_deeply_nested_json_frame_gets_friendly_error_socket_alive():
    """json.loads raises RecursionError (not JSONDecodeError) on deep nesting —
    the receive loop must answer with a friendly error and keep going."""
    with client.websocket_connect("/api/runs") as ws:
        ws.send_text("[" * 10000 + "]" * 10000)
        message = ws.receive_json()
        assert message["type"] == "error"

        # an unterminated deep frame (RecursionError mid-parse) as well
        ws.send_text("[" * 10000)
        assert ws.receive_json()["type"] == "error"

        # socket is still usable: run a full flow afterwards
        started, events = step_run(ws, while_flow())
        assert events[-1]["reason"] == "end"


# ---------- split / merge / subgraph over the real WebSocket ----------

def step_run_lenient(ws, flow, max_credits=80, max_events=80):
    """Like step_run, but for flows containing a fan-out ("split"): one
    step credit can legitimately produce more than one tick (one per
    activated edge), so sends and receives aren't 1:1. Over-supplying
    credits up front is harmless — SemaphorePolicy(limit=1) still allows
    only one handler in flight, so dispatch order stays deterministic."""
    ws.send_json({"type": "start", "flow": flow, "mode": "step", "speed": 1})
    started = ws.receive_json()
    assert started["type"] == "started", started
    for _ in range(max_credits):
        ws.send_json({"type": "step"})
    events = []
    for _ in range(max_events):
        message = receive_strict_json(ws)
        events.append(message)
        if message["type"] != "tick":
            break
    return started, events


def test_split_merge_loop_subgraph_over_websocket():
    with client.websocket_connect("/api/runs") as ws:
        started, events = step_run_lenient(ws, split_merge_loop_subgraph_flow())

    assert events[-1]["type"] == "finished"
    assert events[-1]["reason"] == "end"
    executed = [e["executed"] for e in events]
    # n3 (split) reports twice — once per activated edge
    assert executed[:4] == ["n1", "n2", "n3", "n3"]
    assert set(executed[4:6]) == {"n4", "n5"}
    assert executed[6] == "n6"
    # the split's two ticks share one step count and only the first logs
    split_ticks = [e for e in events if e["executed"] == "n3"]
    assert len(split_ticks) == 2
    assert split_ticks[0]["step"] == split_ticks[1]["step"]
    assert split_ticks[0]["logs"] == [{"kind": "step",
                                       "text": "Split — running both branches"}]
    assert split_ticks[1]["logs"] == []
    assert {split_ticks[0]["port"], split_ticks[1]["port"]} == {"a", "b"}
    # inner ticks carry their TRUE ids/edges (not remapped to "n8") so the
    # client can render and highlight the subgraph's own inner nodes/edges.
    inner_node_ids = {"sg_start", "sg_loop", "sg_say", "sg_end"}
    inner_ticks = [e for e in events if e["executed"] in inner_node_ids]
    assert len(inner_ticks) > 0
    assert all(e["next"] in inner_node_ids for e in inner_ticks)
    # the child graph's own TERMINAL (sg_end) completing is reported as the
    # ENCLOSING subgraph node ("n8") — the only framing whose edge the
    # client can actually resolve and animate (no local edge originates
    # from an inner node's id), and the faithful one per LoopGraph's own
    # contract ("a sub-workflow is just another task" to the parent).
    exit_ticks = [e for e in events if e["executed"] == "n8"]
    assert len(exit_ticks) == 2  # once per outer loop visit
    assert all(e["port"] == "out" and e["next"] == "n7" and e["edgeId"]
              for e in exit_ticks)
    # `completed` is the literal inner terminal — a client MUST clear the
    # edge leading into it using this field, not `executed` (which is
    # overridden to "n8" above): no other tick ever names "sg_end" as
    # `executed`, so an edge keyed off that would animate forever otherwise.
    assert all(e["completed"] == "sg_end" for e in exit_ticks)
    # every ordinary tick's `completed` matches `executed` (no override)
    ordinary = [e for e in events if e["type"] == "tick" and e["executed"] != "n8"]
    assert all(e["completed"] == e["executed"] for e in ordinary)
    # the run really executed the inner loop twice per subgraph visit
    say_texts = [l["text"] for e in events for l in e["logs"]
                if l["text"] == "inner round"]
    assert len(say_texts) == 4  # 2 outer visits × 2 inner rounds


# ---------- validate endpoint ----------

def test_validate_ok():
    response = client.post("/api/flows/validate", json={"flow": starter_flow()})
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_validate_kind_mismatch():
    bad = starter_flow()
    bad["nodes"][4] = node("n5", "loop", {"times": "3"}, kind="TASK")
    body = client.post("/api/flows/validate", json={"flow": bad}).json()
    assert body["ok"] is False
    assert any("must have kind SWITCH" in e for e in body["errors"])


def test_validate_surfaces_loopgraph_rejection():
    body = client.post("/api/flows/validate",
                       json={"flow": shared_loops_flow()}).json()
    assert body["ok"] is False
    assert any("loops that share blocks" in e for e in body["errors"])


def test_validate_missing_flow_key():
    body = client.post("/api/flows/validate", json={"nope": 1}).json()
    assert body["ok"] is False
    assert body["errors"]
