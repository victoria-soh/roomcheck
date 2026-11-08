"""Moved to app/demo_data.py, which `python -m app --demo` uses too. This alias keeps
`from tests.unit import demo_data` and `uv run python -m tests.unit.demo_data` working."""

import sys

from app import demo_data

if __name__ == "__main__":
    demo_data.main()
else:
    sys.modules[__name__] = demo_data
