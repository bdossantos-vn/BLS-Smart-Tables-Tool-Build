"""Qualtrics ingestion and cleaning logic."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from src.io import normalize_wide_checkbox_groups, read_excel_upload, read_sav_upload
from src.respondents import RESPONDENT_ID_COLUMN, is_internal_respondent_column, respondent_count
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
    "Q_RecaptchaScore",
    "Q_RecaptchaStatus",
    "Q_RecaptchaError",
    "gc",
    "rid",
    "c_key",
    "brand",
    "industry",
    "client",
    "quarter",
    "year",
    "methodology",
    "rdud",
    "platform",
    "ad",
    "country",
    "Q_AmbiguousTextPresent",
    "Q_AmbiguousTextQuestions",
    "Q_StraightliningCount",
    "Q_StraightliningPercentage",
    "Q_StraightliningQuestions",
    "Q_UnansweredPercentage",
    "Q_UnansweredQuestions",
]

DEFAULT_BLACKLIST_PREFIXES = [
    "Q_RelevantID",
    "Q_DuplicateRespondent",
]

_QUALTRICS_RID_COLUMN_CANDIDATES = [
    "RESPONSE_KEY",
    "RID",
    "RESPONSEID",
    "RESPONSE_ID",
    "QUALTRICS_RID",
    "QUALTRICS_RESPONSE_ID",
]

SNOWFLAKE_DEFAULT_VARIABLE_BLACKLIST = [
    value
    for value in DEFAULT_VARIABLE_BLACKLIST
    if value.lower()
    not in {
        "ad",
        "brand",
        "client",
        "country",
        "industry",
        "methodology",
        "platform",
        "quarter",
        "rdud",
        "year",
    }
]
SNOWFLAKE_DEFAULT_VARIABLE_BLACKLIST.extend(
    [
        "SURVEY_RESPONSE_ID",
        "SURVEY_KEY",
        "SURVEY_STATUS",
        "SURVEY_PROGRESS",
        "DURATION_IN_SECONDS",
        "IS_FINISHED",
        "SURVEY_RESPONSE_RECORDED_AT",
        "START_DATETIME",
        "START_DATE",
        "END_DATETIME",
        "END_DATE",
        "LOCATION_LATITUDE",
        "LOCATION_LONGITUDE",
        "DISTRIBUTION_CHANNEL",
        "USER_LANGUAGE",
        "Q_RELEVANTIDDUPLICATE",
        "Q_RELEVANTIDDUPLICATESCORE",
        "Q_RELEVANTIDFRAUDSCORE",
        "Q_RELEVANTIDLASTSTARTDATE",
        "IS_QUESTION_DELETED",
        "DW_LOAD_DATETIME",
        "DW_MODIFIED_DATETIME",
        "EMBEDDED_DATA",
        *_QUALTRICS_RID_COLUMN_CANDIDATES,
    ]
)

# Snowflake long-format schema constants (RPT_QUALTRICS__SURVEY_RESPONSE).
_SF_RESPONSE_ID_COL = "SURVEY_RESPONSE_ID"
_SF_RESPONSE_KEY_COL = "RESPONSE_KEY"
_SF_SURVEY_KEY_COL = "SURVEY_KEY"
_SF_QUESTION_KEY_COL = "QUESTION_KEY"
_SF_QUESTION_TEXT_COL = "QUESTION_TEXT"
_SF_BLOCK_DESCRIPTION_COL = "BLOCK_DESCRIPTION"
_SF_OPTION_TEXT_COL = "QUESTION_OPTION_TEXT"
_SF_SUB_QUESTION_KEY_COL = "SUB_QUESTION_KEY"
_SF_SUB_QUESTION_TEXT_COL = "SUB_QUESTION_TEXT"
_SF_EMBEDDED_JSON_COL = "EMBEDDED_DATA"
_SF_ANSWER_VALUE_COLUMNS = (
    _SF_OPTION_TEXT_COL,
    "ANSWER_TEXT",
    "RESPONSE_VALUE",
    "ANSWER_VALUE",
    "QUESTION_OPTION_VALUE",
)

# Semicolon is already treated as a multi-select delimiter by metadata parsing
# and avoids ambiguity with answer labels that contain commas.
_MULTI_SELECT_DELIMITER = ";"

_SF_EMBEDDED_KEY_CANDIDATES = [
    "EMBEDDED_DATA_KEY",
    "EMBEDDED_KEY",
    "EMBEDDED_VARIABLE",
    "EMBEDDED_VARIABLE_NAME",
]
_SF_EMBEDDED_VALUE_CANDIDATES = [
    "EMBEDDED_DATA_VALUE",
    "EMBEDDED_VALUE",
    "EMBEDDED_VARIABLE_VALUE",
]
_QUALTRICS_RID_LABELS = {
    "rid",
    "responsekey",
    "response key",
    "response_key",
    "responseid",
    "response id",
    "response_id",
    "qualtrics rid",
    "qualtrics_rid",
    "qualtrics response id",
    "qualtrics_response_id",
}
_SF_LONG_FORMAT_SCHEMA_COLUMNS = {
    _SF_RESPONSE_ID_COL,
    _SF_RESPONSE_KEY_COL,
    _SF_SURVEY_KEY_COL,
    "SURVEY_ID",
    "SURVEY_NAME",
    "SURVEY_STATUS",
    "SURVEY_PROGRESS",
    _SF_QUESTION_KEY_COL,
    "QUESTION_ID",
    _SF_QUESTION_TEXT_COL,
    "QUESTION_TYPE",
    "QUESTION_DESCRIPTION",
    "QUESTION_EXPORT_TAG",
    _SF_BLOCK_DESCRIPTION_COL,
    "QUESTION_OPTION_ID",
    "QUESTION_OPTION_KEY",
    _SF_OPTION_TEXT_COL,
    _SF_EMBEDDED_JSON_COL,
    "QUESTION_OPTION_VALUE",
    _SF_SUB_QUESTION_KEY_COL,
    _SF_SUB_QUESTION_TEXT_COL,
    "ANSWER_TEXT",
    "ANSWER_VALUE",
    "RESPONSE_VALUE",
}
_SF_ROW_ATTRIBUTE_EXCLUDED_PREFIXES = (
    "ANSWER_",
    "CHOICE_",
    "OPTION_",
    "QUESTION_",
    "RECIPIENT_",
    "RESPONSE_",
    "SURVEY_",
)


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
    source_answer_choices: dict[str, list[str]]
    source_question_types: dict[str, str] = field(default_factory=dict)
    question_text_labels: dict[str, str] = field(default_factory=dict)


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


def _blacklist_match_key(value: object) -> str:
    """Normalize column names for default metadata matching."""
    return re.sub(r"[^a-z0-9]+", "", normalize_text(value).lower())


def _dedupe_surviving_columns(
    df: pd.DataFrame,
    question_labels: dict[str, str],
    question_text_labels: dict[str, str] | None = None,
    source_answer_choices: dict[str, list[str]] | None = None,
) -> tuple[pd.DataFrame, dict[str, str], dict[str, str], dict[str, list[str]], list[str]]:
    """Rename duplicate columns that survive blacklist filtering."""
    question_text_labels = question_text_labels or {}
    source_answer_choices = source_answer_choices or {}
    used_columns: set[str] = set()
    base_columns = [
        normalize_text(column) or f"column_{index}"
        for index, column in enumerate(df.columns)
    ]
    reserved_columns = set(base_columns)
    occurrence_counts: dict[str, int] = {}
    deduped_columns: list[str] = []
    renamed_columns: list[str] = []
    deduped_labels: dict[str, str] = {}
    deduped_text_labels: dict[str, str] = {}
    deduped_answer_choices: dict[str, list[str]] = {}

    for column, base_column in zip(df.columns, base_columns):
        occurrence_counts[base_column] = occurrence_counts.get(base_column, 0) + 1
        candidate = base_column
        if candidate in used_columns:
            suffix = occurrence_counts[base_column]
            candidate = f"{base_column}_{suffix}"
            while candidate in used_columns or candidate in reserved_columns:
                suffix += 1
                candidate = f"{base_column}_{suffix}"

        used_columns.add(candidate)
        deduped_columns.append(candidate)
        if candidate != base_column:
            renamed_columns.append(f"{base_column} -> {candidate}")

        label = question_labels.get(column, question_labels.get(base_column, base_column))
        deduped_labels[candidate] = label
        text_label = question_text_labels.get(column, question_text_labels.get(base_column, label))
        if text_label:
            deduped_text_labels[candidate] = text_label
        answer_choices = source_answer_choices.get(column, source_answer_choices.get(base_column, []))
        if answer_choices:
            deduped_answer_choices[candidate] = list(answer_choices)

    if not renamed_columns:
        return df, question_labels, question_text_labels, source_answer_choices, []

    deduped_df = df.copy()
    deduped_df.columns = deduped_columns
    return deduped_df, deduped_labels, deduped_text_labels, deduped_answer_choices, renamed_columns


def _remove_blacklisted_columns(
    df: pd.DataFrame,
    blacklist: list[str],
    blacklist_prefixes: list[str] | None = None,
    whitelist_columns: list[str] | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """Drop blacklisted system columns case-insensitively."""
    blacklist_lookup = {_blacklist_match_key(value) for value in blacklist}
    prefix_lookup = [_blacklist_match_key(value) for value in (blacklist_prefixes or [])]
    whitelist_lookup = {_blacklist_match_key(value) for value in (whitelist_columns or [])}
    removed = []
    for column in df.columns:
        if is_internal_respondent_column(column):
            continue
        normalized = _blacklist_match_key(column)
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


def _is_snowflake_long_format(df: pd.DataFrame) -> bool:
    """Return True when the dataframe matches the Snowflake survey long format."""
    upper_cols = {str(column).upper() for column in df.columns}
    has_respondent_key = _SF_RESPONSE_ID_COL in upper_cols or _SF_RESPONSE_KEY_COL in upper_cols
    has_answer_value = any(column in upper_cols for column in _SF_ANSWER_VALUE_COLUMNS)
    return has_respondent_key and _SF_QUESTION_KEY_COL in upper_cols and has_answer_value


def _humanize_snowflake_attribute_label(column: str) -> str:
    """Return a readable label for a Snowflake respondent attribute column."""
    normalized = normalize_text(column)
    if not normalized:
        return ""
    return normalized.replace("_", " ").title()


def _first_non_empty(values: pd.Series) -> object:
    """Return the first non-empty value in a grouped Snowflake field."""
    for value in values:
        if normalize_text(value):
            return value
    return None


def _find_existing_column(columns: list[str], candidates: list[str]) -> str | None:
    """Return the first candidate column name present in `columns`."""
    column_lookup = {normalize_text(column).upper(): column for column in columns}
    for candidate in candidates:
        match = column_lookup.get(candidate)
        if match:
            return match
    return None


def _analysis_field_count(df: pd.DataFrame) -> int:
    """Return visible analysis columns, excluding internal respondent identity."""
    return sum(1 for column in df.columns if not is_internal_respondent_column(column))


def _build_snowflake_respondent_ids(df: pd.DataFrame, respondent_keys: list[str]) -> pd.Series:
    """Build stable respondent ids from one or more Snowflake key columns."""
    if len(respondent_keys) == 1:
        return df[respondent_keys[0]].map(normalize_text).rename(RESPONDENT_ID_COLUMN)
    return (
        df[respondent_keys]
        .map(normalize_text)
        .agg("::".join, axis=1)
        .rename(RESPONDENT_ID_COLUMN)
    )


def _resolve_snowflake_respondent_keys(df: pd.DataFrame) -> list[str]:
    """Return the best row grouping keys for Snowflake respondent records."""
    response_key_col = _find_existing_column(list(df.columns), [_SF_RESPONSE_KEY_COL])
    if response_key_col:
        return [response_key_col]

    rid_col = _find_existing_column(list(df.columns), _QUALTRICS_RID_COLUMN_CANDIDATES)
    if rid_col:
        return [rid_col]

    respondent_keys = [_SF_RESPONSE_ID_COL]
    if _SF_SURVEY_KEY_COL in df.columns:
        respondent_keys = [_SF_SURVEY_KEY_COL, _SF_RESPONSE_ID_COL]
    return respondent_keys


def _is_qualtrics_rid_label(value: object) -> bool:
    """Return whether a Snowflake embedded key/column names Qualtrics RID."""
    normalized = normalize_text(value).replace("-", " ").replace("_", " ").lower()
    compact = normalized.replace(" ", "")
    return normalized in _QUALTRICS_RID_LABELS or compact in _QUALTRICS_RID_LABELS


def _extract_qualtrics_rid_from_columns(
    df: pd.DataFrame,
    respondent_keys: list[str],
) -> pd.Series | None:
    """Return respondent-key-indexed Qualtrics RID values from explicit columns."""
    rid_col = _find_existing_column(list(df.columns), _QUALTRICS_RID_COLUMN_CANDIDATES)
    if not rid_col:
        return None

    rid_values = df.groupby(respondent_keys, sort=False)[rid_col].agg(_first_non_empty)
    if rid_values.map(normalize_text).eq("").all():
        return None
    return rid_values.map(normalize_text).rename(RESPONDENT_ID_COLUMN)


def _extract_qualtrics_rid_from_embedded_pairs(
    df: pd.DataFrame,
    respondent_keys: list[str],
) -> pd.Series | None:
    """Return respondent-key-indexed Qualtrics RID values from embedded key/value rows."""
    key_col = _find_existing_column(list(df.columns), _SF_EMBEDDED_KEY_CANDIDATES)
    value_col = _find_existing_column(list(df.columns), _SF_EMBEDDED_VALUE_CANDIDATES)
    if not key_col or not value_col:
        return None

    embedded_source = df[[*respondent_keys, key_col, value_col]].copy()
    embedded_source[key_col] = embedded_source[key_col].map(normalize_text)
    rid_source = embedded_source[embedded_source[key_col].map(_is_qualtrics_rid_label)]
    if rid_source.empty:
        return None

    rid_values = rid_source.groupby(respondent_keys, sort=False)[value_col].agg(_first_non_empty)
    if rid_values.map(normalize_text).eq("").all():
        return None
    return rid_values.map(normalize_text).rename(RESPONDENT_ID_COLUMN)


def _build_snowflake_respondent_ids_with_qualtrics_rid(
    df: pd.DataFrame,
    respondent_keys: list[str],
    respondent_index: pd.Index,
) -> pd.Series:
    """Prefer Qualtrics RID for respondent identity, falling back to Snowflake keys."""
    fallback_ids = _build_snowflake_respondent_ids(
        respondent_index.to_frame(index=False),
        respondent_keys,
    )
    fallback_ids.index = respondent_index

    rid_values = _extract_qualtrics_rid_from_columns(df, respondent_keys)
    if rid_values is None:
        rid_values = _extract_qualtrics_rid_from_embedded_pairs(df, respondent_keys)
    if rid_values is None:
        return fallback_ids

    rid_values = rid_values.reindex(respondent_index).map(normalize_text)
    return rid_values.where(rid_values != "", fallback_ids).rename(RESPONDENT_ID_COLUMN)


def _build_wide_snowflake_respondent_ids(df: pd.DataFrame) -> pd.Series | None:
    """Build respondent ids for already-wide Snowflake data."""
    rid_col = _find_existing_column(list(df.columns), _QUALTRICS_RID_COLUMN_CANDIDATES)
    if rid_col:
        rid_values = df[rid_col].map(normalize_text)
        if not rid_values.eq("").all():
            return rid_values.rename(RESPONDENT_ID_COLUMN)

    upper_columns = {normalize_text(column).upper() for column in df.columns}
    if _SF_RESPONSE_ID_COL not in upper_columns:
        return None

    response_id_col = next(
        column for column in df.columns if normalize_text(column).upper() == _SF_RESPONSE_ID_COL
    )
    if _SF_SURVEY_KEY_COL in upper_columns:
        survey_key_col = next(
            column for column in df.columns if normalize_text(column).upper() == _SF_SURVEY_KEY_COL
        )
        return (
            df[[survey_key_col, response_id_col]]
            .map(normalize_text)
            .agg("::".join, axis=1)
            .rename(RESPONDENT_ID_COLUMN)
        )
    return df[response_id_col].map(normalize_text).rename(RESPONDENT_ID_COLUMN)


def _clean_snowflake_question_text(value: object) -> str:
    """Remove Snowflake/Qualtrics presentation suffixes from question text."""
    return re.sub(r"\s*-\s*Label\s*$", "", normalize_text(value), flags=re.IGNORECASE).strip()


def _snowflake_key_part(value: object) -> str:
    """Normalize Snowflake key parts without leaving integer-looking floats."""
    text = normalize_text(value)
    if re.fullmatch(r"\d+\.0", text):
        return text[:-2]
    return text


def _snowflake_analysis_variable_key(question_key: object, sub_question_key: object = None) -> str:
    """Return the respondent-level variable id for a Snowflake question row."""
    parent_key = _snowflake_key_part(question_key)
    statement_key = _snowflake_key_part(sub_question_key)
    if not parent_key:
        return statement_key
    if not statement_key or statement_key.lower() == parent_key.lower():
        return parent_key
    if statement_key.lower().startswith(parent_key.lower()):
        return statement_key
    return f"{parent_key}_{statement_key}"


def _snowflake_row_analysis_variable_key(row: pd.Series) -> str:
    """Return the analysis variable id for a Snowflake long-format row."""
    return _snowflake_analysis_variable_key(
        row.get(_SF_QUESTION_KEY_COL),
        row.get(_SF_SUB_QUESTION_KEY_COL),
    )


def _snowflake_parent_display_label(row: pd.Series) -> str:
    """Return the best parent-question display label for a Snowflake row."""
    for column in [_SF_BLOCK_DESCRIPTION_COL, _SF_QUESTION_TEXT_COL]:
        if column not in row.index:
            continue
        label = _clean_snowflake_question_text(row.get(column))
        if label:
            return label
    return ""


def _compose_snowflake_statement_label(parent_label: str, statement_label: str) -> str:
    """Return a matrix-statement display label without triggering parent grouping."""
    parent = _clean_snowflake_question_text(parent_label)
    statement = _clean_snowflake_question_text(statement_label)
    if statement and parent and statement.lower() != parent.lower():
        return f"{statement} ({parent})"
    return statement or parent


def _snowflake_row_display_label(row: pd.Series) -> str:
    """Return the Page 2/Page 3 display label for a Snowflake question row."""
    statement_label = _clean_snowflake_question_text(row.get(_SF_SUB_QUESTION_TEXT_COL))
    return _compose_snowflake_statement_label(
        _snowflake_parent_display_label(row),
        statement_label,
    )


def _snowflake_row_question_text_label(row: pd.Series) -> str:
    """Return the source question text for a Snowflake question or statement row."""
    parent_text = _clean_snowflake_question_text(row.get(_SF_QUESTION_TEXT_COL))
    statement_text = _clean_snowflake_question_text(row.get(_SF_SUB_QUESTION_TEXT_COL))
    if statement_text and parent_text and statement_text.lower() not in parent_text.lower():
        return f"{parent_text} - {statement_text}"
    return statement_text or parent_text


def _snowflake_response_value(row: pd.Series) -> str:
    """Return the selected response label/value from a Snowflake long-format row."""
    for column in _SF_ANSWER_VALUE_COLUMNS:
        if column not in row.index:
            continue
        value = normalize_text(row.get(column))
        if value:
            return value
    return ""


def _extract_snowflake_question_labels(df: pd.DataFrame) -> dict[str, str]:
    """Map Snowflake analysis variable ids to the friendliest label available."""
    if _SF_QUESTION_KEY_COL not in df.columns:
        return {}

    question_labels: dict[str, str] = {}
    for _, row in df.iterrows():
        key = _snowflake_row_analysis_variable_key(row)
        if not key:
            continue
        label = _snowflake_row_display_label(row) or key
        question_labels.setdefault(key, label)
    return question_labels


def _extract_snowflake_question_text_labels(df: pd.DataFrame) -> dict[str, str]:
    """Map Snowflake analysis variable ids to the source Qualtrics question text."""
    if _SF_QUESTION_KEY_COL not in df.columns or _SF_QUESTION_TEXT_COL not in df.columns:
        return {}

    question_texts: dict[str, str] = {}
    for _, row in df.iterrows():
        key = _snowflake_row_analysis_variable_key(row)
        if not key:
            continue
        text = _snowflake_row_question_text_label(row)
        if text:
            question_texts.setdefault(key, text)
    return question_texts


def _dedupe_snowflake_attribute_column(column: str, existing_columns: set[str]) -> str:
    """Avoid collisions between question keys and embedded-data column names."""
    candidate = normalize_text(column) or "Embedded Variable"
    if candidate not in existing_columns:
        existing_columns.add(candidate)
        return candidate

    base_candidate = f"{candidate}_embedded"
    candidate = base_candidate
    suffix = 2
    while candidate in existing_columns:
        candidate = f"{base_candidate}_{suffix}"
        suffix += 1
    existing_columns.add(candidate)
    return candidate


def _serialize_embedded_value(value: object) -> str:
    """Return a stable scalar representation for embedded-data values."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return normalize_text(value)


