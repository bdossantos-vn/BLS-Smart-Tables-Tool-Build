"""Streamlit entrypoint for the refactored BLS Smart Tables Tool.

This file now focuses on three responsibilities only:
1. Set up the Streamlit application shell.
2. Initialize central session state.
3. Route the user to the correct page module.
"""

from __future__ import annotations

import streamlit as st

from app.components.navigation import render_page_navigation, render_sidebar
from app.pages import (
    page_10_stat_setup,
    page_11_topline_config,
    page_12_export,
    page_1_project_setup,
    page_2_data_intake,
    page_3_question_audit,
    page_4_scale_mapping,
    page_5_net_definitions,
    page_6_custom_variables,
    page_7_banner_config,
    page_8_filter_config,
    page_9_weighting,
)
from app.state.manager import init_app_state, sync_project_config_from_session

st.set_page_config(
    page_title="BLS Smart Tables Tool",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


PAGE_REGISTRY = {
    "project_setup": page_1_project_setup.render,
    "data_intake": page_2_data_intake.render,
    "question_audit": page_3_question_audit.render,
    "scale_mapping": page_4_scale_mapping.render,
    "net_definitions": page_5_net_definitions.render,
    "custom_variables": page_6_custom_variables.render,
    "banner_config": page_7_banner_config.render,
    "filter_config": page_8_filter_config.render,
    "weighting": page_9_weighting.render,
    "stat_setup": page_10_stat_setup.render,
    "topline_config": page_11_topline_config.render,
    "export": page_12_export.render,
}


def main() -> None:
    """Run the Streamlit app through the new modular page registry."""
    init_app_state()
    current_step_id = render_sidebar()
    page_renderer = PAGE_REGISTRY.get(current_step_id, page_1_project_setup.render)
    page_renderer()
    sync_project_config_from_session()
    render_page_navigation(current_step_id)


if __name__ == "__main__":
    main()
