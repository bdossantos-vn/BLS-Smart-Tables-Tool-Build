"""Snowflake connection helper for the BLS Smart Tables Tool."""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st


_SURVEYS_QUERY = (
    "SELECT DISTINCT SURVEY_NAME, SURVEY_KEY "
    "FROM SNOWFLAKE_EDW.EDW.RPT_QUALTRICS__SURVEY_RESPONSE "
    "ORDER BY SURVEY_NAME"
)

_SURVEY_DATA_QUERY = (
    "SELECT * FROM SNOWFLAKE_EDW.EDW.RPT_QUALTRICS__SURVEY_RESPONSE "
    "WHERE SURVEY_KEY = '{key}'"
)


def _session_is_alive(session) -> bool:
    try:
        session.sql("SELECT 1").collect()
        return True
    except Exception:
        return False


@st.cache_resource(show_spinner=False, validate=_session_is_alive)
def get_snowflake_session():
    """Return a Snowflake Snowpark Session, or None if unavailable."""
    try:
        from snowflake.snowpark.context import get_active_session

        return get_active_session()
    except Exception:
        pass

    if os.environ.get("GCP_PROJECT"):
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        project = os.environ["GCP_PROJECT"]

        def _get_secret(name: str) -> str:
            resource = f"projects/{project}/secrets/{name}/versions/latest"
            response = client.access_secret_version(request={"name": resource})
            return response.payload.data.decode("UTF-8")

        connection_params: dict[str, object] = {
            "account": _get_secret("SNOWFLAKE_ACCOUNT"),
            "user": _get_secret("SNOWFLAKE_USER"),
            "warehouse": _get_secret("SNOWFLAKE_WAREHOUSE"),
            "database": _get_secret("SNOWFLAKE_DATABASE"),
            "schema": _get_secret("SNOWFLAKE_SCHEMA"),
            "role": _get_secret("SNOWFLAKE_ROLE"),
            "client_session_keep_alive": True,
        }

        try:
            from cryptography.hazmat.primitives import serialization

            pem_bytes = _get_secret("SNOWFLAKE_PRIVATE_KEY").encode("utf-8")
            private_key = serialization.load_pem_private_key(pem_bytes, password=None)
            connection_params["private_key"] = private_key.private_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        except Exception:
            connection_params["password"] = _get_secret("SNOWFLAKE_PASSWORD")
    else:

        def _local(key: str) -> str:
            try:
                return st.secrets.get(key, os.environ.get(key, ""))
            except Exception:
                return os.environ.get(key, "")

        connection_params = {
            "account": _local("SNOWFLAKE_ACCOUNT"),
            "user": _local("SNOWFLAKE_USER"),
            "warehouse": _local("SNOWFLAKE_WAREHOUSE"),
            "database": _local("SNOWFLAKE_DATABASE"),
            "schema": _local("SNOWFLAKE_SCHEMA"),
            "role": _local("SNOWFLAKE_ROLE"),
            "client_session_keep_alive": True,
        }

        private_key_raw = _local("SNOWFLAKE_PRIVATE_KEY")
        private_key_path = _local("SNOWFLAKE_PRIVATE_KEY_PATH")
        password = _local("SNOWFLAKE_PASSWORD")

        if private_key_raw or private_key_path:
            from cryptography.hazmat.primitives import serialization

            if private_key_raw:
                pem_bytes = private_key_raw.encode("utf-8")
            else:
                with open(os.path.expanduser(private_key_path), "rb") as key_file:
                    pem_bytes = key_file.read()
            private_key = serialization.load_pem_private_key(pem_bytes, password=None)
            connection_params["private_key"] = private_key.private_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        elif password:
            connection_params["password"] = password
        else:
            connection_params["authenticator"] = "externalbrowser"

    try:
        from snowflake.snowpark import Session

        return Session.builder.configs(connection_params).create()
    except Exception:
        return None


@st.cache_data(ttl=300)
def load_available_surveys(_session) -> pd.DataFrame:
    """Return distinct SURVEY_NAME / SURVEY_KEY pairs."""
    return _session.sql(_SURVEYS_QUERY).to_pandas()


def build_survey_options(surveys_df: pd.DataFrame) -> dict[str, str]:
    """Map display label 'Survey Name [KEY]' to SURVEY_KEY."""
    result: dict[str, str] = {}
    for _, row in surveys_df.iterrows():
        name = str(row.get("SURVEY_NAME", "")).strip()
        raw_key = row.get("SURVEY_KEY")
        key = str(raw_key).strip() if raw_key is not None and str(raw_key).strip() not in ("", "None", "nan") else ""
        label = f"{name} [{key}]" if key else f"{name} [no key]"
        result[label] = key
    return result


def run_survey_query(session, survey_key: str) -> pd.DataFrame:
    """Query all rows for a specific SURVEY_KEY."""
    safe_key = survey_key.replace("'", "''")
    return session.sql(_SURVEY_DATA_QUERY.format(key=safe_key)).to_pandas()


def run_custom_query(session, sql: str) -> pd.DataFrame:
    """Execute an arbitrary SQL string and return the result as a dataframe."""
    return session.sql(sql).to_pandas()
