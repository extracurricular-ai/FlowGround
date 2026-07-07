# Flowground backend

FastAPI server that compiles `flowground.v1` flows into real
[LoopGraph](https://github.com/S2thend/loopgraph) graphs and streams the
engine's actual execution over WebSocket. See `../PROTOCOL.md` for the contract.

## Setup

```bash
cd server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
cd server && uvicorn app.main:app --reload --port 8000
```

- `GET  /api/healthz`
- `POST /api/flows/validate`
- `WS   /api/runs`

## Test

```bash
cd server && python -m pytest tests -q
```
