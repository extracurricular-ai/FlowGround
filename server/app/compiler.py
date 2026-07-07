"""Compile a ``flowground.v1`` flow into a LoopGraph ``Graph`` + handlers.

Each generated handler:

1. awaits a step credit from the run context (the session's pacing gate),
2. executes its block's semantics per the PROTOCOL.md parity table, with the
   prototype's exact narration strings,
3. records a :class:`Report` ``{executed, port, logs, vars snapshot}`` on the
   run context.

SWITCH handlers return the chosen port to LoopGraph (the edges carry matching
``route`` metadata), so routing decisions are made by the real engine.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from loopgraph.core.graph import Edge as LGEdge
from loopgraph.core.graph import Graph as LGGraph
from loopgraph.core.graph import Node as LGNode
from loopgraph.core.types import NodeKind
from loopgraph.registry.function_registry import FunctionRegistry

from .safe_eval import (EmptyExprError, ExprError, coerce, eval_expr, fmt,
                        interp, js_number, js_truthy)
from .schema import BLOCKS, Flow, FlowNode, FlowValidationError

#: cap on executed nodes per run (PROTOCOL.md: after 150 executed nodes,
#: emit the warn line + ``finished(step_limit)``).
STEP_LIMIT = 150

_KIND_MAP = {
    "TASK": NodeKind.TASK,
    "SWITCH": NodeKind.SWITCH,
    "TERMINAL": NodeKind.TERMINAL,
}


@dataclass
class Report:
    """What one executed node did — recorded by its handler."""

    node_id: str
    port: Optional[str]
    logs: List[Tuple[str, str]]
    vars: Dict[str, Any]
    step: int
    halt: Optional[str] = None  # None | "end" | "error" | "step_limit"


@dataclass
class CompiledFlow:
    flow: Flow
    graph: LGGraph
    #: (node id, port) → (edge id, target node id) — the static edge map.
    edge_map: Dict[Tuple[str, str], Tuple[str, str]] = field(default_factory=dict)
    nodes: Dict[str, FlowNode] = field(default_factory=dict)


class BlockError(Exception):
    """A flow-level block failure; message goes into the
    'Stuck on the {Label} block: …' narration."""


def _friendly_engine_error(message: str) -> str:
    m = re.search(r"Switch node '([^']+)' cannot have a self-loop", message)
    if m:
        return (f"The LoopGraph engine won’t allow block {m.group(1)} to arrow "
                "straight back into itself — route it through another block first.")
    m = re.search(r"multi-loop shared nodes: \[(.*)\]", message)
    if m:
        ids = m.group(1).replace("'", "")
        return (f"The LoopGraph engine can’t run loops that share blocks ({ids}) "
                "— give each loop its own blocks.")
    if "no entry nodes" in message:
        return ("The LoopGraph engine needs a block with no incoming arrows to "
                "start from — don’t wire arrows into your Start block.")
    return f"The LoopGraph engine rejected this flow: {message}"


def compile_flow(flow: Flow) -> CompiledFlow:
    """Build the LoopGraph graph. Raises :class:`FlowValidationError` with a
    friendly message when the engine rejects the graph."""
    nodes: Dict[str, LGNode] = {}
    flow_nodes: Dict[str, FlowNode] = {}
    for n in flow.nodes:
        # allow_partial_upstream: loop headers have >1 upstream edge and the
        # engine would otherwise wait for ALL of them (deadlock on cycles).
        nodes[n.id] = LGNode(
            id=n.id,
            kind=_KIND_MAP[BLOCKS[n.block].kind],
            handler=n.id,
            allow_partial_upstream=True,
        )
        flow_nodes[n.id] = n

    edges: Dict[str, LGEdge] = {}
    edge_map: Dict[Tuple[str, str], Tuple[str, str]] = {}
    for e in flow.edges:
        metadata: Dict[str, object] = {"port": e.port}
        if BLOCKS[flow_nodes[e.source].block].kind == "SWITCH":
            # The engine routes SWITCH results by edge "route" metadata.
            metadata["route"] = e.port
        edges[e.id] = LGEdge(id=e.id, source=e.source, target=e.target,
                             metadata=metadata)
        edge_map[(e.source, e.port)] = (e.id, e.target)

    try:
        graph = LGGraph(nodes=nodes, edges=edges)
        graph.validate()
        if graph.nodes and not graph.entry_nodes():
            raise ValueError("Graph has no entry nodes (nodes with no upstream edges)")
    except (ValueError, KeyError) as exc:
        raise FlowValidationError([_friendly_engine_error(str(exc))]) from exc

    return CompiledFlow(flow=flow, graph=graph, edge_map=edge_map,
                        nodes=flow_nodes)


# ---------- block semantics (prototype tick() parity) ----------

def _fn_double(v: Any) -> float:
    # JS: 'Ada' * 2 is NaN — a NaN result is legitimate and flows into vars.
    return js_number(v) * 2.0


def _fn_square(v: Any) -> float:
    n = js_number(v)
    return n * n


def _fn_shout(v: Any) -> str:
    return fmt(v, True).upper()


FUNCS = {"double": _fn_double, "square": _fn_square, "shout": _fn_shout}


def _loop_times(raw: Optional[str]) -> float:
    """Prototype: ``Math.max(0, Math.floor(Number(times) || 0))``.

    JS keeps Infinity here (``Math.floor(Infinity)`` is Infinity), so
    ``times = 'Infinity'`` loops until the 150-step cap; NaN → 0.
    """
    n = js_number("" if raw is None else raw)
    if math.isnan(n):
        return 0.0
    if math.isinf(n):
        return max(0.0, n)  # +Infinity stays; -Infinity clamps to 0
    return max(0.0, float(math.floor(n)))


def _eval_or_block_error(expr: str, variables: Dict[str, Any]) -> Any:
    try:
        return eval_expr(expr, variables)
    except EmptyExprError:
        raise BlockError("this field is empty") from None
    except ExprError:
        raise BlockError(
            "can’t work out \"" + expr + "\" — is every variable set first?"
        ) from None


def _execute_block(node: FlowNode, ctx: Any,
                   logs: List[Tuple[str, str]]) -> Optional[str]:
    """Run one block's semantics; returns the chosen out-port (None for end).
    May raise :class:`BlockError`."""
    cfg = node.config
    block = node.block

    if block == "start":
        logs.append(("step", "Flow started"))
        return "out"

    if block == "ask":
        name = cfg.get("name", "")
        v = coerce(cfg.get("value", ""))
        ctx.vars[name] = v
        logs.append(("step", f"Asked for {name} → got {fmt(v)}"))
        return "out"

    if block == "say":
        logs.append(("out", interp(cfg.get("text", ""), ctx.vars)))
        return "out"

    if block == "set":
        name = cfg.get("name", "")
        expr = cfg.get("expr", "")
        try:
            v = eval_expr(expr, ctx.vars)
        except EmptyExprError:
            raise BlockError("this field is empty") from None
        except ExprError:
            v = interp(expr, ctx.vars)
        ctx.vars[name] = v
        logs.append(("step", f"{name} = {fmt(v)}"))
        return "out"

    if block == "iff":
        cond = cfg.get("cond", "")
        r = js_truthy(_eval_or_block_error(cond, ctx.vars))
        logs.append(("branch", "Is " + cond + "?  → " + ("yes" if r else "no")))
        return "true" if r else "false"

    if block == "loop":
        mode = cfg.get("mode") or "count"
        if mode == "while":
            cond = cfg.get("cond", "")
            r = js_truthy(_eval_or_block_error(cond, ctx.vars))
            logs.append(("loop", "While " + cond + "?  → " +
                         ("yes — around again" if r else "no — loop done")))
            return "repeat" if r else "done"
        t = _loop_times(cfg.get("times"))
        c = ctx.loop_counts.get(node.id, 0)
        if c < t:
            ctx.loop_counts[node.id] = c + 1
            logs.append(("loop", f"Loop — round {c + 1} of {fmt(t, True)}"))
            return "repeat"
        ctx.loop_counts[node.id] = 0
        logs.append(("loop", "Loop finished — moving on"))
        return "done"

    if block == "fn":
        fn_name = cfg.get("fn", "")
        arg = cfg.get("arg", "")
        result_name = cfg.get("result", "")
        f = FUNCS.get(fn_name)
        if f is None:
            raise BlockError("unknown function")
        if arg not in ctx.vars:
            raise BlockError("\"" + arg + "\" isn’t set yet")
        a = ctx.vars[arg]
        r = f(a)
        ctx.vars[result_name] = r
        logs.append(("step", f"{result_name} = {fn_name}({fmt(a)}) → {fmt(r)}"))
        return "out"

    if block == "end":
        logs.append(("ok", "Flow finished — nice!"))
        return None

    raise BlockError("unknown block")  # unreachable; parse_flow rejects


def _make_handler(compiled: CompiledFlow, node: FlowNode, ctx: Any):
    label = BLOCKS[node.block].label
    is_switch = BLOCKS[node.block].kind == "SWITCH"

    async def handler(payload: Any = None) -> Any:
        await ctx.acquire_credit()
        logs: List[Tuple[str, str]] = []
        port: Optional[str] = None
        halt: Optional[str] = None
        try:
            port = _execute_block(node, ctx, logs)
        except BlockError as exc:
            logs.append(("err", f"Stuck on the {label} block: {exc}"))
            halt = "error"

        if halt is None:
            if node.block == "end":
                halt = "end"
            elif (node.id, port) not in compiled.edge_map:
                logs.append(("err",
                             f'The "{port}" arrow of this {label} block isn’t '
                             "connected — drag from its dot to the next block."))
                halt = "error"

        ctx.steps += 1
        if halt is None and ctx.steps >= STEP_LIMIT:
            logs.append(("warn",
                         "150 steps and still going — this might be an infinite "
                         "loop!"))
            halt = "step_limit"

        ctx.record(Report(node_id=node.id, port=port, logs=logs,
                          vars=dict(ctx.vars), step=ctx.steps, halt=halt))

        if is_switch:
            # LoopGraph requires switch handlers to return a string route.
            return port if port is not None else ""
        return dict(ctx.vars)

    return handler


def build_registry(compiled: CompiledFlow, ctx: Any) -> FunctionRegistry:
    """One handler per node, registered under the node id.

    ``ctx`` is the run context (the session's ``Run``): it must provide
    ``vars``/``loop_counts`` dicts, a ``steps`` int, ``async acquire_credit()``
    and ``record(report)``.
    """
    registry = FunctionRegistry()
    for node in compiled.flow.nodes:
        registry.register(node.id, _make_handler(compiled, node, ctx))
    return registry
