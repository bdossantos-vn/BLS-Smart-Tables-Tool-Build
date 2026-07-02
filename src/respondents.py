"""Respondent identity helpers used for N/base counts."""

from __future__ import annotations

import pandas as pd

from src.utils import normalize_text


RESPONDENT_ID_COLUMN = "__respondent_id__"


def is_internal_respondent_column(column: object) -> bool:
    """Return whether a dataframe column is used only for respondent identity."""
    return normalize_text(column) == RESPONDENT_ID_COLUMN


def respondent_count(df: pd.DataFrame, mask: pd.Series | None = None) -> int:
    """Count unique respondents when an internal respondent id is available."""
    if df is None or getattr(df, "empty", True):
        return 0

    if mask is None:
        filtered = df
    else:
        aligned_mask = mask.reindex(df.index, fill_value=False).astype(bool)
        filtered = df.loc[aligned_mask]

    if RESPONDENT_ID_COLUMN not in filtered.columns:
        return int(len(filtered))

    ids = filtered[RESPONDENT_ID_COLUMN].map(normalize_text)
    ids = ids[ids != ""]
    return int(ids.nunique())
