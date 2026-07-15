# Contributing to Flowground

Thanks for considering a contribution. Flowground is a small project, so the process is
intentionally lightweight.

## Getting set up

Follow the [Quick start](README.md#quick-start) in the README to run the backend and
editor locally.

## Before you open a PR

```bash
cd server && .venv/bin/python -m pytest tests -q
cd .. && npm run build
```

Both should pass. If you changed the wire protocol, update [`PROTOCOL.md`](PROTOCOL.md)
alongside the code.

## Making changes

- Frontend code lives in [`src/`](src/); backend and the LoopGraph compiler live in
  [`server/`](server/).
- Keep the client and server in sync with the `flowground.v1` graph format — the
  frontend should never send executable code, only declarative graph data.
- UI strings are bilingual (English/Chinese); add new strings to both locales.
- Match the existing code style in the file you're editing rather than introducing a
  new one.

## Reporting bugs / proposing features

Open a [GitHub issue](../../issues) with steps to reproduce (for bugs) or the problem
you're trying to solve (for features). For open-ended questions, use
[Discussions](../../discussions) if enabled, or open an issue anyway.

## Pull requests

- Keep PRs focused on one change.
- Describe what changed and why in the PR description.
- Link the issue it addresses, if any.
