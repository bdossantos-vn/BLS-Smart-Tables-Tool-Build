"""Shared Streamlit multiselect safeguards."""

from __future__ import annotations

import html
import re
from typing import Any, Callable

import streamlit as st

from src.utils import normalize_text


def widget_key_token(value: object) -> str:
    """Return a compact token for variable-scoped Streamlit widget keys."""
    token = re.sub(r"[^A-Za-z0-9_]+", "_", normalize_text(value)).strip("_")
    return token or "blank"


def valid_multiselect_values(values: list[Any], options: list[Any]) -> list[Any]:
    """Return nonblank selected values that are still available options."""
    option_lookup: dict[str, Any] = {}
    for option in options:
        signature = normalize_text(option)
        if signature and signature not in option_lookup:
            option_lookup[signature] = option

    cleaned_values: list[Any] = []
    seen: set[str] = set()
    for value in values:
        signature = normalize_text(value)
        if not signature or signature not in option_lookup or signature in seen:
            continue
        cleaned_values.append(option_lookup[signature])
        seen.add(signature)
    return cleaned_values


def reconcile_multiselect_values(
    current_values: list[Any],
    options: list[Any],
    default_values: list[Any] | None = None,
    *,
    reset_invalid_to_default: bool = False,
) -> list[Any]:
    """Clean current values, optionally replacing wholly invalid state with defaults."""
    cleaned_values = valid_multiselect_values(current_values, options)
    cleaned_defaults = valid_multiselect_values(default_values or [], options)
    if reset_invalid_to_default and current_values and not cleaned_values and cleaned_defaults:
        return cleaned_defaults
    return cleaned_values


def sanitize_multiselect_session_values(
    key: str,
    options: list[Any],
    default_values: list[Any] | None = None,
    *,
    reset_invalid_to_default: bool = False,
) -> list[Any]:
    """Remove blank/stale values from a Streamlit multiselect before rendering."""
    cleaned_defaults = valid_multiselect_values(default_values or [], options)
    if key not in st.session_state:
        return cleaned_defaults

    current_values = st.session_state.get(key, [])
    if not isinstance(current_values, list):
        st.session_state[key] = cleaned_defaults
        return cleaned_defaults

    cleaned_values = reconcile_multiselect_values(
        current_values,
        options,
        cleaned_defaults,
        reset_invalid_to_default=reset_invalid_to_default,
    )
    if cleaned_values != current_values:
        st.session_state[key] = cleaned_values
    return cleaned_values


def multiselect_display_label(
    value: Any,
    format_func: Callable[[Any], str] | None = None,
) -> str:
    """Return the label Streamlit should show for a selected multiselect value."""
    if format_func is None:
        return normalize_text(value)
    try:
        display_value = format_func(value)
    except Exception:
        display_value = value
    return normalize_text(display_value) or normalize_text(value)


def selected_multiselect_labels(
    values: list[Any],
    format_func: Callable[[Any], str] | None = None,
) -> list[str]:
    """Return display labels for selected multiselect values."""
    labels: list[str] = []
    for value in values:
        label = multiselect_display_label(value, format_func)
        if label:
            labels.append(label)
    return labels


def render_selected_multiselect_summary(
    values: list[Any],
    format_func: Callable[[Any], str] | None = None,
    *,
    label: str = "Selected",
) -> None:
    """Render selected multiselect labels outside the native chip UI."""
    display_labels = selected_multiselect_labels(values, format_func)
    if not display_labels:
        return
    escaped_label = html.escape(label)
    escaped_values = html.escape(", ".join(display_labels))
    st.markdown(
        f'<div class="vn-selected-values"><strong>{escaped_label}:</strong> {escaped_values}</div>',
        unsafe_allow_html=True,
    )


def safe_multiselect(
    label: str,
    *,
    options: list[Any],
    key: str,
    default: list[Any] | None = None,
    reset_invalid_to_default: bool = False,
    format_func: Callable[[Any], str] | None = None,
    show_selected_summary: bool = True,
    selected_summary_label: str = "Selected",
    **kwargs: Any,
) -> list[Any]:
    """Render a multiselect that cannot keep blank or stale selected chips."""
    option_values = list(options)
    default_values = valid_multiselect_values(default or [], option_values)
    key_exists = key in st.session_state
    sanitize_multiselect_session_values(
        key,
        option_values,
        default_values,
        reset_invalid_to_default=reset_invalid_to_default,
    )
    multiselect_kwargs: dict[str, Any] = {
        "options": option_values,
        "key": key,
        **kwargs,
    }
    if not key_exists:
        multiselect_kwargs["default"] = default_values
    if format_func is not None:
        multiselect_kwargs["format_func"] = format_func
    selected_values = st.multiselect(label, **multiselect_kwargs)
    if show_selected_summary:
        render_selected_multiselect_summary(
            selected_values,
            format_func,
            label=selected_summary_label,
        )
    return selected_values
