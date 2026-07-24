"""Global theme helpers for Streamlit UI branding.

This module centralizes visual styling so the app can keep a consistent
brand look without repeating CSS across page files.
"""

from __future__ import annotations

import streamlit as st


def apply_theme() -> None:
    """Inject the shared VN theme into the current Streamlit page.

    Inputs:
        None. The function reads no external arguments.

    Outputs:
        None. It writes CSS into the current Streamlit page.

    Notes:
        The requested font is Proxima Nova. Because a local font file was not
        provided in the repo, we use a safe font stack that prefers Proxima
        Nova when it exists on the user's machine and falls back gracefully.
    """
    st.markdown(
        """
        <style>
            :root {
                --vn-black: #000000;
                --vn-white: #FFFFFF;
                --vn-red: #FF005C;
                --vn-orange: #FF6927;
                --vn-yellow: #FFC227;
                --vn-gray-50: #F8F8FA;
                --vn-gray-100: #F1F2F5;
                --vn-gray-200: #E2E5EA;
                --vn-gray-400: #8A8F98;
            }

            html, body, [class*="css"]  {
                font-family: "Proxima Nova", "Avenir Next", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
            }

            .stApp {
                background:
                    radial-gradient(circle at top right, rgba(255, 194, 39, 0.10), transparent 24%),
                    radial-gradient(circle at top left, rgba(255, 0, 92, 0.07), transparent 30%),
                    var(--vn-white);
                color: var(--vn-black);
                color-scheme: light;
            }

            [data-testid="stSidebar"] {
                background: linear-gradient(180deg, #090909 0%, #161616 100%);
                border-right: 1px solid rgba(255, 255, 255, 0.06);
            }

            [data-testid="stSidebar"] * {
                color: var(--vn-white);
            }

            [data-testid="stSidebar"] .stButton > button,
            [data-testid="stSidebar"] .stDownloadButton > button {
                color: var(--vn-black);
                background: var(--vn-white);
            }

            [data-testid="stSidebar"] .stButton > button *,
            [data-testid="stSidebar"] .stDownloadButton > button * {
                color: var(--vn-black) !important;
                fill: var(--vn-black) !important;
            }

            [data-testid="stSidebar"] .stButton > button:hover *,
            [data-testid="stSidebar"] .stDownloadButton > button:hover * {
                color: var(--vn-white) !important;
                fill: var(--vn-white) !important;
            }

            [data-testid="stSidebar"] hr {
                border-color: rgba(255, 255, 255, 0.14);
            }

            h1, h2, h3, h4, h5, h6 {
                color: var(--vn-black);
                letter-spacing: -0.02em;
            }

            [data-testid="stMain"] label,
            [data-testid="stMain"] legend,
            [data-testid="stMain"] p,
            [data-testid="stMain"] span,
            [data-testid="stMain"] div[data-testid="stMarkdownContainer"] * {
                color: var(--vn-black);
            }

            [data-testid="stMain"] code,
            [data-testid="stMain"] code * {
                color: var(--vn-black) !important;
                background: var(--vn-white) !important;
                border-color: var(--vn-gray-200) !important;
            }

            [data-testid="stMain"] [role="radiogroup"] label,
            [data-testid="stMain"] [role="radiogroup"] label *,
            [data-testid="stMain"] [data-baseweb="radio"] label,
            [data-testid="stMain"] [data-baseweb="radio"] label * {
                color: var(--vn-black) !important;
                fill: var(--vn-black) !important;
            }

            [data-testid="stMain"] [data-testid="stFileUploader"] section,
            [data-testid="stMain"] [data-testid="stFileUploader"] section * {
                color: var(--vn-black) !important;
            }

            [data-testid="stMain"] [data-testid="stFileUploader"] section {
                background: var(--vn-white) !important;
                border: 1px solid var(--vn-gray-200) !important;
            }

            [data-testid="stMain"] [data-testid="stFileUploaderDropzone"],
            [data-testid="stMain"] [data-testid="stFileUploaderDropzone"] * {
                background: var(--vn-white) !important;
                color: var(--vn-black) !important;
                fill: var(--vn-black) !important;
                border-color: var(--vn-gray-200) !important;
            }

            [data-testid="stMain"] [data-testid="stFileUploader"] button,
            [data-testid="stMain"] [data-testid="stFileUploader"] button *,
            [data-testid="stMain"] [data-testid="stFileUploader"] [data-testid="stBaseButton-secondary"],
            [data-testid="stMain"] [data-testid="stFileUploader"] [data-testid="stBaseButton-secondary"] * {
                color: var(--vn-black) !important;
                fill: var(--vn-black) !important;
                background: var(--vn-white) !important;
                border-color: var(--vn-gray-200) !important;
            }

            [data-testid="stMain"] [data-testid="stFileUploader"] small,
            [data-testid="stMain"] [data-testid="stFileUploader"] [data-testid="stFileUploaderFile"],
            [data-testid="stMain"] [data-testid="stFileUploader"] [data-testid="stFileUploaderFile"] * {
                color: var(--vn-black) !important;
                fill: var(--vn-black) !important;
                background: var(--vn-white) !important;
            }

            [data-testid="stMain"] [data-testid="stFileUploader"] [data-baseweb="tag"],
            [data-testid="stMain"] [data-testid="stFileUploader"] [data-baseweb="tag"] * {
                background: var(--vn-white) !important;
                color: var(--vn-black) !important;
                fill: var(--vn-black) !important;
                border-color: var(--vn-gray-200) !important;
            }

            .vn-brand-bar {
                display: flex;
                align-items: center;
                gap: 1rem;
                padding: 0.85rem 1rem;
                margin: 0 0 1.25rem 0;
                background: linear-gradient(90deg, rgba(0, 0, 0, 0.98) 0%, rgba(21, 21, 21, 0.96) 70%, rgba(255, 0, 92, 0.92) 100%);
                border-radius: 18px;
                box-shadow: 0 16px 36px rgba(0, 0, 0, 0.14);
            }

            .vn-brand-copy {
                display: flex;
                flex-direction: column;
                gap: 0.1rem;
            }

            .vn-brand-kicker {
                color: rgba(255, 255, 255, 0.72);
                font-size: 0.82rem;
                text-transform: uppercase;
                letter-spacing: 0.14em;
            }

            .vn-brand-title {
                color: var(--vn-white);
                font-size: 1.2rem;
                font-weight: 700;
                line-height: 1.1;
            }

            .vn-brand-bar *,
            .vn-brand-copy *,
            .vn-brand-title {
                color: var(--vn-white) !important;
                fill: var(--vn-white) !important;
            }

            .vn-brand-kicker {
                color: rgba(255, 255, 255, 0.72) !important;
            }

            .vn-brand-version {
                color: rgba(255, 255, 255, 0.68) !important;
                font-size: 0.76rem;
                line-height: 1.1;
            }

            .stButton > button,
            .stDownloadButton > button {
                border-radius: 14px;
                border: 1px solid var(--vn-black);
                color: var(--vn-black);
                background: var(--vn-white);
                font-weight: 700;
                transition: all 0.18s ease;
            }

            .stButton > button:hover,
            .stDownloadButton > button:hover {
                border-color: var(--vn-red);
                color: var(--vn-white);
                background: linear-gradient(90deg, var(--vn-red) 0%, var(--vn-orange) 100%);
            }

            .stButton > button[kind="primary"],
            .stDownloadButton > button[kind="primary"] {
                color: var(--vn-white);
                border-color: transparent;
                background: linear-gradient(90deg, var(--vn-red) 0%, var(--vn-orange) 100%);
                box-shadow: 0 12px 28px rgba(255, 0, 92, 0.22);
            }

            .stButton > button[kind="primary"]:hover,
            .stDownloadButton > button[kind="primary"]:hover {
                filter: brightness(1.02);
                transform: translateY(-1px);
            }

            [data-testid="stMain"] div[data-baseweb="select"] > div,
            [data-testid="stMain"] div[data-baseweb="input"] > div,
            [data-testid="stMain"] textarea,
            [data-testid="stMain"] input {
                border-radius: 14px !important;
                background: var(--vn-white) !important;
                color: var(--vn-black) !important;
            }

            [data-testid="stMain"] div[data-baseweb="select"] *,
            [data-testid="stMain"] div[data-baseweb="input"] * {
                color: var(--vn-black) !important;
                fill: var(--vn-black) !important;
            }

            [data-baseweb="popover"] {
                z-index: 999999 !important;
            }

            [data-baseweb="popover"] [role="listbox"],
            [data-baseweb="popover"] [data-baseweb="menu"],
            [data-baseweb="popover"] ul {
                min-width: min(44rem, calc(100vw - 2rem)) !important;
                max-width: min(64rem, calc(100vw - 2rem)) !important;
                width: max-content !important;
                background: var(--vn-white) !important;
                border: 1px solid var(--vn-gray-200) !important;
                border-radius: 14px !important;
                box-shadow: 0 18px 44px rgba(0, 0, 0, 0.14) !important;
            }

            [data-baseweb="popover"] [role="option"],
            [data-baseweb="popover"] [data-baseweb="menu"] li,
            [data-baseweb="popover"] li {
                align-items: flex-start !important;
                height: auto !important;
                min-height: 2.5rem !important;
                padding-top: 0.55rem !important;
                padding-bottom: 0.55rem !important;
                white-space: normal !important;
            }

            [data-baseweb="popover"] [role="option"] *,
            [data-baseweb="popover"] [data-baseweb="menu"] li *,
            [data-baseweb="popover"] li * {
                color: var(--vn-black) !important;
                fill: var(--vn-black) !important;
                max-width: none !important;
                overflow: visible !important;
                overflow-wrap: anywhere !important;
                text-overflow: clip !important;
                white-space: normal !important;
                word-break: normal !important;
            }

            [data-testid="stMain"] div[data-baseweb="select"] [data-baseweb="tag"] {
                align-items: center !important;
                display: inline-flex !important;
                max-width: 100% !important;
                min-width: 0 !important;
                width: auto !important;
            }

            [data-testid="stMain"] div[data-baseweb="select"] [data-baseweb="tag"] > span,
            [data-testid="stMain"] div[data-baseweb="select"] [data-baseweb="tag"] > div {
                direction: ltr !important;
                flex: 0 1 auto !important;
                max-width: 100% !important;
                min-width: 0 !important;
                overflow: hidden !important;
                text-align: left !important;
                text-overflow: ellipsis !important;
                white-space: nowrap !important;
                width: auto !important;
            }

            [data-testid="stMain"] div[data-baseweb="select"] [data-baseweb="tag"] > button,
            [data-testid="stMain"] div[data-baseweb="select"] [data-baseweb="tag"] svg {
                flex: 0 0 auto !important;
            }

            [data-testid="stMain"] div[data-baseweb="select"] [role="combobox"] span,
            [data-testid="stMain"] div[data-baseweb="select"] [role="combobox"] div {
                direction: ltr !important;
                text-align: left !important;
                text-overflow: ellipsis !important;
            }

            [data-testid="stMain"] .vn-selected-values {
                color: #45484f !important;
                font-size: 0.9rem !important;
                line-height: 1.35 !important;
                margin: 0.15rem 0 0.45rem 0 !important;
                overflow-wrap: anywhere !important;
                white-space: normal !important;
            }

            [data-testid="stMain"] .vn-selected-values strong {
                color: var(--vn-black) !important;
                font-weight: 700 !important;
            }

            [data-testid="stMain"] [data-baseweb="tag"],
            [data-testid="stMain"] [data-baseweb="tag"] *,
            [data-testid="stMain"] [data-baseweb="button-group"] *,
            [data-testid="stMain"] [data-testid="stExpander"] summary,
            [data-testid="stMain"] [data-testid="stExpander"] summary *,
            [data-testid="stMain"] details {
                color: var(--vn-black) !important;
                fill: var(--vn-black) !important;
                background: var(--vn-white) !important;
                border-color: var(--vn-gray-200) !important;
            }

            [data-testid="stMain"] [data-testid="stExpander"] [role="button"],
            [data-testid="stMain"] [data-testid="stExpander"] [role="button"] * {
                color: var(--vn-black) !important;
                fill: var(--vn-black) !important;
                background: var(--vn-white) !important;
            }

            [data-testid="stMetric"] {
                background: var(--vn-white) !important;
                border: 1px solid var(--vn-gray-200);
                border-radius: 18px;
                padding: 1rem 1rem 0.8rem 1rem;
                box-shadow: 0 8px 20px rgba(0, 0, 0, 0.05);
            }

            [data-testid="stMetric"] * {
                color: var(--vn-black) !important;
            }

            [data-testid="stAlert"] {
                border-radius: 18px;
                border-width: 1px;
            }

            [data-testid="stDataFrame"],
            [data-testid="stDataFrameGlideDataEditor"],
            [data-testid="stDataEditor"],
            [data-testid="stElementToolbar"] + div [data-testid*="GlideDataEditor"] {
                --gdg-bg-cell: var(--vn-white) !important;
                --gdg-bg-cell-medium: var(--vn-white) !important;
                --gdg-bg-header: var(--vn-white) !important;
                --gdg-bg-header-has-focus: var(--vn-white) !important;
                --gdg-bg-header-hovered: var(--vn-gray-50) !important;
                --gdg-bg-icon-header: var(--vn-white) !important;
                --gdg-fg-icon-header: var(--vn-black) !important;
                --gdg-text-dark: var(--vn-black) !important;
                --gdg-text-medium: #333333 !important;
                --gdg-text-light: #666666 !important;
                --gdg-text-header: var(--vn-black) !important;
                --gdg-text-group-header: var(--vn-black) !important;
                --gdg-border-color: var(--vn-gray-200) !important;
                --gdg-horizontal-border-color: var(--vn-gray-200) !important;
                --gdg-drilldown-border: var(--vn-gray-200) !important;
                --gdg-link-color: var(--vn-black) !important;
                --gdg-accent-color: var(--vn-red) !important;
                --gdg-accent-fg: var(--vn-white) !important;
                --gdg-accent-light: rgba(255, 0, 92, 0.14) !important;
                color-scheme: light !important;
                background: var(--vn-white) !important;
                color: var(--vn-black) !important;
            }

            [data-testid="stDataFrameGlideDataEditor"] canvas,
            [data-testid="stDataEditor"] canvas,
            [data-testid*="GlideDataEditor"] canvas {
                background: var(--vn-white) !important;
            }

            [data-testid="stDataFrameGlideDataEditor"] input,
            [data-testid="stDataEditor"] input,
            [data-testid*="GlideDataEditor"] input,
            [data-testid="stDataFrameGlideDataEditor"] textarea,
            [data-testid="stDataEditor"] textarea,
            [data-testid*="GlideDataEditor"] textarea {
                color: var(--vn-black) !important;
                background: var(--vn-white) !important;
            }

            details {
                border-radius: 18px;
                border: 1px solid var(--vn-gray-200);
                background: rgba(255, 255, 255, 0.85);
            }

            .stTabs [data-baseweb="tab-list"] {
                gap: 0.5rem;
            }

            .stTabs [data-baseweb="tab"] {
                border-radius: 999px;
                padding-inline: 1rem;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )
