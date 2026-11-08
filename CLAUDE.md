# RoomCheck
Read docs/original-plan.md for the full design. Build one layer at a time; don't start the next until I confirm.
- Windows 11 native (not WSL). Python 3.12+, FastAPI, React + Vite + TypeScript.
- Fixed rules decide every verdict. AI only explains and never changes severity. Nothing in RoomCheck ever says 'safe'.
- Never log in to devices, try passwords, decrypt traffic, or scan networks without the consent gate.
- Subprocess calls use argument lists, never shell=True. Bind the server to 127.0.0.1 only.
- Every new feature gets pytest tests. Run them before saying a step is done.
- Never run git commands. The user handles version control.
- Don't load the claude-api skill for routine RoomCheck work. The Anthropic call is done
  (app/explain/ai.py). Load it only when I ask, or when a task changes the API call itself
  (model, parameters, SDK version).

## Working rules
- Never run git commands. I commit and push myself.
- Never scan any network except my home network, and only when I say so. Mask MACs, IPs
  (192.0.2.x) and network names in every file, log excerpt and screenshot.
- Demo and screenshot fixtures use documentation addresses (192.0.2.x), "Example-Home",
  made-up CVEs, and AI explanations on (plus one separate AI-off fixture).
- Fixed rules set every priority. AI only words explanations, is optional, and is off unless
  an API key is set.
- Use the shared vocabulary in app/vocabulary.py ("Not detected", "Not checked", "Unconfirmed",
  "Resolved"). Nothing ever says "safe" or "harmless", or implies a room is clear.
- Say "host", never "landlord".
- All UI strings go through web/src/strings/en.json. No inline styles (CSP).
- Results, the report summary and the PDF must always give the same counts (a cross-check test
  covers this; keep it passing).
- The privacy "outside calls" list must stay identical in Help and README (Start only links to Help).
- After every change: run pytest (+ ruff, mypy), vitest (+ tsc, eslint) and Playwright + axe;
  regenerate docs/screenshots/design-pass at 1280 and 390; report what changed plus a table of
  string changes (old → new).
- Work on one prompt at a time; don't start the next until I send it.

## Commands
- Install: `uv sync`
- Tests: `uv run pytest`
- Lint / types: `uv run ruff check .` and `uv run mypy app scannerd`
- Try discovery from the CLI: `uv run python -m app.cli discover` (add `--consent` for active probes)
- Run the API: `uv run python -m app` (serves on 127.0.0.1:8765)
