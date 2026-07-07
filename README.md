# Flowground

*Learn logic by drawing it* — a visual flow-programming playground. Drag blocks onto a
canvas, wire them into a flow, then press **Run** and watch it execute step by step:
node highlights, animated edges, a console that narrates every instruction, and a live
variables panel.

Flows are executed server-side by the real **[LoopGraph](https://github.com/S2thend/loopgraph)**
engine — every tick shown on the canvas is derived from LoopGraph's own scheduler events,
so Flowground doubles as a visualizer for LoopGraph's actual execution order.

Design source: [Flowground.dc.html](https://claude.ai/design/p/b31fb3f0-9226-437e-a9f2-a78a09888638?file=Flowground.dc.html)

## Architecture

| Piece | Stack | Where |
|---|---|---|
| Editor SPA | React 18 + Vite, prototype-faithful inline styles (no CSS framework) | `src/` |
| Run backend | Python 3.10+, FastAPI + uvicorn, loopgraph | `server/` |
| Contract | WebSocket `/api/runs` + REST, wire format `flowground.v1` | [PROTOCOL.md](PROTOCOL.md) |

The client never executes flows and never sends code — it sends the declarative
`flowground.v1` graph; the server compiles each block into a LoopGraph handler,
evaluating user expressions with an AST-whitelisted evaluator. The `loopgraph.v1 +
Python` export in the UI is a human-readable artifact, not the wire format.

## Run it

Backend (first time: create the venv):

```bash
cd server
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

Frontend (separate terminal, repo root):

```bash
npm install
npm run dev        # http://localhost:5173 — proxies /api to :8000
```

## Tests

```bash
cd server && .venv/bin/python -m pytest tests -q   # backend: engine, protocol, safety
npm run build                                       # frontend: production build
```
