"""Export page."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from app.state.manager import export_project_template
from src.exporter import export_workbook_to_excel_bytes
from src.tables import build_workbook_preview, describe_generation_readiness, generate_workbook_package


def _build_export_filename(uploaded_filename: str | None) -> str:
    """Build the final Excel filename using the agreed naming convention."""
    stem = (uploaded_filename or "BLS_Smart_Tables").rsplit(".", 1)[0].strip() or "BLS_Smart_Tables"
    return f"{stem}_Tables_{datetime.now().strftime('%Y%m%d')}.xlsx"


def _save_local_export(filename: str, data: bytes | str) -> Path:
    """Save an export artifact inside the local workspace."""
    # 2026-05-15 BD: Codex's in-app browser may block localhost downloads, so
    # export pages also provide a workspace-local save path for analyst testing.
    export_dir = Path.cwd() / "exports"
    export_dir.mkdir(exist_ok=True)
    output_path = export_dir / filename
    if isinstance(data, str):
        output_path.write_text(data, encoding="utf-8")
    else:
        output_path.write_bytes(data)
    return output_path


def render() -> None:
    """Render the export page and generate the final workbook."""
    st.header("12. Table Generator & Excel Export")

    readiness = describe_generation_readiness({}, st.session_state)
    for line in readiness:
        st.write(f"- {line}")

    if st.button("Generate Tables", type="primary"):
        if not isinstance(st.session_state.get("cleaned_df"), pd.DataFrame) or st.session_state.cleaned_df.empty:
            st.error("A cleaned dataset is required before tables can be generated.")
        elif not st.session_state.get("question_metadata"):
            st.error("Question metadata is required before tables can be generated.")
        else:
            workbook_package = generate_workbook_package(
                cleaned_df=st.session_state.cleaned_df,
                question_metadata=st.session_state.question_metadata,
                custom_variables=st.session_state.custom_variables,
                banner_config=st.session_state.banner_config or {},
                adhoc_crosstabs_config=st.session_state.get("adhoc_crosstabs_config", {}) or {},
                net_definitions=st.session_state.net_definitions or {},
                scale_mappings=st.session_state.scale_mappings or {},
                banner_stat_config=st.session_state.get("banner_stat_config", {}) or {},
                adhoc_stat_config=st.session_state.get("adhoc_stat_config", {}) or {},
                comparison_col=st.session_state.get("comparison_col"),
                comparison_group_order=st.session_state.get("comparison_group_order", {}),
                comparison_group_labels=st.session_state.get("comparison_group_labels", {}),
                # 2026-05-19 BD: Pass layered comparison rules into generation
                # so toplines/banners can build Control-vs-group columns.
                comparison_scheme=st.session_state.get("comparison_scheme", {}),
                global_filters=st.session_state.get("global_filters", {}) or {},
                weighting_config=st.session_state.get("weighting_config", {}) or {},
                topline_config=st.session_state.get("topline_config", {}),
            )
            st.session_state.generated_tables = workbook_package
            st.success("Tables generated successfully.")

    workbook_package = st.session_state.get("generated_tables", {})
    preview_df = build_workbook_preview(workbook_package) if workbook_package else pd.DataFrame()
    if not preview_df.empty:
        st.subheader("Workbook Preview")
        st.dataframe(preview_df, use_container_width=True, hide_index=True)

        excel_bytes = export_workbook_to_excel_bytes(
            workbook_package,
            uploaded_filename=st.session_state.get("uploaded_filename"),
        )
        export_filename = _build_export_filename(st.session_state.get("uploaded_filename"))
        st.download_button(
            "Download Excel Workbook",
            data=excel_bytes,
            file_name=export_filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        if st.button("Save Excel Workbook Locally", use_container_width=True):
            output_path = _save_local_export(export_filename, excel_bytes)
            st.success(f"Saved workbook to `{output_path}`.")

    st.divider()
    st.subheader("Project Template Export")
    st.write("Download a configuration-only template after your project is fully set up.")
    template_json = export_project_template()
    st.download_button(
        "Download Project Template",
        data=template_json,
        file_name="bls_smart_tables_template.json",
        mime="application/json",
    )
    if st.button("Save Project Template Locally", use_container_width=True):
        output_path = _save_local_export("bls_smart_tables_template.json", template_json)
        st.success(f"Saved template to `{output_path}`.")
