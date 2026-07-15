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
