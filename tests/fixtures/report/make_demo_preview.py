"""Make demo_preview.pdf: the real report template, rendered by RoomCheck's own PDF renderer
from the demo check and its handover data, both made by the pipeline from made-up raw inputs
(app/demo_data.py). The screenshots' Report preview shows it. Made-up data only;
nothing is sent anywhere.

Run from the project folder: uv run python tests/fixtures/report/make_demo_preview.py
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # the project folder

from app.report import render
from tests.unit import demo_data

HERE = Path(__file__).resolve().parent


def view() -> dict[str, object]:
    """The demo report's view: the demo check, its handover data (tasks, statuses and the
    physical check) and no move-in scan, as on the dashboard's demo Results."""
    files = demo_data.build()
    return render.build_view(
        files["result_full"],
        files["result_full"].explanations,  # AI on, as in the rest of the demo
        room_label="Room 4B",
        generated_at=datetime(2026, 11, 3, 5, 25, tzinfo=UTC),
        handover=files["handover_report"],
        compare_state="none",
    )


def main() -> None:
    (HERE / "demo_preview.pdf").write_bytes(render.render_pdf(render.render_html(view())))
    print("wrote", HERE / "demo_preview.pdf")


if __name__ == "__main__":
    main()
