"""Question metadata detection and editing helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any
import re

import pandas as pd

from src.utils import normalize_text, split_multi_select_value, split_text_outside_grouping


DEFAULT_INCLUDE_VALUE = True
QUESTION_TYPES = [
    "Single-Select",
    "Multi-Select",
    "Scale / Likert",
    "Numeric Data",
    "Open-End Text",
    "Ignore",
]


def get_display_variable_name(metadata_row: dict[str, Any]) -> str:
    """Return the analyst-facing variable name, falling back to the raw variable."""
    # 2026-05-15 BD: Displayed variable names are a readability/export layer;
    # raw variable names remain the internal keys for data joins and saved configs.
    return normalize_text(metadata_row.get("display_variable_name")) or normalize_text(metadata_row.get("variable"))


def build_display_variable_lookup(question_metadata: list[dict[str, Any]]) -> dict[str, str]:
    """Build a raw-variable to display-variable lookup."""
    return {
        normalize_text(row.get("variable")): get_display_variable_name(row)
        for row in question_metadata
        if normalize_text(row.get("variable"))
    }


LIKERT_PATTERNS = [
    "strongly disagree",
    "disagree",
    "neutral",
    "agree",
    "strongly agree",
    "very dissatisfied",
    "dissatisfied",
    "satisfied",
    "very satisfied",
]

SCALE_LABEL_HINTS = [
    "on a scale",
    "scale of",
    "where 1 is",
    "where 1 =",
    "agree or disagree",
    "how likely",
    "how familiar",
    "to what extent",
    "feel about",
    "how interested",
    "familiar are you",
    "familiarity",
    "brand affinity",
    "brand sentiment",
    "sentiment",
    "interest",
    "affinity",
    "relationship with",
]

SCALE_VALUE_HINTS = [
    "very interested",
    "extremely familiar",
    "very familiar",
    "somewhat familiar",
    "moderately familiar",
    "slightly familiar",
    "not very familiar",
    "not at all familiar",
    "unfamiliar",
    "somewhat interested",
    "moderately interested",
    "not that interested",
    "not very interested",
    "not at all interested",
    "love it",
    "like it",
    "neutral",
    "dislike it",
    "hate it",
    "very likely",
    "quite likely",
    "moderately likely",
    "not that likely",
    "somewhat likely",
    "not likely",
    "very unlikely",
    "somewhat better",
    "about the same",
    "much worse",
    "much better",
    "somewhat worse",
    "dedicated harry potter fan",
    "new to the series but interested",
    "nostalgic toward it",
    "not a fan",
    "leads much more often",
    "leads somewhat more often",
    "follows somewhat more often",
    "follows much more often",
    "follows more often",
    "about the same",
    "somewhat worse",
    "much worse",
    "somewhat better",
    "much better",
]

SCALE_POSITIVE_TERMS = [
    "authentic",
    "trustworthy",
    "informative",
    "familiar",
    "credible",
    "believable",
    "clear",
    "relevant",
    "useful",
    "appealing",
    "positive",
]

SCALE_NEGATIVE_TERMS = [
    "inauthentic",
    "untrustworthy",
    "uninformative",
    "unfamiliar",
    "not familiar",
    "not at all familiar",
    "not very familiar",
    "not trustworthy",
    "not informative",
    "not authentic",
    "not credible",
    "not believable",
    "unclear",
    "irrelevant",
    "not useful",
    "unappealing",
    "negative",
]

SCALE_ORDER_PATTERNS = [
    ("love it", 0),
    ("very unlikely", 4),
    ("not at all interested", 4),
    ("not at all likely", 4),
    ("not very interested", 3),
    ("not that interested", 3),
    ("strongly disagree", 4),
    ("dislike it", 3),
    ("hate it", 4),
    ("very likely", 0),
    ("very interested", 0),
    ("strongly agree", 0),
    ("much better", 0),
    ("leads much more often", 0),
    ("quite likely", 1),
    ("somewhat likely", 1),
    ("somewhat interested", 1),
    ("somewhat agree", 1),
    ("somewhat better", 1),
    ("like it", 1),
    ("leads somewhat more often", 1),
    ("about the same", 2),
    ("neutral", 2),
    ("moderately interested", 2),
    ("moderately likely", 2),
    ("neither agree nor disagree", 2),
    ("follows somewhat more often", 2),
    ("somewhat worse", 3),
    ("not that likely", 3),
    ("not likely", 3),
    ("somewhat disagree", 3),
    ("follows much more often", 3),
    ("follows more often", 3),
    ("much worse", 4),
]

HP_INTEREST_ORDER_PATTERNS = [
    ("i am a dedicated harry potter fan", 0),
    ("i enjoyed it in the past and feel nostalgic toward it", 1),
    ("i'm new to the series but interested", 2),
    ("i’m new to the series but interested", 2),
    ("i'm not a fan", 3),
    ("i’m not a fan", 3),
]

EXCLUSIVE_RESPONSE_PATTERNS = [
    "none of the above",
    "none",
    "other",
    "prefer not to say",
    "don't know",
    "dont know",
    "unsure",
    "not applicable",
    "n/a",
]


def _count_pattern_hits(values: list[str], patterns: list[str]) -> int:
    """Count how many values match any pattern in a hint list."""
    return sum(any(pattern in value for pattern in patterns) for value in values)


def _count_scored_scale_hits(choices: list[str]) -> int:
    """Count how many choices match one of the known ordered scale patterns."""
    return sum(1 for choice in choices if _scale_choice_score(choice) is not None)


def _count_hp_interest_hits(choices: list[str]) -> int:
    """Count how many choices match the Harry Potter fandom ordering patterns."""
    hits = 0
    for choice in choices:
        normalized = choice.lower()
        if any(pattern in normalized for pattern, _ in HP_INTEREST_ORDER_PATTERNS):
            hits += 1
    return hits


def _clean_scale_anchor_label(label: str) -> str:
    """Trim punctuation and leftover survey wording from a numeric scale anchor."""
    cleaned = normalize_text(label)
    cleaned = re.split(r"\s+(?:how|when|if|for|would|did|does|do|are|were|was)\b", cleaned, maxsplit=1)[0]
    return cleaned.strip(" ,.;:?!()[]{}\"'")


def _extract_numeric_scale_anchors(question_label: str) -> tuple[int, str, int, str] | None:
    """Parse labels such as `where 1 is Poor and 5 is Excellent` from question text."""
    label = normalize_text(question_label)
    label_lower = label.lower()
    if "scale" not in label_lower and "where" not in label_lower:
        return None

    pattern = re.compile(
        r"\b(?P<first_num>\d{1,2})\s*(?:=|is|means|indicates|represents|being)\s*"
        r"(?P<first_label>.+?)"
        r"(?:,?\s+(?:and|to|through)\s+|,\s*|/\s*)"
        r"(?P<second_num>\d{1,2})\s*(?:=|is|means|indicates|represents|being)\s*"
        r"(?P<second_label>.+?)(?:[,.?;]|$)",
        re.IGNORECASE,
    )
    match = pattern.search(label)
    if not match:
        return None

    first_num = int(match.group("first_num"))
    second_num = int(match.group("second_num"))
    if first_num == second_num:
        return None

    first_label = _clean_scale_anchor_label(match.group("first_label"))
    second_label = _clean_scale_anchor_label(match.group("second_label"))
    if not first_label or not second_label:
        return None
    return first_num, first_label, second_num, second_label


def _has_numeric_scale_anchor(question_label: str) -> bool:
    """Return whether question text names the two ends of a numeric scale."""
    return _extract_numeric_scale_anchors(question_label) is not None


def _has_comma_delimiter_evidence(values: list[str]) -> bool:
    """Return whether commas appear to separate recurring multi-select choices."""
    if not values:
        return False

    candidate_rows: list[tuple[str, list[str]]] = []
    part_sources: dict[str, set[str]] = {}
    for value in values:
        parts = split_text_outside_grouping(value, ",")
        if len(parts) <= 1:
            continue
        candidate_rows.append((value, parts))
        for part in set(parts):
            part_sources.setdefault(part, set()).add(value)

    if len(candidate_rows) / len(values) < 0.3:
        return False

    varied_parts = [
        part
        for part, source_values in part_sources.items()
        if len(source_values) >= 2
    ]
    return len(varied_parts) >= 2


def _is_multi_select(series: pd.Series) -> bool:
    values = [normalize_text(value) for value in series.dropna().tolist() if normalize_text(value)]
    if not values:
        return False

    semicolon_ratio = sum(
        len(split_text_outside_grouping(value, ";")) > 1
        for value in values
    ) / len(values)
    if semicolon_ratio >= 0.3:
        return True

    return _has_comma_delimiter_evidence(values)


def _is_scale(series: pd.Series, question_label: str = "") -> bool:
    values = [normalize_text(value).lower() for value in series.dropna().tolist() if normalize_text(value)]
    if not values:
        return False
    unique_values = sorted(set(values))
    if len(unique_values) > 11:
        return False
    label_lower = question_label.lower()
    if _has_numeric_scale_anchor(question_label) and len(unique_values) <= 11:
        return True
    if any(token in label_lower for token in SCALE_LABEL_HINTS):
        if len(unique_values) <= 7:
            return True
    pattern_hits = _count_pattern_hits(unique_values, LIKERT_PATTERNS)
    if pattern_hits >= 2:
        return True
    value_hint_hits = _count_pattern_hits(unique_values, SCALE_VALUE_HINTS)
    if value_hint_hits >= 2 and len(unique_values) <= 7:
        return True
    scored_scale_hits = _count_scored_scale_hits(unique_values)
    if scored_scale_hits >= max(3, len(unique_values) - 1) and len(unique_values) <= 7:
        return True
    if len(unique_values) in {4, 5}:
        ordered_candidates = _sort_scale_choices(unique_values)
        if _count_scored_scale_hits(ordered_candidates) >= 3:
            return True
    numeric_like = pd.to_numeric(pd.Series(unique_values), errors="coerce")
    if numeric_like.notna().all() and len(unique_values) <= 10:
        return True
    return False


def _is_numeric(series: pd.Series) -> bool:
    coerced = pd.to_numeric(series, errors="coerce")
    non_null_ratio = coerced.notna().mean()
    unique_values = coerced.dropna().nunique()
    return float(non_null_ratio) >= 0.8 and int(unique_values) >= 8


def _is_open_text(series: pd.Series) -> bool:
    values = series.dropna().astype(str).str.strip()
    if values.empty:
        return False
    unique_ratio = values.nunique() / max(len(values), 1)
    avg_length = values.map(len).mean()
    return float(unique_ratio) >= 0.5 and float(avg_length) >= 15


def guess_question_type(series: pd.Series, question_label: str = "") -> str:
    """Classify a survey variable using value-level heuristics only."""
    label_lower = question_label.lower()
    if "select all that apply" in label_lower or _is_multi_select(series):
        return "Multi-Select"
    if _is_scale(series, question_label):
        return "Scale / Likert"
    if _is_numeric(series):
        return "Numeric Data"
    if _is_open_text(series):
        return "Open-End Text"
    return "Single-Select"


def get_metadata_editor_columns() -> dict[str, Any]:
    """Build Streamlit column config lazily so the heuristics remain UI-independent."""
    import streamlit as st

    return {
        "variable": st.column_config.TextColumn("Raw Variable Name", disabled=True, width=220),
        "display_variable_name": st.column_config.TextColumn(
            "Displayed Variable Name",
            width=260,
            help="Edit the name analysts should see in later setup pages and Excel exports.",
        ),
        "question_label": st.column_config.TextColumn("Question Text", disabled=True, width=620),
        "detected_type": st.column_config.SelectboxColumn(
            "Question Type",
            options=QUESTION_TYPES,
            required=True,
            width=170,
        ),
        "answer_choice_count": st.column_config.NumberColumn(
            "Answer Choices Count",
            disabled=True,
            width=190,
        ),
        "answer_choices": st.column_config.TextColumn(
            "Answer Choices",
            width=1400,
            help="Edit answer choices using a new line or `|` between labels for clear separation.",
        ),
    }


def _sort_age_choices(choices: list[str]) -> list[str]:
    """Sort common age bucket labels into ascending age order."""
    scored: list[tuple[tuple[int, int], str]] = []
    unmatched: list[str] = []
    for choice in choices:
        matched_score = _age_bucket_key(choice)
        if matched_score is None:
            unmatched.append(choice)
        else:
            scored.append((matched_score, choice))
    if not scored:
        return choices
    ordered = [choice for _, choice in sorted(scored, key=lambda item: item[0])]
    ordered.extend(unmatched)
    return ordered


def _age_bucket_key(choice: str) -> tuple[int, int] | None:
    """Convert common age bucket labels into a sortable (start_age, end_age) key."""
    normalized = choice.lower().strip()

    under_match = re.search(r"under\s+(\d+)", normalized)
    if under_match:
        upper = int(under_match.group(1))
        return (0, upper)

    plus_match = re.search(r"(\d+)\s*\+", normalized)
    if plus_match:
        lower = int(plus_match.group(1))
        return (lower, 999)

    range_match = re.search(r"(\d+)\s*-\s*(\d+)", normalized)
    if range_match:
        lower = int(range_match.group(1))
        upper = int(range_match.group(2))
        return (lower, upper)

    return None


def _sort_scale_choices(choices: list[str], question_label: str = "") -> list[str]:
    """Sort common scale labels from most positive to most negative."""
    anchored_choices = _sort_numeric_anchor_scale_choices(choices, question_label)
    if anchored_choices is not None:
        return anchored_choices

    numeric_choices = _sort_numeric_scale_choices(choices)
    if numeric_choices is not None:
        return numeric_choices

    scored: list[tuple[tuple[int, int], int, str]] = []
    unmatched: list[tuple[int, str]] = []
    for index, choice in enumerate(choices):
        matched_score = _scale_choice_score(choice)
        if matched_score is None:
            unmatched.append((index, choice))
        else:
            scored.append((matched_score, index, choice))
    if not scored:
        return choices
    ordered = [choice for _, _, choice in sorted(scored, key=lambda item: (item[0], item[1]))]
    ordered.extend(choice for _, choice in unmatched)
    return ordered


def _contains_phrase(normalized: str, phrase: str) -> bool:
    """Return whether a normalized choice contains a phrase on token boundaries."""
    return re.search(rf"(?<![a-z]){re.escape(phrase)}(?![a-z])", normalized) is not None


def _simple_numeric_choice_value(choice: str) -> float | None:
    """Parse simple numeric scale labels while ignoring ranges and mixed labels."""
    text = normalize_text(choice)
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return float(text)
    return None


def _sort_numeric_scale_choices(choices: list[str]) -> list[str] | None:
    """Sort plain numeric scale choices from highest to lowest by default."""
    scored: list[tuple[float, int, str]] = []
    unmatched: list[tuple[int, str]] = []
    for index, choice in enumerate(choices):
        value = _simple_numeric_choice_value(choice)
        if value is None:
            unmatched.append((index, choice))
        else:
            scored.append((value, index, choice))

    if len(scored) < max(2, len(choices) - 1):
        return None

    ordered = [choice for _, _, choice in sorted(scored, key=lambda item: (-item[0], item[1]))]
    ordered.extend(choice for _, choice in unmatched)
    return ordered


def _scale_anchor_positive_number(anchors: tuple[int, str, int, str]) -> int:
    """Infer which endpoint number represents the more positive side."""
    first_num, first_label, second_num, second_label = anchors
    first_score = _scale_choice_score(first_label)
    second_score = _scale_choice_score(second_label)

    if first_score is not None and second_score is not None:
        if first_score[0] < second_score[0]:
            return first_num
        if second_score[0] < first_score[0]:
            return second_num

    if first_score is not None and second_score is None:
        return first_num if first_score[0] <= 2 else second_num
    if second_score is not None and first_score is None:
        return second_num if second_score[0] <= 2 else first_num

    return max(first_num, second_num)


def _choice_matches_anchor_label(choice: str, anchor_label: str) -> bool:
    """Return whether a response choice represents a named endpoint label."""
    normalized_choice = choice.lower().strip()
    normalized_label = anchor_label.lower().strip()
    if not normalized_choice or not normalized_label:
        return False
    return normalized_choice == normalized_label or _contains_phrase(normalized_choice, normalized_label)


def _choice_scale_number(choice: str, anchors: tuple[int, str, int, str]) -> int | None:
    """Resolve a response choice to a numeric scale point using label anchors."""
    first_num, first_label, second_num, second_label = anchors
    low = min(first_num, second_num)
    high = max(first_num, second_num)
    normalized = choice.lower().strip()

    leading_match = re.match(r"^\s*(\d{1,2})(?:\b|[\s).:\-])", normalized)
    if leading_match:
        value = int(leading_match.group(1))
        if low <= value <= high:
            return value

    number_matches = [int(match.group(0)) for match in re.finditer(r"\b\d{1,2}\b", normalized)]
    in_range_matches = [value for value in number_matches if low <= value <= high]
    if len(in_range_matches) == 1:
        return in_range_matches[0]

    if _choice_matches_anchor_label(normalized, first_label):
        return first_num
    if _choice_matches_anchor_label(normalized, second_label):
        return second_num
    return None


def _sort_numeric_anchor_scale_choices(choices: list[str], question_label: str) -> list[str] | None:
    """Sort choices using explicit numeric endpoint labels in the question text."""
    anchors = _extract_numeric_scale_anchors(question_label)
    if anchors is None:
        return None

    positive_num = _scale_anchor_positive_number(anchors)
    descending = positive_num == max(anchors[0], anchors[2])
    scored: list[tuple[int, int, str]] = []
    unmatched: list[tuple[int, str]] = []

    for index, choice in enumerate(choices):
        scale_number = _choice_scale_number(choice, anchors)
        if scale_number is None:
            unmatched.append((index, choice))
            continue
        sort_value = -scale_number if descending else scale_number
        scored.append((sort_value, index, choice))

    required_matches = max(2, len(choices) - 1)
    if len(scored) < required_matches:
        return None

    ordered = [choice for _, _, choice in sorted(scored, key=lambda item: (item[0], item[1]))]
    ordered.extend(choice for _, choice in unmatched)
    return ordered


def _scale_choice_score(choice: str) -> tuple[int, int] | None:
    """Score one scale label so obvious positive-to-negative families sort consistently.

    Inputs:
        choice: One answer-choice label from a scale question.

    Outputs:
        A sortable tuple where lower values are more positive. Returns `None`
        when the label does not match any known scale family.
    """
    normalized = choice.lower().strip()

    if _contains_phrase(normalized, "leads much more often"):
        return (0, 0)
    if _contains_phrase(normalized, "leads somewhat more often"):
        return (1, 0)
    if _contains_phrase(normalized, "follows somewhat more often"):
        return (3, 0)
    if _contains_phrase(normalized, "follows much more often") or _contains_phrase(normalized, "follows more often"):
        return (4, 0)

    if _contains_phrase(normalized, "i am a dedicated harry potter fan"):
        return (0, 0)
    if _contains_phrase(normalized, "feel nostalgic toward it"):
        return (1, 0)
    if _contains_phrase(normalized, "new to the series but interested"):
        return (2, 0)
    if _contains_phrase(normalized, "not a fan"):
        return (4, 0)

    if _contains_phrase(normalized, "love it"):
        return (0, 0)
    if _contains_phrase(normalized, "dislike it"):
        return (3, 0)
    if _contains_phrase(normalized, "hate it"):
        return (4, 0)
    if _contains_phrase(normalized, "like it"):
        return (1, 0)
    if _contains_phrase(normalized, "neutral") or _contains_phrase(normalized, "about the same") or _contains_phrase(normalized, "neither agree nor disagree"):
        return (2, 0)

    if _contains_phrase(normalized, "much better"):
        return (0, 0)
    if _contains_phrase(normalized, "somewhat better"):
        return (1, 0)
    if _contains_phrase(normalized, "somewhat worse"):
        return (3, 0)
    if _contains_phrase(normalized, "much worse"):
        return (4, 0)

    if _contains_phrase(normalized, "strongly agree"):
        return (0, 0)
    if _contains_phrase(normalized, "somewhat agree"):
        return (1, 0)
    if _contains_phrase(normalized, "somewhat disagree"):
        return (3, 0)
    if _contains_phrase(normalized, "strongly disagree"):
        return (4, 0)
    if _contains_phrase(normalized, "agree"):
        return (1, 0)
    if _contains_phrase(normalized, "disagree"):
        return (3, 0)

    if _contains_phrase(normalized, "very satisfied"):
        return (0, 0)
    if _contains_phrase(normalized, "satisfied"):
        return (1, 0)
    if _contains_phrase(normalized, "very dissatisfied"):
        return (4, 0)
    if _contains_phrase(normalized, "dissatisfied"):
        return (3, 0)

    positive_weight = None
    if "not at all " in normalized or "very unlikely" in normalized or "not familiar" in normalized:
        positive_weight = 4
    elif "not that " in normalized or "not very " in normalized or "not likely" in normalized:
        positive_weight = 3
    elif "slightly " in normalized or "a little " in normalized:
        positive_weight = 3
    elif "moderately " in normalized:
        positive_weight = 2
    elif "quite " in normalized or "somewhat " in normalized:
        positive_weight = 1
    elif "extremely " in normalized or "very " in normalized:
        positive_weight = 0

    if positive_weight is not None:
        if any(_contains_phrase(normalized, token) for token in ["interested", "likely", "unlikely", "familiar"]):
            return (positive_weight, 1)

    for term in SCALE_NEGATIVE_TERMS:
        if _contains_phrase(normalized, term):
            return (4, 2)
    for term in SCALE_POSITIVE_TERMS:
        if _contains_phrase(normalized, term):
            return (0, 2)

    for pattern, score in SCALE_ORDER_PATTERNS:
        if pattern in normalized:
            return (score, 9)
    return None


def _sort_pattern_list(choices: list[str], ordered_patterns: list[tuple[str, int]]) -> list[str]:
    """Sort choices by a custom ordered pattern list, preserving unmatched items afterward."""
    scored: list[tuple[int, int, str]] = []
    unmatched: list[tuple[int, str]] = []
    for index, choice in enumerate(choices):
        normalized = choice.lower()
        matched_score = None
        for pattern, score in ordered_patterns:
            if pattern in normalized:
                matched_score = score
                break
        if matched_score is None:
            unmatched.append((index, choice))
        else:
            scored.append((matched_score, index, choice))
    if not scored:
        return choices
    ordered = [choice for _, _, choice in sorted(scored, key=lambda item: (item[0], item[1]))]
    ordered.extend(choice for _, choice in unmatched)
    return ordered


def _anchor_exclusive_choices_last(choices: list[str]) -> list[str]:
    """Move exclusive response options like none/other/prefer not to say to the end."""
    regular_choices: list[str] = []
    exclusive_choices: list[str] = []
    for choice in choices:
        normalized = choice.lower()
        if any(pattern in normalized for pattern in EXCLUSIVE_RESPONSE_PATTERNS):
            exclusive_choices.append(choice)
        else:
            regular_choices.append(choice)
    return regular_choices + exclusive_choices


def sort_answer_choices(answer_choices: list[str], question_type: str, question_label: str = "") -> list[str]:
    """Apply practical default ordering for common answer-choice patterns."""
    if not answer_choices:
        return []

    label_lower = question_label.lower()
    age_hits = sum(1 for choice in answer_choices if _age_bucket_key(choice) is not None)
    if "age" in label_lower or age_hits >= max(2, len(answer_choices) // 2):
        return _anchor_exclusive_choices_last(_sort_age_choices(answer_choices))
    if (
        "relationship with the harry potter series" in label_lower
        or _count_hp_interest_hits(answer_choices) >= 2
    ):
        return _anchor_exclusive_choices_last(_sort_pattern_list(answer_choices, HP_INTEREST_ORDER_PATTERNS))
    if question_type == "Scale / Likert":
        return _anchor_exclusive_choices_last(_sort_scale_choices(answer_choices, question_label))
    return _anchor_exclusive_choices_last(answer_choices)


def extract_answer_choices(series: pd.Series, question_type: str, question_label: str = "") -> list[str]:
    """Extract unique answer choices in display order for supported question types."""
    values = [normalize_text(value) for value in series.dropna().tolist()]
    if not values:
        return []

    if question_type == "Multi-Select":
        choices: list[str] = []
        allow_comma = _has_comma_delimiter_evidence(values)
        for value in values:
            parts = split_multi_select_value(value, allow_comma=allow_comma)
            for part in parts:
                if part not in choices:
                    choices.append(part)
        return sort_answer_choices(choices, question_type, question_label)

    if question_type in {"Open-End Text", "Numeric Data", "Ignore"}:
        return []

    choices = []
    for value in values:
        if value and value not in choices:
            choices.append(value)
    return sort_answer_choices(choices, question_type, question_label)


def serialize_answer_choices(answer_choices: list[str]) -> str:
    """Serialize answer choices into an editable display string."""
    return " | ".join(answer_choices)


def parse_answer_choices(answer_choices_text: str) -> list[str]:
    """Parse edited answer-choice text back into a normalized list."""
    parts = [part.strip() for part in re.split(r"\||\n", answer_choices_text) if part.strip()]
    return parts


def detect_question_types(
    df: pd.DataFrame,
    question_labels: dict[str, str],
    cell_col: str | None = None,
) -> dict[str, str]:
    """Detect default question types for all relevant variables."""
    detected: dict[str, str] = {}
    for column in df.columns:
        if column == cell_col:
            detected[column] = "Ignore"
            continue
        detected[column] = guess_question_type(df[column], question_labels.get(column, ""))
    return detected


def build_question_metadata(
    df: pd.DataFrame,
    question_labels: dict[str, str],
    cell_col: str | None = None,
) -> list[dict[str, Any]]:
    """Build the default editable metadata package for the audit page."""
    detected = detect_question_types(df, question_labels, cell_col)
    metadata: list[dict[str, Any]] = []
    for column in df.columns:
        question_type = detected[column]
        answer_choices = extract_answer_choices(df[column], question_type, question_labels.get(column, column))
        metadata.append(
            {
                "variable": column,
                "display_variable_name": column,
                "question_label": question_labels.get(column, column),
                "detected_type": question_type,
                "answer_choices": serialize_answer_choices(answer_choices),
                "answer_choices_list": answer_choices,
                "include": DEFAULT_INCLUDE_VALUE if question_type != "Ignore" else False,
                "notes": "System split variable" if column == cell_col else "",
            }
        )
    return metadata


def prepare_metadata_editor_frame(metadata_rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert metadata rows to a dataframe for `st.data_editor`."""
    editor_rows = []
    for row in metadata_rows:
        editor_rows.append(
            {
                "variable": row.get("variable", ""),
                "display_variable_name": get_display_variable_name(row),
                "question_label": row.get("question_label", ""),
                "detected_type": row.get("detected_type", "Single-Select"),
                "answer_choice_count": len(row.get("answer_choices_list", [])),
                "answer_choices": row.get("answer_choices", ""),
            }
        )
    return pd.DataFrame(editor_rows)


