"""Branding helpers for the Streamlit shell."""

from __future__ import annotations

from pathlib import Path

import streamlit as st


LOGO_PATH = Path(__file__).resolve().parents[1] / "assets" / "vn_logo.png"


def render_sidebar_brand() -> None:
    """Render the VN logo and product name in the sidebar.

    Inputs:
        None.

    Outputs:
        None. The function writes branded sidebar content.
    """
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), use_container_width=True)
    st.markdown(
        """
        <div style="margin-top:0.35rem; margin-bottom:0.9rem;">
            <div style="font-size:0.78rem; letter-spacing:0.14em; text-transform:uppercase; opacity:0.7;">
                Viral Nation
            </div>
            <div style="font-size:1.25rem; font-weight:700; line-height:1.1;">
                BLS Smart Tables Tool
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_page_brand_header() -> None:
    """Render a compact branded header above the current page content.

    Inputs:
        None.

    Outputs:
        None. The function writes a reusable header block into the page.
    """
    logo_html = ""
    if LOGO_PATH.exists():
        logo_html = (
            f'<img src="data:image/png;base64,{_logo_base64()}" '
            'style="height:42px; width:auto; display:block;" alt="Viral Nation logo" />'
        )

    st.markdown(
        f"""
        <div class="vn-brand-bar">
            {logo_html}
            <div class="vn-brand-copy">
                <div class="vn-brand-kicker">Viral Nation</div>
                <div class="vn-brand-title">BLS Smart Tables Tool</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _logo_base64() -> str:
    """Return the bundled logo image encoded for inline HTML use.

    Inputs:
        None.

    Outputs:
        A base64-encoded string representation of the logo file.
    """
    import base64

    return base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")
