"""Custom variable builder page wrapper."""

from __future__ import annotations

from app.services import legacy_flow


def render() -> None:
    """Render the existing Custom Variable Builder page."""
    legacy_flow.render_step_6()

