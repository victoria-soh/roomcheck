"""`python -m app`: serve the API on 127.0.0.1 only. `--demo`: made-up data, no scans."""

import argparse

import uvicorn

from app.logsetup import configure_logging
from app.main import HOST, PORT, app

if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="python -m app", description="RoomCheck's dashboard")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="demo mode: made-up data; no scans, probes or outside calls (app/demo.py)",
    )
    args = parser.parse_args()
    app.state.demo_requested = args.demo
    configure_logging()
    uvicorn.run(app, host=HOST, port=PORT)
