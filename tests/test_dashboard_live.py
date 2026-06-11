from __future__ import annotations

from ztb.dashboard.live import render_live_page


def test_render_live_page_importable() -> None:
    assert callable(render_live_page)
