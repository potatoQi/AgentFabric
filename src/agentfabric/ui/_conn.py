from __future__ import annotations

import os
from dataclasses import dataclass

import streamlit as st


@st.cache_data(show_spinner=False)
def load_conn_defaults_from_config(config_path: str) -> tuple[str | None, str | None, str | None]:
    """Return (db_url, artifact_base_url, error_message) from YAML config."""

    try:
        from agentfabric.config.loader import load_config

        cfg = load_config(config_path)
        return (cfg.db_url, cfg.artifact_base_url, None)
    except Exception as e:
        return (None, None, str(e))


@dataclass(frozen=True)
class Conn:
    config_path: str
    artifact_base_url: str | None


def env(name: str) -> str | None:
    v = os.getenv(name)
    return v if v and v.strip() else None


def ensure_connected(
    *,
    config_path: str,
    cfg_db: str | None,
    cfg_err: str | None,
    env_cfg_path: str,
    connect_clicked: bool,
) -> bool:
    """Maintain connect state.

    - If launched via CLI with --config, auto-connect once.
    - Changing config_path requires connect again.
    """

    env_has_cfg = bool(env_cfg_path.strip())
    active_cfg = st.session_state.get("af_active_config_path")
    is_connected = bool(st.session_state.get("af_connected", False))

    if active_cfg != config_path:
        st.session_state["af_connected"] = False
        is_connected = False

    if (
        not is_connected
        and env_has_cfg
        and config_path
        and config_path == env_cfg_path
        and cfg_db
        and not cfg_err
    ):
        st.session_state["af_active_config_path"] = config_path
        st.session_state["af_connected"] = True
        is_connected = True

    if connect_clicked:
        st.session_state["af_active_config_path"] = config_path
        st.session_state["af_connected"] = True
        is_connected = True
        st.cache_resource.clear()
        st.cache_data.clear()

    return bool(is_connected)
