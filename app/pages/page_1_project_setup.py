"""Project setup page."""

from __future__ import annotations

import streamlit as st

from app.services.template_service import parse_template_bytes
from app.state.manager import load_project_template


def render() -> None:
    """Render the Project Setup page.

    This page lets a user start clean or load a saved configuration template.
    """
    st.header("1. Project Setup")
    st.write("Choose whether to start from scratch or load a saved configuration template.")

    mode = st.radio(
        "How do you want to begin?",
        ["Start from scratch", "Upload template"],
        key="project_setup_mode",
    )

    if mode == "Upload template":
        template_file = st.file_uploader(
            "Upload template file",
            type=["json"],
            key="project_template_upload",
            help="Templates store configuration only. They do not contain respondent data.",
        )
        if template_file is not None:
            try:
                payload = parse_template_bytes(template_file.getvalue())
                load_project_template(payload)
            except Exception as exc:  # pragma: no cover - Streamlit boundary
                st.error(f"Template upload failed: {exc}")
            else:
                st.success(st.session_state.get("template_upload_message", "Template loaded successfully."))