def _parse_snowflake_embedded_data(value: object) -> dict[str, str]:
    """Parse Qualtrics embedded-data JSON into a key/value mapping."""
    if isinstance(value, dict):
        payload = value
    else:
        text = normalize_text(value)
        if not text:
            return {}
        try:
            payload = json.loads(text)
        except (TypeError, ValueError):
            return {}

    if not isinstance(payload, dict):
        return {}

    parsed: dict[str, str] = {}
    for key, raw_value in payload.items():
        column = normalize_text(key)
        if not column:
            continue
        parsed[column] = _serialize_embedded_value(raw_value)
    return parsed


def _extract_snowflake_embedded_json_attributes(
    df: pd.DataFrame,
    respondent_keys: list[str],
    existing_columns: set[str],
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Expand the Snowflake EMBEDDED_DATA JSON payload into respondent-level columns."""
    embedded_col = _find_existing_column(list(df.columns), [_SF_EMBEDDED_JSON_COL])
    respondent_index = df.groupby(respondent_keys, sort=False).size().index
    if not embedded_col:
        return pd.DataFrame(index=respondent_index), {}

    values_by_respondent: dict[object, dict[str, str]] = {
        index_value: {} for index_value in respondent_index
    }
    key_order: list[str] = []

    for _, row in df[[*respondent_keys, embedded_col]].iterrows():
        respondent_key = (
            row[respondent_keys[0]]
            if len(respondent_keys) == 1
            else tuple(row[key] for key in respondent_keys)
        )
        parsed = _parse_snowflake_embedded_data(row[embedded_col])
        if not parsed:
            continue
        respondent_values = values_by_respondent.setdefault(respondent_key, {})
        for embedded_key, embedded_value in parsed.items():
            if embedded_key not in key_order:
                key_order.append(embedded_key)
            if embedded_key not in respondent_values or not normalize_text(respondent_values[embedded_key]):
                respondent_values[embedded_key] = embedded_value

    if not key_order:
        return pd.DataFrame(index=respondent_index), {}

    rename_map: dict[str, str] = {}
    embedded_labels: dict[str, str] = {}
    for embedded_key in key_order:
        deduped_column = _dedupe_snowflake_attribute_column(embedded_key, existing_columns)
        rename_map[embedded_key] = deduped_column
        embedded_labels[deduped_column] = _humanize_snowflake_attribute_label(embedded_key)

    rows = []
    for index_value in respondent_index:
        source_values = values_by_respondent.get(index_value, {})
        rows.append({
            rename_map[embedded_key]: source_values.get(embedded_key, "")
            for embedded_key in key_order
        })
    embedded_df = pd.DataFrame(rows, index=respondent_index)
    return embedded_df, embedded_labels


def _extract_snowflake_embedded_key_value_attributes(
    df: pd.DataFrame,
    respondent_keys: list[str],
    existing_columns: set[str],
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Pivot key/value embedded-data rows into respondent-level attributes."""
    key_col = _find_existing_column(list(df.columns), _SF_EMBEDDED_KEY_CANDIDATES)
    value_col = _find_existing_column(list(df.columns), _SF_EMBEDDED_VALUE_CANDIDATES)
    if not key_col or not value_col:
        return pd.DataFrame(index=df.groupby(respondent_keys, sort=False).size().index), {}

    embedded_source = df[[*respondent_keys, key_col, value_col]].copy()
    embedded_source[key_col] = embedded_source[key_col].map(normalize_text)
    embedded_source = embedded_source[embedded_source[key_col] != ""]
    if embedded_source.empty:
        return pd.DataFrame(index=df.groupby(respondent_keys, sort=False).size().index), {}

    embedded_df = (
        embedded_source.groupby([*respondent_keys, key_col], sort=False)[value_col]
        .agg(_first_non_empty)
        .unstack(key_col)
    )
    embedded_labels: dict[str, str] = {}
    rename_map: dict[str, str] = {}
    for column in embedded_df.columns:
        deduped_column = _dedupe_snowflake_attribute_column(str(column), existing_columns)
        rename_map[column] = deduped_column
        embedded_labels[deduped_column] = _humanize_snowflake_attribute_label(str(column))

    embedded_df = embedded_df.rename(columns=rename_map)
    return embedded_df, embedded_labels


def _is_snowflake_respondent_attribute_candidate(column: str) -> bool:
    """Return whether a Snowflake long-format column may be respondent-level data."""
    upper_column = normalize_text(column).upper()
    if not upper_column:
        return False
    if upper_column in _SF_LONG_FORMAT_SCHEMA_COLUMNS:
        return False
    if upper_column in _SF_EMBEDDED_KEY_CANDIDATES or upper_column in _SF_EMBEDDED_VALUE_CANDIDATES:
        return False
    if any(upper_column.startswith(prefix) for prefix in _SF_ROW_ATTRIBUTE_EXCLUDED_PREFIXES):
        return False
    return True


def _extract_snowflake_respondent_attributes(
    df: pd.DataFrame,
    respondent_keys: list[str],
    existing_columns: set[str],
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Extract embedded variables stored as repeated respondent-level columns."""
    respondent_index = df.groupby(respondent_keys, sort=False).size().index
    attributes = pd.DataFrame(index=respondent_index)
    attribute_labels: dict[str, str] = {}

    for column in df.columns:
        if not _is_snowflake_respondent_attribute_candidate(column):
            continue

        grouped = df.groupby(respondent_keys, sort=False)[column]
        unique_counts = grouped.nunique(dropna=True)
        if (unique_counts > 1).any():
            continue

        values = grouped.agg(_first_non_empty)
        if values.map(normalize_text).eq("").all():
            continue

        deduped_column = _dedupe_snowflake_attribute_column(str(column), existing_columns)
        attributes[deduped_column] = values
        attribute_labels[deduped_column] = _humanize_snowflake_attribute_label(str(column))

    return attributes, attribute_labels


def _pivot_snowflake_long_to_wide(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Pivot Snowflake respondent-question rows into one row per respondent."""
    df = df.copy()
    df.columns = [str(column).upper() for column in df.columns]

    question_labels = _extract_snowflake_question_labels(df)
    question_text_labels = _extract_snowflake_question_text_labels(df)
    analysis_key_col = "__BLS_ANALYSIS_VARIABLE__"
    answer_value_col = "__BLS_ANSWER_VALUE__"
    df[analysis_key_col] = df.apply(_snowflake_row_analysis_variable_key, axis=1)
    df[answer_value_col] = df.apply(_snowflake_response_value, axis=1)
    df = df[df[analysis_key_col].map(normalize_text) != ""]

    def _join_responses(values: pd.Series) -> object:
        parts = [normalize_text(value) for value in values if normalize_text(value)]
        return _MULTI_SELECT_DELIMITER.join(parts) if parts else None

    respondent_keys = _resolve_snowflake_respondent_keys(df)

    wide_df = (
        df.groupby([*respondent_keys, analysis_key_col], sort=False)[answer_value_col]
        .agg(_join_responses)
        .unstack(analysis_key_col)
    )
    respondent_ids = _build_snowflake_respondent_ids_with_qualtrics_rid(df, respondent_keys, wide_df.index)
    wide_df.insert(0, RESPONDENT_ID_COLUMN, respondent_ids)

    existing_columns = {str(column) for column in wide_df.columns}
    json_attrs, json_attr_labels = _extract_snowflake_embedded_json_attributes(
        df,
        respondent_keys,
        existing_columns,
    )
    key_value_attrs, key_value_labels = _extract_snowflake_embedded_key_value_attributes(
        df,
        respondent_keys,
        existing_columns,
    )
    column_attrs, column_attr_labels = _extract_snowflake_respondent_attributes(
        df,
        respondent_keys,
        existing_columns,
    )
    if not json_attrs.empty:
        wide_df = wide_df.join(json_attrs)
        question_labels.update(json_attr_labels)
    if not key_value_attrs.empty:
        wide_df = wide_df.join(key_value_attrs)
        question_labels.update(key_value_labels)
    if not column_attrs.empty:
        wide_df = wide_df.join(column_attrs)
        question_labels.update(column_attr_labels)

    wide_df = wide_df.reset_index(drop=True)
    wide_df.columns.name = None
    wide_df.attrs["question_text_labels"] = question_text_labels
    return wide_df, question_labels


def extract_snowflake_label_maps(df: pd.DataFrame) -> tuple[dict[str, str], dict[str, str]]:
    """Return Snowflake display/question-text labels without rebuilding the full intake."""
    raw_df = df.copy()
    raw_df.columns = [str(column).upper() for column in raw_df.columns]
    if _SF_QUESTION_KEY_COL not in raw_df.columns:
        return {}, {}
    return _extract_snowflake_question_labels(raw_df), _extract_snowflake_question_text_labels(raw_df)


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
    (
        prepared_df,
        question_labels,
        source_answer_choices,
        source_question_types,
        collapsed_multi_response_groups,
    ) = normalize_wide_checkbox_groups(prepared_df, question_labels)
    if collapsed_multi_response_groups:
        log_lines.append(
            "Collapsed "
            f"{collapsed_multi_response_groups} checkbox question group(s) "
            "into multi-select question columns."
        )

    no_tech_df, removed_columns = _remove_blacklisted_columns(
        prepared_df,
        blacklist,
        DEFAULT_BLACKLIST_PREFIXES,
        whitelist_columns,
    )
    log_lines.append(f"Removed {len(removed_columns)} blacklisted column(s).")
    source_answer_choices = {
        column: list(source_answer_choices.get(column, []))
        for column in no_tech_df.columns
        if source_answer_choices.get(column)
    }
    source_question_types = {
        column: source_question_types.get(column, "")
        for column in no_tech_df.columns
        if source_question_types.get(column)
    }
    no_tech_df, question_labels, _, source_answer_choices, deduped_columns = _dedupe_surviving_columns(
        no_tech_df,
        question_labels,
        source_answer_choices=source_answer_choices,
    )
    source_question_types = {
        column: source_question_types.get(column, "")
        for column in no_tech_df.columns
        if source_question_types.get(column)
    }
    if deduped_columns:
        log_lines.append("Renamed duplicate column(s): " + ", ".join(deduped_columns) + ".")

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
        source_answer_choices=source_answer_choices,
        source_question_types=source_question_types,
    )


def ingest_snowflake_dataframe(
    df: pd.DataFrame,
    source_name: str,
    blacklist: list[str] | None = None,
    whitelist_columns: list[str] | None = None,
) -> IngestionResult:
    """Adapt a Snowflake survey dataframe into a respondent-level result."""
    blacklist = unique_preserving_order(blacklist or SNOWFLAKE_DEFAULT_VARIABLE_BLACKLIST)
    completed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    raw_df = df.copy()
    raw_df.columns = [str(column) for column in raw_df.columns]
    raw_df = raw_df.reset_index(drop=True)

    log_lines = [f"Loaded from Snowflake: `{source_name}`."]
    if _is_snowflake_long_format(raw_df):
        log_lines.append("Prepared Snowflake survey responses as one record per respondent.")
        wide_df, question_labels = _pivot_snowflake_long_to_wide(raw_df)
        question_text_labels = dict(wide_df.attrs.get("question_text_labels", {}))
        log_lines.append(
            f"Prepared {respondent_count(wide_df):,} respondent(s) and {_analysis_field_count(wide_df):,} analysis field(s)."
        )
    else:
        wide_df = raw_df
        question_labels = {column: column for column in wide_df.columns}
        question_text_labels = question_labels.copy()
        respondent_ids = _build_wide_snowflake_respondent_ids(wide_df)
        if respondent_ids is not None:
            wide_df[RESPONDENT_ID_COLUMN] = respondent_ids

    no_tech_df, removed_columns = _remove_blacklisted_columns(
        wide_df,
        blacklist,
        DEFAULT_BLACKLIST_PREFIXES,
        whitelist_columns,
    )
    log_lines.append(f"Removed {len(removed_columns)} blacklisted column(s).")
    no_tech_df, question_labels, question_text_labels, _, deduped_columns = _dedupe_surviving_columns(
        no_tech_df,
        question_labels,
        question_text_labels,
    )
    if deduped_columns:
        log_lines.append("Renamed duplicate column(s): " + ", ".join(deduped_columns) + ".")

    cell_column = _resolve_cell_column(list(no_tech_df.columns))
    if no_tech_df.empty:
        raise ValueError("No data returned from Snowflake query.")

    question_labels = {
        column: question_labels.get(column, column)
        for column in no_tech_df.columns
    }
    question_text_labels = {
        column: question_text_labels.get(column, question_labels.get(column, column))
        for column in no_tech_df.columns
    }
    log_lines.append(
        f"Final dataset contains {respondent_count(no_tech_df):,} respondent(s) and {_analysis_field_count(no_tech_df):,} analysis field(s)."
    )

    return IngestionResult(
        raw_df=raw_df,
        cleaned_df=no_tech_df,
        question_labels=question_labels,
        cell_column=cell_column,
        blacklist_used=blacklist,
        log_lines=log_lines,
        metadata_rows_removed=0,
        removed_columns=removed_columns,
        sheet_name="Snowflake",
        completed_at=completed_at,
        source_answer_choices={},
        question_text_labels=question_text_labels,
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


def ingest_qualtrics_sav(
    uploaded_file,
    blacklist: list[str] | None = None,
    whitelist_columns: list[str] | None = None,
) -> IngestionResult:
    """Ingest, clean, and validate a Qualtrics SPSS SAV export."""
    read_result = read_sav_upload(uploaded_file)
    blacklist = unique_preserving_order(blacklist or DEFAULT_VARIABLE_BLACKLIST)
    completed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    log_lines = [f"Loaded SAV data from `{uploaded_file.name}`."]
    log_lines.append("Preserved SAV variable labels and value labels for metadata defaults.")
    if read_result.collapsed_multi_response_groups:
        log_lines.append(
            "Collapsed "
            f"{read_result.collapsed_multi_response_groups} SAV multiple-response set(s) "
            "into multi-select question columns."
        )

    no_tech_df, removed_columns = _remove_blacklisted_columns(
        read_result.dataframe,
        blacklist,
        DEFAULT_BLACKLIST_PREFIXES,
        whitelist_columns,
    )
    log_lines.append(f"Removed {len(removed_columns)} blacklisted column(s).")

    cell_column = _resolve_cell_column(list(no_tech_df.columns))
    if no_tech_df.empty:
        raise ValueError("All respondent rows were removed during cleaning. Check the source export.")

    question_labels = {
        column: read_result.question_labels.get(column, column)
        for column in no_tech_df.columns
    }
    source_answer_choices = {
        column: list(read_result.source_answer_choices.get(column, []))
        for column in no_tech_df.columns
        if read_result.source_answer_choices.get(column)
    }
    source_question_types = {
        column: read_result.source_question_types.get(column, "")
        for column in no_tech_df.columns
        if read_result.source_question_types.get(column)
    }
    no_tech_df, question_labels, _, source_answer_choices, deduped_columns = _dedupe_surviving_columns(
        no_tech_df,
        question_labels,
        source_answer_choices=source_answer_choices,
    )
    source_question_types = {
        column: source_question_types.get(column, "")
        for column in no_tech_df.columns
        if source_question_types.get(column)
    }
    if deduped_columns:
        log_lines.append("Renamed duplicate column(s): " + ", ".join(deduped_columns) + ".")
    log_lines.append(
        f"Final dataset contains {len(no_tech_df):,} respondent rows and {len(no_tech_df.columns):,} columns."
    )

    return IngestionResult(
        raw_df=read_result.dataframe,
        cleaned_df=no_tech_df,
        question_labels=question_labels,
        cell_column=cell_column,
        blacklist_used=blacklist,
        log_lines=log_lines,
        metadata_rows_removed=0,
        removed_columns=removed_columns,
        sheet_name=read_result.sheet_name,
        completed_at=completed_at,
        source_answer_choices=source_answer_choices,
        source_question_types=source_question_types,
    )