def sanitize_metadata_editor(editor_df: pd.DataFrame) -> list[dict[str, Any]]:
    """Normalize edited metadata rows into a safe JSON-serializable structure."""
    if editor_df.empty:
        return []
    sanitized: list[dict[str, Any]] = []
    for row in editor_df.to_dict(orient="records"):
        detected_type = normalize_text(row.get("detected_type")) or "Single-Select"
        if detected_type not in QUESTION_TYPES:
            detected_type = "Single-Select"
        answer_choices_text = normalize_text(row.get("answer_choices"))
        sanitized.append(
            {
                "variable": normalize_text(row.get("variable")),
                "display_variable_name": normalize_text(row.get("display_variable_name"))
                or normalize_text(row.get("variable")),
                "question_label": normalize_text(row.get("question_label")),
                "detected_type": detected_type,
                "answer_choice_count": len(parse_answer_choices(answer_choices_text)),
                "answer_choices": answer_choices_text,
                "answer_choices_list": parse_answer_choices(answer_choices_text),
                "include": detected_type != "Ignore",
                "notes": "",
            }
        )
    return sanitized


def merge_metadata_editor_with_source(
    editor_df: pd.DataFrame,
    previous_metadata: list[dict[str, Any]],
    source_df: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Merge edited metadata with source data, recalculating answer choices when type changes."""
    sanitized = sanitize_metadata_editor(editor_df)
    previous_lookup = {row.get("variable"): row for row in previous_metadata}
    merged: list[dict[str, Any]] = []

    for row in sanitized:
        variable = row["variable"]
        previous_row = previous_lookup.get(variable, {})
        old_type = previous_row.get("detected_type")
        new_type = row["detected_type"]
        previous_answer_text = normalize_text(previous_row.get("answer_choices", ""))
        edited_answer_text = normalize_text(row.get("answer_choices", ""))

        if (
            variable in source_df.columns
            and old_type != new_type
            and edited_answer_text == previous_answer_text
        ):
            recalculated_choices = extract_answer_choices(
                source_df[variable],
                new_type,
                row.get("question_label", variable),
            )
            row["answer_choice_count"] = len(recalculated_choices)
            row["answer_choices"] = serialize_answer_choices(recalculated_choices)
            row["answer_choices_list"] = recalculated_choices

        merged.append(row)

    return merged


def restore_metadata_defaults(
    df: pd.DataFrame,
    question_labels: dict[str, str],
    cell_col: str | None = None,
) -> list[dict[str, Any]]:
    """Rebuild question metadata using the default heuristics."""
    return build_question_metadata(df, question_labels, cell_col)


def build_metadata_change_log_entry(variable: str, old_type: str | None, new_type: str) -> str:
    """Build a timestamped audit log entry."""
    timestamp = datetime.now().strftime("%H:%M")
    return f"[{timestamp}] {variable}: Type changed from {old_type or 'Unknown'} to {new_type}"


def summarize_included_questions(metadata_rows: list[dict[str, Any]]) -> str:
    """Return a simple included-question count summary."""
    total = len(metadata_rows)
    included = sum(1 for row in metadata_rows if row.get("include"))
    return f"{included}/{total}"
