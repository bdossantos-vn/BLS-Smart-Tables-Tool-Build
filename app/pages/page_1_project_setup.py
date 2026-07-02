"""Project setup page."""

from __future__ import annotations

import streamlit as st

from app.services.template_service import parse_template_bytes
from app.state.manager import load_project_template


def render() -> None:
    """Render the Project Setup page.

    This page lets a user start clean or load saved project settings.
    """
    st.header("1. Project Setup")
    st.write("Start a new project or resume a previous project with a saved settings file.")

    if st.session_state.get("project_setup_mode") == "Upload template":
        st.session_state.project_setup_mode = "Resume from saved project"

    mode = st.radio(
        "How do you want to begin?",
        ["Start from scratch", "Resume from saved project"],
        key="project_setup_mode",
    )

    if mode == "Resume from saved project":
        st.subheader("Resume Project")
        template_file = st.file_uploader(
            "Upload saved project settings",
            type=["json"],
            key="project_template_upload",
            help="Project settings store configuration only. They do not contain respondent data.",
        )
        if template_file is not None:
            try:
                payload = parse_template_bytes(template_file.getvalue())
                load_project_template(payload)
            except Exception as exc:  # pragma: no cover - Streamlit boundary
                st.error(f"Project settings upload failed: {exc}")
            else:
                st.success(st.session_state.get("template_upload_message", "Project settings loaded."))

    if st.session_state.get("pending_project_config"):
        st.info(
            "Saved project settings are ready. Go to Data Intake and load the matching data "
            "from upload or Snowflake to restore the working project."
        )
