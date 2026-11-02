# RoomCheck
Read PLAN.md for the full design. Build one layer at a time; don't start the next until I confirm.
- Windows 11 native (not WSL). Python 3.12+, FastAPI, React + Vite + TypeScript.
- Fixed rules decide every verdict. AI only explains and never changes severity. Nothing in RoomCheck ever says 'safe'.
- Never log in to devices, try passwords, decrypt traffic, or scan networks without the consent gate.
- Subprocess calls use argument lists, never shell=True. Bind the server to 127.0.0.1 only.
- Every new feature gets pytest tests. Run them before saying a step is done.
- Never run git commands. The user handles version control.

## Commands
- Install: `uv sync`
- Tests: `uv run pytest`
- Lint / types: `uv run ruff check .` and `uv run mypy app scannerd`
- Try discovery from the CLI: `uv run python -m app.cli discover` (add `--consent` for active probes)
- Run the API: `uv run python -m app` (serves on 127.0.0.1:8765)
