"""Export page."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import time
from typing import Callable

import pandas as pd
import streamlit as st

from app.state.manager import export_project_template
from src.exporter import export_workbook_to_excel_bytes
from src.tables import build_workbook_preview, describe_generation_readiness, generate_workbook_package


PROGRESS_THRESHOLD_SECONDS = 0.85
PROGRESS_STAGE_WEIGHTS = {
    "Preparing data": 8,
    "Calculating tables and significance": 48,
    "Building topline": 12,
    "Writing Excel workbook": 25,
    "Finalizing download": 7,
}


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


def _format_duration(seconds: float | None) -> str:
    """Return a compact elapsed/ETA label."""
    if seconds is None or seconds < 0:
        return "calculating"
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, remainder = divmod(seconds, 60)
    return f"{minutes}m {remainder:02d}s"


def _dataframe_signature(df: pd.DataFrame | None) -> dict[str, object]:
    """Build a compact data signature without storing respondent data."""
    if not isinstance(df, pd.DataFrame):
        return {"shape": None, "columns": []}
    try:
        data_hash = int(pd.util.hash_pandas_object(df, index=True).sum())
    except Exception:
        sample = df.head(5).astype(str).to_dict(orient="list")
        data_hash = hashlib.sha256(json.dumps(sample, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return {
        "shape": list(df.shape),
        "columns": list(df.columns),
        "hash": data_hash,
    }


def _build_export_signature() -> str:
    """Return a hash for the current data and export-affecting settings."""
    payload = {
        "uploaded_filename": st.session_state.get("uploaded_filename"),
        "data": _dataframe_signature(st.session_state.get("cleaned_df")),
        "question_metadata": st.session_state.get("question_metadata", []),
        "custom_variables": st.session_state.get("custom_variables", []),
        "banner_config": st.session_state.get("banner_config", {}) or {},
        "adhoc_crosstabs_config": st.session_state.get("adhoc_crosstabs_config", {}) or {},
        "net_definitions": st.session_state.get("net_definitions", {}) or {},
        "scale_mappings": st.session_state.get("scale_mappings", {}) or {},
        "banner_stat_config": st.session_state.get("banner_stat_config", {}) or {},
        "adhoc_stat_config": st.session_state.get("adhoc_stat_config", {}) or {},
        "comparison_col": st.session_state.get("comparison_col"),
        "comparison_group_order": st.session_state.get("comparison_group_order", {}),
        "comparison_group_labels": st.session_state.get("comparison_group_labels", {}),
        "comparison_scheme": st.session_state.get("comparison_scheme", {}),
        "global_filters": st.session_state.get("global_filters", {}) or {},
        "weighting_config": st.session_state.get("weighting_config", {}) or {},
        "topline_config": st.session_state.get("topline_config", {}),
    }
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _build_progress_callback() -> tuple[Callable[[str, int, int, str | None], None], Callable[[], float], Callable[[], bool]]:
    """Create a delayed progress renderer with ETA."""
    started_at = time.perf_counter()
    placeholder = st.empty()
    state = {"visible": False}
    stage_names = list(PROGRESS_STAGE_WEIGHTS)
    total_weight = sum(PROGRESS_STAGE_WEIGHTS.values())
    stage_offsets: dict[str, int] = {}
    running = 0
    for stage in stage_names:
        stage_offsets[stage] = running
        running += PROGRESS_STAGE_WEIGHTS[stage]

    def elapsed() -> float:
        return time.perf_counter() - started_at

    def callback(stage: str, completed: int, total: int, detail: str | None = None) -> None:
        current_elapsed = elapsed()
        if current_elapsed < PROGRESS_THRESHOLD_SECONDS and not state["visible"]:
            return
        state["visible"] = True
        stage_weight = PROGRESS_STAGE_WEIGHTS.get(stage, 1)
        stage_offset = stage_offsets.get(stage, 0)
        stage_fraction = min(max(completed / max(total, 1), 0.0), 1.0)
        overall_fraction = min((stage_offset + stage_weight * stage_fraction) / total_weight, 1.0)
        eta_seconds = None
        if overall_fraction > 0:
            eta_seconds = (current_elapsed / overall_fraction) - current_elapsed
        detail_text = f" - {detail}" if detail else ""
        with placeholder.container():
            st.progress(overall_fraction)
            st.caption(
                f"{stage}{detail_text} | elapsed {_format_duration(current_elapsed)} | ETA {_format_duration(eta_seconds)}"
            )

    return callback, elapsed, lambda: bool(state["visible"])


def _render_completion_summary(workbook_package: dict, elapsed_seconds: float) -> None:
    """Show a compact export completion summary."""
    summary = workbook_package.get("export_summary", {}) or {}
    optimized_sheets = list(summary.get("optimized_sig_sheets", []) or [])
    optimized_label = ", ".join(dict.fromkeys(optimized_sheets)) if optimized_sheets else "No thresholded optimization needed"
    st.caption(
        "Export complete: "
        f"{_format_duration(elapsed_seconds)} | "
        f"{summary.get('sheet_count', len(workbook_package.get('sheets', [])) + 1)} sheet(s) | "
        f"{summary.get('question_count', workbook_package.get('question_count', 0))} question(s) | "
        f"{int(summary.get('estimated_sig_tests', 0)):,} estimated sig test(s) | "
        f"{optimized_label}"
    )


def _prepare_excel_download(
    workbook_package: dict,
    uploaded_filename: str | None,
    export_signature: str,
    progress_callback: Callable[[str, int, int, str | None], None] | None = None,
) -> tuple[bytes, str]:
    """Build and store Excel bytes for the current generated workbook."""
    export_filename = _build_export_filename(uploaded_filename)
    excel_bytes = export_workbook_to_excel_bytes(
        workbook_package,
        uploaded_filename=uploaded_filename,
        progress_callback=progress_callback,
    )
    st.session_state.generated_excel_bytes = excel_bytes
    st.session_state.generated_excel_filename = export_filename
    st.session_state.generated_excel_signature = export_signature
    return excel_bytes, export_filename


def render() -> None:
    """Render the export page and generate the final workbook."""
    st.header("12. Table Generator & Excel Export")

    readiness = describe_generation_readiness({}, st.session_state)
    for line in readiness:
        st.write(f"- {line}")

    current_export_signature = _build_export_signature()

    if st.button("Generate Tables", type="primary"):
        if not isinstance(st.session_state.get("cleaned_df"), pd.DataFrame) or st.session_state.cleaned_df.empty:
            st.error("A cleaned dataset is required before tables can be generated.")
        elif not st.session_state.get("question_metadata"):
            st.error("Question metadata is required before tables can be generated.")
        else:
            st.session_state.generated_excel_bytes = None
            st.session_state.generated_excel_filename = ""
            st.session_state.generated_excel_signature = ""
            progress_callback, elapsed, progress_was_visible = _build_progress_callback()
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
                progress_callback=progress_callback,
            )
            st.session_state.generated_tables = workbook_package
            st.session_state.generated_tables_signature = current_export_signature
            _prepare_excel_download(
                workbook_package,
                st.session_state.get("uploaded_filename"),
                current_export_signature,
                progress_callback=progress_callback,
            )
            progress_callback("Finalizing download", 2, 2, "Download ready")
            st.success("Tables generated successfully.")
            if workbook_package.get("export_summary", {}).get("topline_notes_warning"):
                st.warning(workbook_package["export_summary"]["topline_notes_warning"])
            _render_completion_summary(workbook_package, elapsed())

    workbook_package = st.session_state.get("generated_tables", {})
    preview_df = build_workbook_preview(workbook_package) if workbook_package else pd.DataFrame()
    if not preview_df.empty:
        generated_tables_signature = st.session_state.get("generated_tables_signature", "")
        if generated_tables_signature and generated_tables_signature != current_export_signature:
            st.info("Settings changed after these tables were generated. Click Generate Tables to refresh the workbook.")
        st.subheader("Workbook Preview")
        st.dataframe(preview_df, use_container_width=True, hide_index=True)
        if workbook_package.get("export_summary", {}).get("topline_notes_warning"):
            st.warning(workbook_package["export_summary"]["topline_notes_warning"])

        excel_bytes = st.session_state.get("generated_excel_bytes")
        export_filename = st.session_state.get("generated_excel_filename")
        excel_signature = st.session_state.get("generated_excel_signature", "")
        can_use_cached_excel = bool(excel_bytes and export_filename and excel_signature == current_export_signature)
        if not can_use_cached_excel and (not generated_tables_signature or generated_tables_signature == current_export_signature):
            progress_callback, elapsed, progress_was_visible = _build_progress_callback()
            excel_bytes, export_filename = _prepare_excel_download(
                workbook_package,
                st.session_state.get("uploaded_filename"),
                current_export_signature,
                progress_callback=progress_callback,
            )
            if progress_was_visible():
                _render_completion_summary(workbook_package, elapsed())
            can_use_cached_excel = True
        if can_use_cached_excel:
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
    st.subheader("Project Settings Export")
    st.write("Download a configuration-only project settings file after your project is fully set up.")
    template_json = export_project_template()
    st.download_button(
        "Download Project Settings",
        data=template_json,
        file_name="bls_smart_tables_project_settings.json",
        mime="application/json",
    )
    if st.button("Save Project Settings Locally", use_container_width=True):
        output_path = _save_local_export("bls_smart_tables_project_settings.json", template_json)
        st.success(f"Saved project settings to `{output_path}`.")
