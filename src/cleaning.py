"""Qualtrics ingestion and cleaning logic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from src.io import read_excel_upload
from src.utils import normalize_text, unique_preserving_order


DEFAULT_VARIABLE_BLACKLIST = [
    "StartDate",
    "EndDate",
    "IPAddress",
    "RecipientEmail",
    "RecipientFirstName",
    "RecipientLastName",
    "Status",
    "Duration",
    "Duration (in seconds)",
    "RecordedDate",
    "ResponseId",
    "ResponseSet",
    "LocationLatitude",
    "LocationLongitude",
    "UserLanguage",
    "Finished",
    "Progress",
    "DistributionChannel",
    "ExternalReference",
]

DEFAULT_BLACKLIST_PREFIXES = [
    "Q_RelevantID",
    "Q_DuplicateRespondent",
]


@dataclass
class IngestionResult:
    """Structured result returned after processing a Qualtrics export."""

    raw_df: pd.DataFrame
    cleaned_df: pd.DataFrame
    question_labels: dict[str, str]
    cell_column: str | None
    blacklist_used: list[str]
    log_lines: list[str]
    metadata_rows_removed: int
    removed_columns: list[str]
    sheet_name: str
    completed_at: str


def _looks_like_metadata_row(row: pd.Series, header_values: list[str], row_index: int) -> bool:
    """Heuristically identify non-respondent metadata rows after the label row."""
    values = [normalize_text(value) for value in row.tolist()]
    non_empty_values = [value for value in values if value]
    if not non_empty_values:
        return True

    import_id_hits = sum("importid" in value.lower() for value in non_empty_values)
    header_overlap = sum(value in header_values for value in non_empty_values)
    qualtrics_meta_hits = sum(
        any(token in value.lower() for token in ["qualtrics", "metadata", "question text", "survey"])
        for value in non_empty_values
    )

    # Practical assumption: respondent rows after the standard label row typically contain
    # a mix of blanks and answer values. Rows dominated by ImportId/header/meta patterns
    # are treated as additional metadata and removed.
    if row_index == 2 and import_id_hits >= max(1, len(non_empty_values) // 3):
        return True
    if header_overlap >= max(2, len(non_empty_values) // 2):
        return True
    if qualtrics_meta_hits >= max(2, len(non_empty_values) // 2):
        return True
    return False


def _prepare_qualtrics_dataframe(raw_df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str], int]:
    """Promote the first row to headers and remove metadata rows while preserving labels."""
    if raw_df.shape[0] < 2:
        raise ValueError("The uploaded workbook does not contain enough rows to parse.")

    header_values = [normalize_text(value) for value in raw_df.iloc[0].tolist()]
    if not any(header_values):
        raise ValueError("The first row does not contain valid variable names.")

    question_label_row = raw_df.iloc[1].tolist()
    question_labels = {
        header if header else f"column_{idx}": normalize_text(label)
        for idx, (header, label) in enumerate(zip(header_values, question_label_row))
        if header
    }

    df = raw_df.copy()
    df.columns = [header if header else f"column_{idx}" for idx, header in enumerate(header_values)]
    metadata_rows_removed = 0
    rows_to_drop: list[int] = [0, 1]

    for row_index in range(2, len(df)):
        if _looks_like_metadata_row(df.iloc[row_index], header_values, row_index):
            rows_to_drop.append(row_index)
            metadata_rows_removed += 1
        else:
            break

    cleaned_df = df.drop(index=rows_to_drop).reset_index(drop=True)
    return cleaned_df, question_labels, metadata_rows_removed


def _remove_blacklisted_columns(
    df: pd.DataFrame,
    blacklist: list[str],
    blacklist_prefixes: list[str] | None = None,
    whitelist_columns: list[str] | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """Drop blacklisted system columns case-insensitively."""
    blacklist_lookup = {value.lower() for value in blacklist}
    prefix_lookup = [value.lower() for value in (blacklist_prefixes or [])]
    whitelist_lookup = {value.lower() for value in (whitelist_columns or [])}
    removed = []
    for column in df.columns:
        normalized = normalize_text(column).lower()
        if normalized in whitelist_lookup:
            continue
        if normalized in blacklist_lookup or any(normalized.startswith(prefix) for prefix in prefix_lookup):
            removed.append(column)
    cleaned_df = df.drop(columns=removed, errors="ignore")
    return cleaned_df, removed


def _resolve_cell_column(columns: list[str]) -> str | None:
    """Find the primary experimental split column named `cell`, case-insensitively."""
    matches = [column for column in columns if normalize_text(column).lower() == "cell"]
    return matches[0] if matches else None


def ingest_qualtrics_dataframe(
    raw_df: pd.DataFrame,
    source_name: str,
    sheet_name: str,
    blacklist: list[str] | None = None,
    whitelist_columns: list[str] | None = None,
) -> IngestionResult:
    """Ingest, clean, and validate a Qualtrics dataframe already loaded into memory."""
    blacklist = unique_preserving_order(blacklist or DEFAULT_VARIABLE_BLACKLIST)
    completed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    log_lines = [f"Loaded sheet `{sheet_name}` from `{source_name}`."]
    prepared_df, question_labels, metadata_rows_removed = _prepare_qualtrics_dataframe(raw_df)
    log_lines.append(f"Preserved variable names and question labels. Removed {metadata_rows_removed} metadata row(s).")

    no_tech_df, removed_columns = _remove_blacklisted_columns(
        prepared_df,
        blacklist,
        DEFAULT_BLACKLIST_PREFIXES,
        whitelist_columns,
    )
    log_lines.append(f"Removed {len(removed_columns)} blacklisted column(s).")

    cell_column = _resolve_cell_column(list(no_tech_df.columns))
    if no_tech_df.empty:
        raise ValueError("All respondent rows were removed during cleaning. Check the source export.")

    # Preserve question labels only for columns that survived cleaning.
    question_labels = {
        column: question_labels.get(column, column)
        for column in no_tech_df.columns
    }
    log_lines.append(
        f"Final dataset contains {len(no_tech_df):,} respondent rows and {len(no_tech_df.columns):,} columns."
    )

    return IngestionResult(
        raw_df=raw_df,
        cleaned_df=no_tech_df,
        question_labels=question_labels,
        cell_column=cell_column,
        blacklist_used=blacklist,
        log_lines=log_lines,
        metadata_rows_removed=metadata_rows_removed,
        removed_columns=removed_columns,
        sheet_name=sheet_name,
        completed_at=completed_at,
    )


def ingest_qualtrics_excel(
    uploaded_file,
    blacklist: list[str] | None = None,
    whitelist_columns: list[str] | None = None,
    sheet_name: str | None = None,
) -> IngestionResult:
    """Ingest, clean, and validate a Qualtrics Excel export."""
    read_result = read_excel_upload(uploaded_file, sheet_name=sheet_name)
    return ingest_qualtrics_dataframe(
        raw_df=read_result.dataframe,
        source_name=uploaded_file.name,
        sheet_name=read_result.sheet_name,
        blacklist=blacklist,
        whitelist_columns=whitelist_columns,
    )
