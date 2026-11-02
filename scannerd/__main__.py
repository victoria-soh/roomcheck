"""Entry point: `python -m scannerd`.

Reads the hex auth key from the first line of stdin, prints `PORT <n>`, then serves until
stdin closes (the app closed it or exited).
"""

from __future__ import annotations

import sys
import threading

from scannerd.server import Server


def main() -> int:
    try:
        authkey = bytes.fromhex(sys.stdin.readline().strip())
    except ValueError:
        return 2
    if len(authkey) < 32:
        return 2
    server = Server(authkey)
    print(f"PORT {server.address[1]}", flush=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    sys.stdin.read()  # returns when the app closes stdin or dies
    server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
