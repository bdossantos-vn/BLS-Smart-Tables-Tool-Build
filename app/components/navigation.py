"""Navigation helpers for the refactored page-based app."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.components.branding import render_sidebar_brand
from app.models.project_config import build_default_project_config
from app.state.manager import sync_project_config_from_session
from src.mapping import identify_scale_questions
from src.state import reset_project_state


STEPS: list[dict[str, str]] = [
    {"id": "project_setup", "label": "1. Project Setup"},
    {"id": "data_intake", "label": "2. Data Intake"},
    {"id": "question_audit", "label": "3. Survey Question Audit"},
    {"id": "scale_mapping", "label": "4. Scale Mapping"},
    {"id": "net_definitions", "label": "5. Net Definitions"},
    {"id": "custom_variables", "label": "6. Custom Variables"},
    {"id": "banner_config", "label": "7. Banner Configuration"},
    {"id": "adhoc_crosstabs", "label": "8. Custom AdHoc Crosstabs"},
    {"id": "filter_config", "label": "9. Filter Configuration"},
    {"id": "stat_setup", "label": "10. Statistical Setup"},
    {"id": "topline_config", "label": "11. Topline Configuration"},
    {"id": "export", "label": "12. Export"},
]

LEGACY_LABEL_REDIRECTS = {
    "8. Filter Configuration": "9. Filter Configuration",
    "9. Weighting": "10. Statistical Setup",
    "10. Statistical Setup": "10. Statistical Setup",
    "11. Topline Configuration": "11. Topline Configuration",
    "12. Export": "12. Export",
}


def _step_labels() -> list[str]:
    """Return ordered user-facing step labels."""
    return [step["label"] for step in STEPS]


def get_step_id_from_label(label: str) -> str:
    """Resolve an internal step id from a sidebar label."""
    for step in STEPS:
        if step["label"] == label:
            return step["id"]
    return STEPS[0]["id"]


def get_step_label_from_id(step_id: str) -> str:
    """Resolve a user-facing label from an internal step id."""
    for step in STEPS:
        if step["id"] == step_id:
            return step["label"]
    return STEPS[0]["label"]


def can_advance(step_id: str) -> bool:
    """Return whether the current step is ready to move forward."""
    cleaned_df = st.session_state.get("cleaned_df")
    question_metadata = st.session_state.get("question_metadata", [])
    if step_id == "project_setup":
        return True
    if step_id == "data_intake":
        return (
            isinstance(cleaned_df, pd.DataFrame)
            and not cleaned_df.empty
            and bool(st.session_state.get("comparison_configured"))
        )
    if step_id == "question_audit":
        return bool(question_metadata)
    if step_id == "scale_mapping":
        scale_questions = identify_scale_questions(question_metadata)
        if not scale_questions:
            return True
        mapped_variables = set(st.session_state.get("scale_mappings", {}).keys())
        required_variables = {row["variable"] for row in scale_questions}
        return required_variables.issubset(mapped_variables)
    return True


def render_sidebar() -> str:
    """Render the shared sidebar navigation.

    Returns:
        The internal page id for the currently selected page.
    """
    with st.sidebar:
        render_sidebar_brand()
        current_label = st.session_state.get("app_current_step", STEPS[0]["label"])
        if current_label in LEGACY_LABEL_REDIRECTS:
            current_label = LEGACY_LABEL_REDIRECTS[current_label]
            st.session_state.app_current_step = current_label
        if current_label not in _step_labels():
            current_label = STEPS[0]["label"]
        selected_label = st.radio("Workflow", _step_labels(), index=_step_labels().index(current_label))
        st.session_state.app_current_step = selected_label
        st.divider()

        if "confirm_new_project" not in st.session_state:
            st.session_state.confirm_new_project = False
        if st.button("Start New Project", type="secondary", use_container_width=True):
            st.session_state.confirm_new_project = True
            st.rerun()
        if st.session_state.get("confirm_new_project"):
            st.warning(
                "Starting a new project will delete your current progress and data, and return you to step 1 to upload a new file. Continue"
            )
            yes_col, no_col = st.columns(2)
            with yes_col:
                if st.button("Yes", key="confirm_start_new_project_yes", use_container_width=True):
                    reset_project_state()
                    st.session_state.project_setup_mode = "Start from scratch"
                    st.session_state.app_current_step = STEPS[0]["label"]
                    st.session_state.project_config = build_default_project_config()
                    st.session_state.topline_config = {
                        "variables": [],
                        "response_selections": {},
                        "note_base_sections": {},
                        "include_lift": False,
                        "comparison_scope": "control_vs_test",
                        "include_significance_notes": True,
                    }
                    st.session_state.template_upload_message = ""
                    st.session_state.qualtrics_upload = None
                    st.session_state.confirm_new_project = False
                    sync_project_config_from_session()
                    st.rerun()
            with no_col:
                if st.button("No", key="confirm_start_new_project_no", use_container_width=True):
                    st.session_state.confirm_new_project = False
                    st.rerun()
    return get_step_id_from_label(selected_label)


def render_page_navigation(current_step_id: str) -> None:
    """Render previous/next buttons for the current page."""
    step_ids = [step["id"] for step in STEPS]
    current_index = step_ids.index(current_step_id)
    left, _, right = st.columns([1, 3, 1])
    with left:
        if current_index > 0 and st.button("Back", key=f"back_{current_step_id}", use_container_width=True):
            st.session_state.app_current_step = STEPS[current_index - 1]["label"]
            st.rerun()
    with right:
        if current_index < len(STEPS) - 1 and can_advance(current_step_id):
            if st.button("Next", key=f"next_{current_step_id}", use_container_width=True):
                st.session_state.app_current_step = STEPS[current_index + 1]["label"]
                st.rerun()
