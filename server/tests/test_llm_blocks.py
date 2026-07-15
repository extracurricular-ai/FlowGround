import asyncio
import time
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from loopgraph.bus.eventbus import EventBus
from loopgraph.concurrency import SemaphorePolicy
from loopgraph.core.types import NodeKind
from loopgraph.scheduler.scheduler import Scheduler

from app.compiler import build_registry, compile_flow
from app.llm_client import LLMError
from app.main import app
from app.schema import parse_flow
from app.session import SPEEDS

from flowdefs import llm_flow
from test_compiler import StubCtx
from test_run_ws import step_run

client = TestClient(app)


def test_llm_blocks_compile_with_correct_kinds():
    compiled = compile_flow(parse_flow(llm_flow()))
    graph = compiled.graph
    assert graph.nodes["n3"].kind is NodeKind.TASK     # llm_generate
    assert graph.nodes["n4"].kind is NodeKind.SWITCH   # llm_judge
    assert compiled.edge_map[("n4", "true")] == ("e4", "n5")
    assert compiled.edge_map[("n4", "false")] == ("e5", "n6")


async def _run(flow_def, ctx):
    compiled = compile_flow(parse_flow(flow_def))
    registry = build_registry(compiled, ctx)
    scheduler = Scheduler(registry, EventBus(), SemaphorePolicy(limit=1))
    await scheduler.run(compiled.graph, initial_payload={})
    return compiled


async def test_llm_generate_saves_result_and_interpolates_prompt():
    ctx = StubCtx(llm={"apiKey": "k", "baseUrl": "https://api.example",
                       "mode": "openai", "model": "test-model"})
    seen_prompts = []

    async def fake_call_llm(*, mode, base_url, api_key, model, prompt):
        seen_prompts.append(prompt)
        assert mode == "openai" and api_key == "k" and model == "test-model"
        return "Hello ducks!"

    with patch("app.compiler.call_llm", new=fake_call_llm):
        await _run(llm_flow(), ctx)

    assert ctx.vars["reply"] == "Hello ducks!"
    # the {topic} placeholder was interpolated before being sent
    assert seen_prompts[0] == "Say hi about ducks."
    assert ctx.reports[-1].halt == "end"


async def test_llm_judge_routes_true_on_yes_like_answer():
    ctx = StubCtx(llm={"apiKey": "k", "baseUrl": "https://api.example"})
    with patch("app.compiler.call_llm", new=AsyncMock(return_value="Yes, definitely.")):
        await _run(llm_flow(), ctx)
    assert [r.port for r in ctx.reports if r.node_id == "n4"] == ["true"]
    assert ctx.reports[-1].vars["reply"]  # generate ran before judge


async def test_llm_judge_routes_false_on_no_like_answer():
    ctx = StubCtx(llm={"apiKey": "k", "baseUrl": "https://api.example"})
    with patch("app.compiler.call_llm", new=AsyncMock(return_value="No.")):
        await _run(llm_flow(), ctx)
    assert [r.port for r in ctx.reports if r.node_id == "n4"] == ["false"]


def test_llm_call_failure_halts_with_friendly_message():
    # A bare StubCtx + raw Scheduler never actually stops on halt (only the
    # real Session/Run does, via record() -> _finish() cancelling the task),
    # so error-path tests go through the real WS session, same as the
    # existing bad_expr_flow/empty_expr_flow tests in test_run_ws.py.
    boom = AsyncMock(side_effect=LLMError("couldn’t reach https://api.example (timeout)"))
    with patch("app.compiler.call_llm", new=boom):
        with client.websocket_connect("/api/runs") as ws:
            started, events = step_run(
                ws, llm_flow(),
                llm={"apiKey": "k", "baseUrl": "https://api.example"})

    finished = events[-1]
    assert finished["reason"] == "error"
    assert finished["executed"] == "n3"  # fails at the first LLM node it hits
    assert finished["logs"] == [
        {"kind": "err",
         "text": "Stuck on the AI Generate block: couldn’t reach "
                 "https://api.example (timeout)"},
    ]


