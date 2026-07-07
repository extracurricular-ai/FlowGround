"""Pydantic models + friendly validation for the ``flowground.v1`` format."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict

from .safe_eval import js_num_str

FORMAT = "flowground.v1"


class BlockSpec:
    def __init__(self, label: str, kind: str, ports: Tuple[str, ...]):
        self.label = label
        self.kind = kind
        self.ports = ports


#: block → (label, required loopgraph kind, out-ports) — PROTOCOL.md table.
BLOCKS: Dict[str, BlockSpec] = {
    "start": BlockSpec("Start", "TASK", ("out",)),
    "ask": BlockSpec("Ask", "TASK", ("out",)),
    "say": BlockSpec("Say", "TASK", ("out",)),
    "set": BlockSpec("Set variable", "TASK", ("out",)),
    "iff": BlockSpec("If", "SWITCH", ("true", "false")),
    "loop": BlockSpec("Loop", "SWITCH", ("repeat", "done")),
    "fn": BlockSpec("Function", "TASK", ("out",)),
    "end": BlockSpec("End", "TERMINAL", ()),
}


class FlowNode(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    kind: str
    block: str
    config: Dict[str, str]

    @property
    def label(self) -> str:
        return BLOCKS[self.block].label

    @property
    def ports(self) -> Tuple[str, ...]:
        return BLOCKS[self.block].ports


class FlowEdge(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    source: str
    port: str
    target: str


class Flow(BaseModel):
    model_config = ConfigDict(frozen=True)

    format: str
    entry: str
    nodes: List[FlowNode]
    edges: List[FlowEdge]


class FlowValidationError(Exception):
    """Carries the list of friendly validation messages."""

    def __init__(self, errors: List[str]):
        super().__init__(" ".join(errors))
        self.errors = errors


def _config_value(v: Any) -> Optional[str]:
    """Config values should be strings; tolerate JSON scalars."""
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return js_num_str(v)
    return None


def parse_flow(data: Any) -> Flow:
    """Validate raw JSON into a :class:`Flow`; raise :class:`FlowValidationError`
    with friendly messages on any problem."""
    errors: List[str] = []
    if not isinstance(data, dict):
        raise FlowValidationError(
            ['This doesn’t look like a Flowground flow — expected a JSON object '
             'with format "flowground.v1".'])

    if data.get("format") != FORMAT:
        errors.append('This doesn’t look like a Flowground flow — expected format '
                      '"flowground.v1".')

    nodes: List[FlowNode] = []
    node_ids: Dict[str, FlowNode] = {}
    raw_nodes = data.get("nodes")
    if not isinstance(raw_nodes, list):
        errors.append('The flow needs a "nodes" list.')
        raw_nodes = []
    for raw in raw_nodes:
        if not isinstance(raw, dict):
            errors.append("Every node must be a JSON object.")
            continue
        nid = raw.get("id")
        if not isinstance(nid, str) or not nid:
            errors.append('Every node needs an "id".')
            continue
        block = raw.get("block")
        if block not in BLOCKS:
            errors.append(f'Unknown block type "{block}" on node {nid} — expected '
                          'one of start, ask, say, set, iff, loop, fn, end.')
            continue
        spec = BLOCKS[block]
        kind = raw.get("kind")
        if kind != spec.kind:
            errors.append(f'The "{block}" block ({nid}) must have kind '
                          f'{spec.kind}, not {kind}.')
            continue
        raw_config = raw.get("config", {})
        if raw_config is None:
            raw_config = {}
        if not isinstance(raw_config, dict):
            errors.append(f"The config of block {nid} must be an object.")
            continue
        config: Dict[str, str] = {}
        bad_config = False
        for key, value in raw_config.items():
            text = _config_value(value)
            if text is None:
                errors.append(f'The "{key}" setting of block {nid} must be text.')
                bad_config = True
                break
            config[str(key)] = text
        if bad_config:
            continue
        if nid in node_ids:
            errors.append(f'Two blocks share the id "{nid}" — ids must be unique.')
            continue
        node = FlowNode(id=nid, kind=kind, block=block, config=config)
        node_ids[nid] = node
        nodes.append(node)

    edges: List[FlowEdge] = []
    seen_ports: set = set()
    seen_edge_ids: set = set()
    raw_edges = data.get("edges")
    if not isinstance(raw_edges, list):
        errors.append('The flow needs an "edges" list.')
        raw_edges = []
    for index, raw in enumerate(raw_edges):
        if not isinstance(raw, dict):
            errors.append('Every edge must be a JSON object with "source", "port" '
                          'and "target".')
            continue
        source, port, target = raw.get("source"), raw.get("port"), raw.get("target")
        if not all(isinstance(v, str) and v for v in (source, port, target)):
            errors.append('Every edge needs "source", "port" and "target".')
            continue
        eid = raw.get("id")
        if eid is None:
            eid = f"e{index + 1}"
        if not isinstance(eid, str) or not eid:
            errors.append("Edge ids must be text.")
            continue
        if source not in node_ids:
            errors.append(f'An arrow starts at unknown block "{source}".')
            continue
        if target not in node_ids:
            errors.append(f'An arrow points at unknown block "{target}".')
            continue
        src_node = node_ids[source]
        if port not in src_node.ports:
            ports = ", ".join(src_node.ports) if src_node.ports else "none"
            errors.append(f'The {src_node.label} block ({source}) has no "{port}" '
                          f'arrow — its arrows are: {ports}.')
            continue
        if (source, port) in seen_ports:
            errors.append(f'The "{port}" arrow of block {source} is connected '
                          'twice — a block can only have one arrow per dot.')
            continue
        if eid in seen_edge_ids:
            errors.append(f'Two arrows share the id "{eid}" — ids must be unique.')
            continue
        seen_ports.add((source, port))
        seen_edge_ids.add(eid)
        edges.append(FlowEdge(id=eid, source=source, port=port, target=target))

    entry = data.get("entry")
    if not isinstance(entry, str) or not entry:
        errors.append("The flow has no entry — add a Start block first.")
        entry = ""
    elif not errors and entry not in node_ids:
        errors.append(f'The entry block "{entry}" doesn’t exist.')

    if errors:
        raise FlowValidationError(errors)

    return Flow(format=FORMAT, entry=entry, nodes=nodes, edges=edges)
