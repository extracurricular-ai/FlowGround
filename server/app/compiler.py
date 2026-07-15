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

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from loopgraph.core.graph import Edge as LGEdge
from loopgraph.core.graph import Graph as LGGraph
from loopgraph.core.graph import Node as LGNode
from loopgraph.core.types import NodeKind
from loopgraph.registry.function_registry import FunctionRegistry

from .llm_client import LLMError, call_llm
from .safe_eval import (EmptyExprError, ExprError, coerce, eval_expr, fmt,
                        interp, js_number, js_truthy)
from .schema import (BLOCKS, NESTED_GRAPH_BLOCKS, Flow, FlowEdge, FlowNode,
                     FlowValidationError, parse_flow)

#: cap on executed nodes per run (PROTOCOL.md: after 150 executed nodes,
#: emit the warn line + ``finished(step_limit)``).
STEP_LIMIT = 150

_KIND_MAP = {
    "TASK": NodeKind.TASK,
    "SWITCH": NodeKind.SWITCH,
    "TERMINAL": NodeKind.TERMINAL,
    "AGGREGATE": NodeKind.AGGREGATE,
    "SUBGRAPH": NodeKind.SUBGRAPH,
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
    #: True for a block whose completion activates ALL of its out-edges at
    #: once (currently only "split") — the run context then expects one
    #: NODE_SCHEDULED per activated edge instead of exactly one.
    fan_out: bool = False


@dataclass
class CompiledFlow:
    flow: Flow
    graph: LGGraph
    #: (node id, port) → (edge id, target node id) — the static edge map,
    #: merged across the top-level flow AND every nested subgraph body (all
    #: node/edge ids are globally unique, so one flat map covers all scopes).
    edge_map: Dict[Tuple[str, str], Tuple[str, str]] = field(default_factory=dict)
    #: every compiled FlowNode, top-level and nested, keyed by id.
    nodes: Dict[str, FlowNode] = field(default_factory=dict)
    #: node ids that belong to the outermost flow — only their "end" block
    #: halts the whole run. A nested subgraph's "end" block just ends that
    #: child graph; LoopGraph does that automatically when its TERMINAL runs.
    top_level_ids: Set[str] = field(default_factory=set)
    #: node id → OUTERMOST enclosing top-level SUBGRAPH node id (identity for
    #: top-level ids themselves) — flattened across every nesting level. Lets
    #: the WS session keep a subgraph block highlighted on canvas for the
    #: duration of its child graph's run, no matter how deep inside it a
    #: given node actually is.
    node_scope: Dict[str, str] = field(default_factory=dict)
    #: node id → its DIRECT (one level up) enclosing SUBGRAPH node id, absent
    #: for top-level ids. Unlike ``node_scope`` this is NOT flattened — used
    #: to resolve "what fires next" when a nested child graph's own TERMINAL
    #: completes, which is always the immediate parent's out-edge, not the
    #: outermost ancestor's (those differ once subgraphs nest 2+ levels deep).
    parent_scope: Dict[str, str] = field(default_factory=dict)


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


def _compile_subgraph_body(n: FlowNode, enclosing: Optional[str], *,
                           all_flow_nodes: Dict[str, FlowNode],
                           edge_map: Dict[Tuple[str, str], Tuple[str, str]],
                           top_level_ids: Set[str],
                           node_scope: Dict[str, str],
                           parent_scope: Dict[str, str]) -> LGGraph:
    """Parse+compile a "subgraph" block's nested ``flowground.v1`` body."""
    label = BLOCKS[n.block].label
    raw = n.config.get("graph", "")
    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise FlowValidationError(
            [f'The "{label}" block ({n.id}) has an invalid nested flow: '
             f'its "graph" setting isn’t valid JSON ({exc}).']) from exc
    try:
        child_flow = parse_flow(data)
    except FlowValidationError as exc:
        raise FlowValidationError(
            [f'The "{label}" block ({n.id}) has an invalid nested flow: ' + m
             for m in exc.errors]) from exc
    outer_scope = n.id if enclosing is None else enclosing
    return _compile_scope(child_flow.nodes, child_flow.edges, enclosing=outer_scope,
                          parent=n.id, all_flow_nodes=all_flow_nodes,
                          edge_map=edge_map, top_level_ids=top_level_ids,
                          node_scope=node_scope, parent_scope=parent_scope)


def _compile_scope(flow_nodes: List[FlowNode], flow_edges: List[FlowEdge], *,
                   enclosing: Optional[str], parent: Optional[str],
                   all_flow_nodes: Dict[str, FlowNode],
                   edge_map: Dict[Tuple[str, str], Tuple[str, str]],
                   top_level_ids: Set[str],
                   node_scope: Dict[str, str],
                   parent_scope: Dict[str, str]) -> LGGraph:
    """Compile one flow's worth of nodes/edges into an ``LGGraph``, recursing
    into any "subgraph" blocks. All node/edge ids across every scope share
    one flat ``all_flow_nodes``/``edge_map`` (ids must be globally unique).
    ``enclosing`` is the OUTERMOST top-level ancestor (for ``node_scope``);
    ``parent`` is the DIRECT enclosing subgraph node, one level up, or None
    at the top level (for ``parent_scope``) — they diverge once subgraphs
    nest two or more levels deep."""
    nodes: Dict[str, LGNode] = {}
    local_nodes: Dict[str, FlowNode] = {}
    subgraph_ids: List[str] = []
    for n in flow_nodes:
        if n.id in all_flow_nodes:
            raise FlowValidationError(
                [f'Two blocks share the id "{n.id}" (including inside a '
                 "subgraph) — every block needs a unique id, even nested ones."])
        # Register this node BEFORE recursing into any nested subgraph body,
        # so a child that reuses an id already in scope — including this
        # very subgraph node's own id — is caught, regardless of nesting order.
        local_nodes[n.id] = n
        all_flow_nodes[n.id] = n
        if enclosing is None:
            top_level_ids.add(n.id)
            node_scope[n.id] = n.id
        else:
            node_scope[n.id] = enclosing
        if parent is not None:
            parent_scope[n.id] = parent

        spec = BLOCKS[n.block]
        if n.block in NESTED_GRAPH_BLOCKS:
            subgraph_ids.append(n.id)
            child_graph = _compile_subgraph_body(
                n, enclosing, all_flow_nodes=all_flow_nodes, edge_map=edge_map,
                top_level_ids=top_level_ids, node_scope=node_scope,
                parent_scope=parent_scope)
            lg_config: Dict[str, object] = {"graph": child_graph.to_dict()}
            handler = ""
        else:
            lg_config = {}
            handler = n.id
        # allow_partial_upstream: loop headers have >1 upstream edge and the
        # engine would otherwise wait for ALL of them (deadlock on cycles).
        # AGGREGATE-kind nodes ignore this flag and always join properly.
        nodes[n.id] = LGNode(
            id=n.id,
            kind=_KIND_MAP[spec.kind],
            handler=handler,
            config=lg_config,
            allow_partial_upstream=True,
        )

    lg_edges: Dict[str, LGEdge] = {}
    for e in flow_edges:
        metadata: Dict[str, object] = {"port": e.port}
        if BLOCKS[local_nodes[e.source].block].kind == "SWITCH":
            # The engine routes SWITCH results by edge "route" metadata.
            metadata["route"] = e.port
        lg_edges[e.id] = LGEdge(id=e.id, source=e.source, target=e.target,
                                metadata=metadata)
        edge_map[(e.source, e.port)] = (e.id, e.target)

    # A subgraph node has no handler of its own, so — unlike every other
    # block — nothing at RUNTIME ever checks that its single "out" port is
    # wired (PROTOCOL.md's "unconnected port" narration never fires for it).
    # Its out-edge always fires unconditionally once the child graph ends, so
    # catching a missing one here (compile time) loses no legitimate
    # "never actually reached" case the way skipping an iff/loop branch would.
    for sid in subgraph_ids:
        label = BLOCKS[local_nodes[sid].block].label
        for port in local_nodes[sid].ports:
            if (sid, port) not in edge_map:
                raise FlowValidationError(
                    [f'The "{port}" arrow of this {label} block ({sid}) isn’t '
                     "connected — drag from its dot to the next block."])

    return LGGraph(nodes=nodes, edges=lg_edges)


def compile_flow(flow: Flow) -> CompiledFlow:
    """Build the LoopGraph graph. Raises :class:`FlowValidationError` with a
    friendly message when the engine rejects the graph."""
    all_flow_nodes: Dict[str, FlowNode] = {}
    edge_map: Dict[Tuple[str, str], Tuple[str, str]] = {}
    top_level_ids: Set[str] = set()
    node_scope: Dict[str, str] = {}
    parent_scope: Dict[str, str] = {}

    graph = _compile_scope(flow.nodes, flow.edges, enclosing=None, parent=None,
                           all_flow_nodes=all_flow_nodes, edge_map=edge_map,
                           top_level_ids=top_level_ids, node_scope=node_scope,
                           parent_scope=parent_scope)

    try:
        graph.validate()
        if graph.nodes and not graph.entry_nodes():
            raise ValueError("Graph has no entry nodes (nodes with no upstream edges)")
    except (ValueError, KeyError) as exc:
        raise FlowValidationError([_friendly_engine_error(str(exc))]) from exc

    return CompiledFlow(flow=flow, graph=graph, edge_map=edge_map,
                        nodes=all_flow_nodes, top_level_ids=top_level_ids,
                        node_scope=node_scope, parent_scope=parent_scope)


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


def _ellipsize(text: str, limit: int = 120) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


async def _call_llm_or_block_error(ctx: Any, prompt: str) -> str:
    """Call the LLM using the run's global AI settings (``ctx.llm`` — set
    from the start message's "llm" field, never part of the flow itself).
    Wraps :class:`LLMError` as a :class:`BlockError` so it surfaces through
    the same "Stuck on the {Label} block: …" narration as any other block
    failure, rather than crashing the run differently."""
    llm = getattr(ctx, "llm", None) or {}
    try:
        return await call_llm(
            mode=llm.get("mode", "anthropic"),
            base_url=llm.get("baseUrl", ""),
            api_key=llm.get("apiKey", ""),
            model=llm.get("model", ""),
            prompt=prompt,
        )
    except LLMError as exc:
        raise BlockError(str(exc)) from None


async def _execute_block(node: FlowNode, ctx: Any,
                         logs: List[Tuple[str, str]]) -> Optional[str]:
    """Run one block's semantics; returns the chosen out-port (None for end).
    May raise :class:`BlockError`. ``async`` solely so llm_generate/llm_judge
    can ``await`` their HTTP call — every other block below is synchronous."""
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

    if block == "llm_generate":
        prompt = interp(cfg.get("prompt", ""), ctx.vars)
        result_name = cfg.get("result", "")
        text = await _call_llm_or_block_error(ctx, prompt)
        ctx.vars[result_name] = text
        logs.append(("step", f"{result_name} = AI(\"{_ellipsize(prompt)}\") "
                             f"→ {fmt(_ellipsize(text))}"))
        return "out"

    if block == "llm_judge":
        prompt = interp(cfg.get("prompt", ""), ctx.vars)
        text = await _call_llm_or_block_error(ctx, prompt)
        r = text.strip().lower().startswith(("y", "true"))
        logs.append(("branch", f"AI: {_ellipsize(prompt)}  → "
                               + ("yes" if r else "no")))
        return "true" if r else "false"

    if block == "split":
        logs.append(("step", "Split — running both branches"))
        return None  # fan-out: activated edges are structural, not port-driven

    if block == "merge":
        # payload is the AGGREGATE's list of upstream results; this app
        # threads state through the shared ctx.vars instead, so the list
        # itself isn't needed — the join point matters, not its contents.
        logs.append(("step", "Merge — branches joined"))
        return "out"

    if block == "end":
        logs.append(("ok", "Flow finished — nice!"))
        return None

    raise BlockError("unknown block")  # unreachable; parse_flow rejects


def _make_handler(compiled: CompiledFlow, node: FlowNode, ctx: Any):
    label = BLOCKS[node.block].label
    spec = BLOCKS[node.block]
    is_switch = spec.kind == "SWITCH"
    is_fan_out = spec.fan_out
    #: only the outermost flow's own "end" block halts the whole run — a
    #: nested subgraph's "end"/TERMINAL just ends that child graph, which
    #: LoopGraph does automatically once it runs.
    halts_on_end = node.id in compiled.top_level_ids

    async def handler(payload: Any = None) -> Any:
        await ctx.acquire_credit()
        logs: List[Tuple[str, str]] = []
        port: Optional[str] = None
        halt: Optional[str] = None
        try:
            port = await _execute_block(node, ctx, logs)
        except BlockError as exc:
            logs.append(("err", f"Stuck on the {label} block: {exc}"))
            halt = "error"

        if halt is None:
            if is_fan_out:
                missing = [p for p in node.ports
                          if (node.id, p) not in compiled.edge_map]
                if missing:
                    logs.append(("err",
                                 f'The "{missing[0]}" arrow of this {label} '
                                 "block isn’t connected — drag from its dot "
                                 "to the next block."))
                    halt = "error"
            elif node.block == "end":
                if halts_on_end:
                    halt = "end"
                # a nested "end" block just ends its child graph normally
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
                          vars=dict(ctx.vars), step=ctx.steps, halt=halt,
                          fan_out=is_fan_out))

        if is_switch:
            # LoopGraph requires switch handlers to return a string route.
            return port if port is not None else ""
        return dict(ctx.vars)

    return handler


def build_registry(compiled: CompiledFlow, ctx: Any) -> FunctionRegistry:
    """One handler per node — top-level AND every nested subgraph node.

    ``ctx`` is the run context (the session's ``Run``): it must provide
    ``vars``/``loop_counts`` dicts, a ``steps`` int, ``async acquire_credit()``
    and ``record(report)``. "subgraph" blocks have no handler of their own
    (LoopGraph runs their embedded child graph directly).
    """
    registry = FunctionRegistry()
    for node_id, node in compiled.nodes.items():
        if node.block in NESTED_GRAPH_BLOCKS:
            continue
        registry.register(node_id, _make_handler(compiled, node, ctx))
    return registry
