# Flowground ↔ Backend Protocol (v1)

Contract between the React SPA and the Python backend. Both sides implement this exactly.

## Roles

- **Frontend** (React 18 + Vite, `src/`): canvas editor, inspector, tutorial, achievements,
  export modal. Does NOT execute flows. Renders run state from server events.
- **Backend** (`server/`, FastAPI + [loopgraph](https://github.com/S2thend/loopgraph)):
  compiles a `flowground.v1` graph into a LoopGraph `Graph` + `FunctionRegistry` and executes
  it with LoopGraph's `Scheduler`. Streams per-node events over WebSocket.

**Fidelity requirement (why this backend exists):** the user wants to *visually observe
LoopGraph's real execution order*. Every `tick` is sent only once the real `Scheduler` has
actually dispatched and completed that node's handler (gated by the session's credit
semaphore, never predicted ahead of it) — never from an independent graph walk. If the
engine does something surprising (an unexpected route, a rejected graph shape), the UI must
show it. `next`/`edgeId` are resolved from the compiled flow's static edge map, which is
exactly as faithful as watching `NODE_SCHEDULED`: LoopGraph guarantees deterministic,
graph-definition-order dispatch for simultaneously-ready nodes, and a (node, port) pair maps
to exactly one edge by construction — the earlier design that paired each report with the
*following* `NODE_SCHEDULED` event was retired because that 1:1 pairing silently mispairs or
drops reports across a genuine merge (two branches both completing before their shared
`AGGREGATE` target is scheduled once — see "Fan-out and merge ticks" below).

## Wire format: `flowground.v1`

The frontend sends the declarative format (same shape as its Export → "Flowground" tab).
The `loopgraph.v1` export (with embedded Python source) is a human-facing artifact only —
it is NEVER sent to the server (client-supplied code = RCE).

```json
{
  "format": "flowground.v1",
  "entry": "n1",
  "nodes": [
    {"id": "n5", "kind": "SWITCH", "block": "loop",
     "config": {"mode": "count", "times": "3", "cond": "lap < 4"},
     "position": {"x": 360, "y": 480}}
  ],
  "edges": [{"source": "n5", "port": "repeat", "target": "n6"}]
}
```

- `kind`: `TASK` (start/ask/say/set/fn/split), `SWITCH` (iff/loop), `TERMINAL` (end),
  `AGGREGATE` (merge), `SUBGRAPH` (subgraph).
  Server re-derives and validates kind from `block`; mismatch → validation error.
- `position` is editor-only; server ignores it.
- Block configs (all values are strings, straight from the inspector):
  | block | config | out-ports |
  |---|---|---|
  | start | `{}` | `out` |
  | ask   | `{name, value}` | `out` |
  | say   | `{text}` | `out` |
  | set   | `{name, expr}` | `out` |
  | iff   | `{cond}` | `true`, `false` |
  | loop  | `{mode: "count"\|"while", times?, cond?}` | `repeat`, `done` |
  | fn    | `{fn: "double"\|"square"\|"shout", arg, result}` | `out` |
  | split | `{}` | `a`, `b` (both fire — a real LoopGraph fan-out) |
  | merge | `{}` | `out` (fires once all incoming branches complete) |
  | subgraph | `{graph: "<JSON-encoded nested flowground.v1 flow>"}` | `out` |
  | end   | `{}` | none |

### Fan-out and merge ticks

- **split** is a `TASK`-kind node with two out-ports, both of which LoopGraph activates
  unconditionally (only `SWITCH` kinds route — everything else fires all out-edges). One
  `split` completion therefore produces **two** `tick` messages, one per activated edge, both
  sharing the same `step`. Only the first carries `logs`; the second's `logs` is `[]` so the
  console never narrates one completion twice. Clients apply every tick as its own atomic
  update (highlight `next`, animate the edge for `port`) — nothing in the protocol assumes one
  tick per node completion any more.
- **merge** is an `AGGREGATE`-kind node: unlike an ordinary join (which fires on the *first*
  upstream and ignores the rest), it waits for every incoming edge before its handler runs
  once. Both branches that fed it get their own ordinary tick showing `next` = the merge
  node's id — nothing is dropped, nothing is double-counted.
- **subgraph** embeds a complete nested flow. Server-side, its inner nodes compile and run
  exactly like top-level ones (same block vocabulary, same shared variables/console), but the
  canvas has no boxes for them: every inner tick's `next` is remapped to the enclosing
  subgraph block's own id, so that block stays highlighted for the whole child-graph run while
  the console narrates its real steps (e.g. real `Loop — round 1 of 2` lines from the inner
  loop). The one tick where control returns to the parent (the child's own `end`/`TERMINAL`
  completing) reports `next` as the parent's real downstream node — but `executed` stays the
  literal inner node id, so — as a deliberate, documented simplification — that specific
  transition's edge does not animate (no local canvas edge originates from an inner node's
  id). A nested `end` block ends only that child graph (LoopGraph's own subgraph contract);
  only the outermost flow's `end` halts the whole run.
- Node/edge ids must be globally unique across a flow and every subgraph nested inside it,
  at any depth — the server rejects a collision with a friendly error.

## HTTP endpoints

- `GET /api/healthz` → `{"ok": true}`
- `POST /api/flows/validate` body `{flow: <flowground.v1>}` →
  `200 {"ok": true}` or `200 {"ok": false, "errors": ["<friendly message>", ...]}`
  (friendly = same tone as run errors below; includes LoopGraph graph-construction
  rejections, e.g. its overlapping-loop rule).

## WebSocket: `/api/runs`

One socket may host many sequential runs (at most one active). JSON text frames.
Server cancels the active run when the socket closes.

### Client → server

```json
{"type": "start", "flow": {…flowground.v1…}, "mode": "run", "speed": 1, "runId": "r3"}
{"type": "step"}                 // in step mode: execute exactly one node
{"type": "pause"}
{"type": "resume"}
{"type": "set_speed", "speed": 2}   // speed = index into [1400, 850, 420] ms
{"type": "reset"}                // cancel active run; session stays usable
```

- The session has one boolean: `auto`. `start(mode:"run")` → auto on (server ticks every
  `SPEEDS[speed]` ms); `start(mode:"step")` → auto off. `pause` → auto off. `resume` →
  auto on. `step` → auto off AND execute exactly one node (valid in either mode — it
  pauses an auto run and advances once). `set_speed` → change interval (takes effect
  immediately if auto).
- Frontend button mapping (prototype parity): Step when idle = `start(mode:"step")`
  followed by one `step` (the prototype executes one node on the first Step click);
  Run while paused = `resume`; Run while auto-running = `pause`.
- `start` while a run is active = implicit reset + new run.
- `runId`: an opaque client-chosen string identifying the run. The server echoes it
  verbatim on every run-scoped event (`started`/`tick`/`finished`). Clients MUST drop
  events whose `runId` differs from their current run (stale frames crossing a Reset or
  a rapid re-start on the wire) — this is the only defense against in-flight events
  repopulating a UI the user just reset.

### Server → client

```json
{"type": "started", "runId": "r3", "entry": "n1", "mode": "run",
 "logs": [{"kind": "info", "text": "Run started"}]}

{"type": "tick", "executed": "n5", "port": "repeat", "next": "n6", "edgeId": "e5",
 "step": 3, "logs": [{"kind": "loop", "text": "Loop — round 1 of 3"}],
 "vars": {"name": "Ada", "lap": 1}}

{"type": "finished", "reason": "end", "executed": "n8", "port": null, "step": 9,
 "logs": [{"kind": "ok", "text": "Flow finished — nice!"}], "vars": {…}}

{"type": "error", "message": "…"}   // protocol/validation errors, not flow errors
```

- `started.logs`: `Run started` (run mode) / `Stepping — press Step for each move` (step mode),
  kind `info`. On `started` the UI highlights `entry` (it is *about to* execute).
- `tick`: node `executed` ran; `next` is now highlighted; `edgeId` names the traversed
  edge **positionally** (`e{index+1}` over the wire-format edge array — local editor ids
  need not match, so clients must resolve the edge to animate from `(executed, port)`,
  not from `edgeId`). `vars` is the full payload snapshot (raw JSON values; non-finite
  numbers, which JSON cannot carry, are encoded as `{"__js": "NaN"|"Infinity"|"-Infinity"}`
  and rendered bare by clients). One `tick` = one atomic UI update, but one node completion
  is not always one tick: a `split` produces one tick per activated edge (see "Fan-out and
  merge ticks" above), and `next`/`executed` for a subgraph's inner nodes are scoped to the
  enclosing subgraph block. `tick` and `finished` carry the run's `runId`.
- `finished` is a final tick: `reason` = `"end"` (reached End block) | `"error"` (flow
  error, see wording below) | `"step_limit"` (150 steps). Its `logs` carry the closing
  line(s). UI clears highlight/edge, `running=false`.
- Flow errors are `logs` with kind `err` inside `tick`/`finished` — NOT `type:"error"`.

### Console line kinds

`info · step · out · branch · loop · ok · err · warn` — exactly the prototype's set.

## Execution semantics — parity with the prototype

The prototype's `tick()` in `Flowground.dc.html` (scratchpad copy, see path in task notes)
is the reference for narration text and value semantics. Copy strings EXACTLY — several
contain typographic characters (U+2019 ’, U+2014 —, U+2192 →); do not retype them as ASCII.

| event | kind | text template |
|---|---|---|
| start executes | step | `Flow started` |
| ask | step | `Asked for {name} → got {fmt(v)}` |
| say | out | interpolated text (see `interp`) |
| set | step | `{name} = {fmt(v)}` |
| iff | branch | `Is {cond}?  → yes` / `…→ no` (two spaces before →) |
| loop(count) repeat | loop | `Loop — round {c} of {t}` |
| loop(count) done | loop | `Loop finished — moving on` |
| loop(while) | loop | `While {cond}?  → yes — around again` / `…→ no — loop done` |
| fn | step | `{result} = {fn}({fmt(a)}) → {fmt(r)}` |
| split | step | `Split — running both branches` |
| merge | step | `Merge — branches joined` |
| end | ok | `Flow finished — nice!` |
| eval failure | err | `Stuck on the {Label} block: can’t work out "{expr}" — is every variable set first?` |
| empty expr | err | `Stuck on the {Label} block: this field is empty` |
| fn unknown | err | `Stuck on the Function block: unknown function` |
| fn arg unset | err | `Stuck on the Function block: "{arg}" isn’t set yet` |
| unconnected port | err | `The "{port}" arrow of this {Label} block isn’t connected — drag from its dot to the next block.` |
| step 150 hit | warn | `150 steps and still going — this might be an infinite loop!` |

`{Label}` = block label (`Start/Ask/Say/Set variable/If/Loop/Function/Split/Merge/Subgraph/End`).

### Value semantics

- `coerce(v)` (ask): trimmed string matching `^-?\d+(\.\d+)?$` → number, else string.
- `fmt(v)`: strings → `"v"` (double-quoted); numbers → JS-style (integral floats print
  with no decimal: `2.0` → `2`); booleans → `true`/`false` lowercase.
- `interp(text, vars)` (say + set-fallback): replace `{word}` with bare-formatted value
  when the var exists, else leave `{word}` literally.
- **Numeric model: JS float64.** All numbers are IEEE-754 doubles with JS operator
  semantics — the evaluator must NOT leak Python numerics: `%` takes the dividend's sign
  (`fmod`), `**` follows JS `Math.pow` (negative base with fractional exponent → NaN,
  overflow → Infinity — never Python complex/big-int), chained comparisons evaluate
  pairwise left-to-right with boolean→number coercion (`1 < 2 < 3` is `(1<2)<3` = `true<3`
  = `1<3`), truthiness is JS's (NaN and `""` falsy), and number→string follows ECMA
  `Number::toString` (plain notation for 1e-6 ≤ |x| < 1e21, else `1e-7`-style exponent).
  A **non-finite final result** of `evalExpr` is the eval failure above (prototype's
  'impossible number'), but `fn` results may legitimately be NaN (JS `'Ada'*2`).
  `Number(string)` coercion (loop `times`, fn `double/square`) follows JS `Number()`:
  `''`→0, hex/binary/octal prefixes parse, `'Infinity'` exact-case only, underscores are
  NOT allowed, else NaN; `loop times = Infinity` loops until the step cap.
- `evalExpr(expr, vars)` (set/iff/loop-while): before parsing, rewrite JS spellings:
  `===`→`==`, `!==`→`!=`, `&&`→`and`, `||`→`or`, `!x`→`not x` (not before `=`),
  `true`→`True`, `false`→`False`. Then evaluate with an AST whitelist:
  literals (num/str/bool), variable names bound to current payload, unary -/not,
  `+ - * / % **`, comparisons, `and/or`, parentheses. NOTHING else (no calls,
  attributes, subscripts, comprehensions). `+` with a string operand = JS-style
  concatenation (other operand bare-formatted). Unknown name / any failure /
  non-finite result → eval failure (single catch-all message above).
- `set` block: try `evalExpr`; on failure use `interp` (string fallback) — EXCEPT the
  empty-expr case which is an error.
- Loop(count): per-node counter; `c < times` → port `repeat`, counter++ ; else counter
  reset to 0, port `done`. `times` = `max(0, floor(Number(times) || 0))`.
- Step cap: after 150 executed nodes, emit warn line + `finished(step_limit)`.
- SWITCH port with no edge → unconnected-port err + `finished(error)`. TASK single
  out-edge (`out`); the editor guarantees ≤1 edge per (node, port).

### Achievements (frontend-only, inferred from events)

- `decider`: a `tick`/`finished` whose `executed` node is block `iff` AND whose `port`
  is non-null (the condition actually evaluated and routed; a failed eval never decided).
- `looper`: a `tick`/`finished` whose `executed` is block `loop` and `port == "done"`.
- `run`: `finished` with `reason == "end"`.
- `wire`, `tutorial`: purely local editor events (unchanged from prototype).

## Dev wiring

- Backend: `cd server && uvicorn app.main:app --reload --port 8000`.
- Vite proxy: `server.proxy = { '/api': { target: 'http://localhost:8000', ws: true } }`.
- Frontend connects the WS lazily on first Run/Step. On connect failure or mid-run close:
  console line kind `err`: `Can’t reach the flow server — is it running? (cd server && uvicorn app.main:app --reload)`
  and run state resets. The client-side "Add a Start block first — every flow needs one."
  check stays local (no server round-trip).
