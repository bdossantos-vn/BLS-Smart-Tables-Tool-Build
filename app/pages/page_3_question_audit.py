"""Survey question audit page wrapper."""

from __future__ import annotations

from app.services import legacy_flow


def render() -> None:
    """Render the existing Survey Question Audit page."""
    legacy_flow.render_step_3()

