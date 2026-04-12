"""Export page wrapper."""

from __future__ import annotations

import streamlit as st

from app.services import legacy_flow
from app.state.manager import export_project_template


def render() -> None:
    """Render the existing export page."""
    legacy_flow.render_step_11()
    st.divider()
    st.subheader("Project Template Export")
    st.write("Download a configuration-only template after your project is fully set up.")
    st.download_button(
        "Download Project Template",
        data=export_project_template(),
        file_name="bls_smart_tables_template.json",
        mime="application/json",
    )
