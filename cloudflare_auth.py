"""Optional Cloudflare Access JWT validation for Streamlit."""

from __future__ import annotations

import json
import os
import urllib.request

import streamlit as st

_TEAM_DOMAIN = os.environ.get("CLOUDFLARE_TEAM_DOMAIN", "")
_AUD = os.environ.get("CLOUDFLARE_AUD", "")


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_public_keys(team_domain: str) -> list:
    """Fetch and cache Cloudflare Access JWKS for one hour."""
    url = f"https://{team_domain}/cdn-cgi/access/certs"
    with urllib.request.urlopen(url, timeout=5) as response:
        jwks = json.loads(response.read())
    return jwks.get("keys", [])


def validate_cloudflare_jwt() -> None:
    """Stop the app when Cloudflare Access is configured and the request is invalid."""
    if not _AUD or not _TEAM_DOMAIN:
        return

    try:
        import jwt
    except ModuleNotFoundError:
        st.error("403 - Cloudflare Access validation requires PyJWT to be installed.")
        st.stop()

    token = st.context.headers.get("Cf-Access-Jwt-Assertion", "")
    if not token:
        st.error("403 - Access denied: no Cloudflare Access token present.")
        st.stop()

    keys = _fetch_public_keys(_TEAM_DOMAIN)
    for key_data in keys:
        try:
            public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key_data))
            jwt.decode(token, public_key, algorithms=["RS256"], audience=_AUD)
            return
        except jwt.ExpiredSignatureError:
            st.error("403 - Your Cloudflare Access session has expired. Please log in again.")
            st.stop()
        except jwt.InvalidAudienceError:
            st.error("403 - Access denied: token audience mismatch.")
            st.stop()
        except jwt.InvalidSignatureError:
            continue

    st.error("403 - Access denied: invalid Cloudflare Access token.")
    st.stop()