def test_llm_generate_with_no_settings_fails_without_any_network_call():
    """No "llm" field sent at all — call_llm itself (unmocked) must reject
    before attempting any HTTP call, and the run halts with a message
    pointing at AI settings rather than a raw network exception."""
    with client.websocket_connect("/api/runs") as ws:
        started, events = step_run(ws, llm_flow())  # no llm= kwarg

    finished = events[-1]
    assert finished["reason"] == "error"
    assert finished["executed"] == "n3"
    assert "AI settings" in finished["logs"][0]["text"]


# ---------- auto-mode pacing (Run.record()'s _arm_next_tick) ----------

def _auto_run_timeline(flow_def, speed_ix, llm_impl):
    """start(mode run) at speed_ix with call_llm patched to llm_impl;
    returns (started_at, [(monotonic_time, message), ...]) through finished."""
    timeline = []
    with patch("app.compiler.call_llm", new=llm_impl):
        with client.websocket_connect("/api/runs") as ws:
            ws.send_json({"type": "start", "flow": flow_def, "mode": "run",
                          "speed": speed_ix,
                          "llm": {"apiKey": "k", "baseUrl": "https://x"}})
            started = ws.receive_json()
            assert started["type"] == "started", started
            started_at = time.monotonic()
            while True:
                msg = ws.receive_json()
                timeline.append((time.monotonic(), msg))
                if msg["type"] != "tick":
                    break
    assert timeline[-1][1]["type"] == "finished", timeline[-1]
    return started_at, timeline


def test_no_instant_hop_after_slow_llm_call_in_auto_mode():
    """Regression: a free-running ticker used to keep releasing credits on
    its own schedule every SPEEDS[speed] ms, even while a handler was still
    busy — so a slow llm_generate/llm_judge network call let credits bank
    up, and the very next node fired within a few ms of it resolving. That
    is easy to miss entirely for a SWITCH block like llm_judge: its own
    outgoing edge gets replaced by the next tick before a browser ever
    paints it lit, which reads as "the edge never turns on" even though the
    state was technically correct for an instant. Now every credit is
    scheduled fresh from record() — after a node's real work finishes, not
    from an independent clock — so nothing can ever bank ahead of a slow
    call."""
    speed_ix = 2
    interval = SPEEDS[speed_ix] / 1000.0
    delay = interval * 1.5  # deliberately longer than one pacing interval

    async def slow_llm(*, mode, base_url, api_key, model, prompt):
        await asyncio.sleep(delay)
        return "Yes, definitely."

    started_at, timeline = _auto_run_timeline(llm_flow(), speed_ix, slow_llm)
    ticks = [(t, m) for t, m in timeline if m["type"] == "tick"]
    executed_order = [m["executed"] for _, m in ticks]
    assert "n3" in executed_order and "n4" in executed_order  # llm_generate, llm_judge

    gaps = []
    prev_t = started_at
    for t, _ in ticks:
        gaps.append(t - prev_t)
        prev_t = t
    min_gap = min(gaps)
    assert min_gap > interval * 0.6, (
        f"smallest gap between consecutive ticks was {min_gap * 1000:.0f}ms — "
        f"expected at least ~{interval * 1000:.0f}ms (instant-hop regression); "
        f"all gaps(ms): {[round(g * 1000) for g in gaps]}")


def test_normal_auto_pacing_still_roughly_one_interval_apart():
    """Sanity check the fix didn't change normal pacing the other way: with
    a FAST llm call (much shorter than one interval), consecutive ticks
    should still land roughly one interval apart — not doubled, not
    skipped."""
    speed_ix = 2
    interval = SPEEDS[speed_ix] / 1000.0

    async def fast_llm(*, mode, base_url, api_key, model, prompt):
        return "Yes."

    started_at, timeline = _auto_run_timeline(llm_flow(), speed_ix, fast_llm)
    ticks = [t for t, m in timeline if m["type"] == "tick"]
    prev = started_at
    for t in ticks:
        gap = t - prev
        assert interval * 0.5 < gap < interval * 3, (
            f"gap {gap * 1000:.0f}ms not close to the expected ~{interval * 1000:.0f}ms")
        prev = t
