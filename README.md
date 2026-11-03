# RoomCheck

A digital move-in inspection: find out what's watching or controlling your room before you unpack.
See [PLAN.md](PLAN.md) for the design. Status: Layer 1 (on-network device discovery) built.

## Setup (Windows 11)
1. Install [Npcap](https://npcap.com/#download) (free; not bundled because its licence forbids it).
2. Install [uv](https://docs.astral.sh/uv/), then run `uv sync`.

## Use
- `uv run python -m app.cli discover`: listen-only check (passive, no consent needed).
- `uv run python -m app.cli discover --consent`: also sweeps and probes. Only use this on a network you own or have permission to test.
- `uv run python -m app.cli nearby [--room-network NAME]`: nearby Wi-Fi and Bluetooth only (about 30 s). Reads public broadcasts and never connects. Needs Windows Location turned on to list Wi-Fi.
- `uv run python -m app.cli locate [--item N]`: runs the nearby check, then a warmer/colder signal bar for one flagged item.
- `uv run python -m app`: API on http://127.0.0.1:8765 (`POST /api/discovery`, `POST /api/nearby`, WebSocket `/api/nearby/locate/{ref}`).
- `uv run pytest`: tests.

## Legal note
RoomCheck never logs in to devices or tries passwords, and runs active checks only after you confirm you have permission. It was designed with Singapore's Computer Misuse Act in mind. If you are outside Singapore, check your local law. This is not legal advice.
