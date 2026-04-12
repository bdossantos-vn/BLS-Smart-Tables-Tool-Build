"""Data intake page wrapper."""

from __future__ import annotations

from app.services import legacy_flow


def render() -> None:
    """Render the existing Data Intake page."""
    legacy_flow.render_step_1()

