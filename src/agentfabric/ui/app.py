from __future__ import annotations

import json
import math
import base64
from urllib.parse import urlparse
from typing import Any

import pandas as pd
import streamlit as st
from sqlalchemy import text

from agentfabric import AgentFabric
from agentfabric.fabric import DBManager

from agentfabric.ui._conn import Conn, ensure_connected, env, load_conn_defaults_from_config
from agentfabric.ui._delete_panel import render_delete_panel
from agentfabric.ui._filters import get_applied_where, others_no_child_rows_enabled, render_filters_popover_content
from agentfabric.ui._preview import candidate_url_fields, open_preview_cached, pick_default_url_field
from agentfabric.ui._ui_query import query_rows
from agentfabric.ui._styles import apply_global_css

CONTENT_PANEL_HEIGHT = 520
TABLE_HEIGHT = int(700 * 1.8)

@st.cache_resource(show_spinner=False)
def _get_db(config_path: str) -> DBManager:
    db, _store = AgentFabric(config_path)
    schema = db.registry.postgres_schema
    if schema:
        with db.engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
    db.init_schema()
    return db


def _row_matches_pk(row: dict[str, Any], pk_cols: list[str], key_row: dict[str, Any]) -> bool:
    for c in pk_cols:
        if row.get(c) != key_row.get(c):
            return False
    return True


def _pick_preview_row(rows: list[dict[str, Any]], pk_cols: list[str], selected_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if selected_rows and pk_cols:
        key_row = selected_rows[0]
        for r in rows:
            if _row_matches_pk(r, pk_cols, key_row):
                return r
        return key_row
    if rows:
        return rows[0]
    return None


def _normalize_for_preview(value: Any) -> Any:
    # Convert pandas/numpy missing markers to None, recursively.
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    if isinstance(value, dict):
        return {k: _normalize_for_preview(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize_for_preview(v) for v in value]
    if isinstance(value, tuple):
        return [_normalize_for_preview(v) for v in value]

    # NaN can sneak in from DataFrame-to-dict conversions.
    if isinstance(value, float) and math.isnan(value):
        return None

    # Best-effort for common objects.
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        try:
            return iso()
        except Exception:
            pass

    return value


def _guess_ext_from_url(url: str) -> str:
    try:
        p = urlparse(url)
        path = p.path or ""
    except Exception:
        path = url
    # strip query fragments just in case
    path = path.split("?")[0].split("#")[0]
    if "." not in path:
        return ""
    return path.rsplit(".", 1)[-1].lower()


def _render_preview_content(url: str, text: str, *, height: int = CONTENT_PANEL_HEIGHT) -> None:
    """Render artifact content in a fixed-height scrollable panel."""

    # Keep the panel height stable across URL-field switches.
    with st.container(height=height, border=True):
        # Avoid trying to syntax-highlight very large content.
        if len(text) > 200_000:
            st.caption("content is large; showing raw text")
            st.text_area(
                "content",
                value=text,
                height=max(120, height - 60),
                label_visibility="collapsed",
            )
            return

        ext = _guess_ext_from_url(url)

        if ext in {"md", "markdown"}:
            st.markdown(text)
            return

        if ext == "json":
            try:
                obj = json.loads(text)
                obj = _normalize_for_preview(obj)
                pretty = json.dumps(obj, ensure_ascii=False, indent=2, default=str, allow_nan=False)
            except Exception:
                pretty = text
            st.code(pretty, language="json")
            return

        # Common "diff-like" extensions.
        if ext in {"diff", "patch"}:
            st.code(text, language="diff")
            return

        # A few useful extras; still fall back to raw text for .txt.
        if ext in {"yaml", "yml"}:
            st.code(text, language="yaml")
            return
        if ext in {"toml"}:
            st.code(text, language="toml")
            return

        st.text_area(
            "content",
            value=text,
            height=max(120, height - 20),
            label_visibility="collapsed",
        )


def _get_query_params() -> dict[str, list[str]]:
    try:
        qp = st.query_params  # type: ignore[attr-defined]
        # Streamlit returns a dict-like with string/list values depending on version.
        out: dict[str, list[str]] = {}
        for k, v in dict(qp).items():
            if isinstance(v, list):
                out[k] = [str(x) for x in v]
            else:
                out[k] = [str(v)]
        return out
    except Exception:
        return {k: [str(x) for x in v] for k, v in st.experimental_get_query_params().items()}


def _b64e(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode("utf-8")).decode("ascii").rstrip("=")


def _b64d(s: str) -> str:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("ascii")).decode("utf-8")


def _full_view_href(url: str, artifact_base_url: str | None) -> str:
    # Relative link works both locally and behind proxies.
    u = _b64e(url)
    a = _b64e(artifact_base_url or "")
    return f"?af_full=1&u={u}&a={a}"


def _maybe_render_full_view() -> bool:
    qp = _get_query_params()
    if not qp.get("af_full"):
        return False

    u_enc = (qp.get("u") or [""])[0]
    a_enc = (qp.get("a") or [""])[0]
    if not u_enc:
        st.error("Missing url")
        return True

    try:
        url = _b64d(u_enc)
        artifact_base_url = _b64d(a_enc) if a_enc else None
        artifact_base_url = artifact_base_url or None
    except Exception:
        st.error("Invalid parameters")
        return True

    st.set_page_config(page_title="AgentFabric - Content", layout="wide")
    st.markdown("**content (full)**")
    st.caption(url)

    try:
        data = open_preview_cached(url, artifact_base_url)
        text = data.decode("utf-8", errors="replace")
        # In full view, keep the same type-based rendering but give raw text more space.
        if _guess_ext_from_url(url) in {"", "txt"} or len(text) > 200_000:
            st.text_area("content", value=text, height=900, label_visibility="collapsed")
        else:
            _render_preview_content(url, text, height=900)
    except Exception as e:
        st.error(f"Open failed: {e}")

    return True


def main() -> None:
    # If opened with ?af_full=1, render a dedicated full-content view.
    if _maybe_render_full_view():
        return

    st.set_page_config(page_title="AgentFabric", layout="wide")

    try:
        toolbar_mode = st.get_option("client.toolbarMode")
    except Exception:
        toolbar_mode = None

    apply_global_css(None if toolbar_mode is None else str(toolbar_mode))

    # Top controls bar.
    # db_url / artifact_base_url are sourced from config; no need to show as separate inputs.
    env_cfg_path = env("AGENTFABRIC_UI_CONFIG_PATH") or ""
    # Keep the top bar on a single row.
    # Add a spacer column so config/table can stay narrow without stretching.
    # Give connect/refresh enough width so their labels don't wrap.
    # Give the Filters trigger enough width so its label never wraps vertically.
    # Give filters a bit more room so the label never wraps; reduce the spacer.
    top = st.columns([1.6, 1.3, 0.6, 1.1, 2.75, 0.9, 0.9], gap="small")

    with top[0]:
        config_path = st.text_input(
            "config path",
            value=(st.session_state.get("conn_config_path") or env_cfg_path),
            placeholder="/path/to/schema.yaml",
            key="conn_config_path",
            # Force the input itself to be narrower.
            width=320,
        )

    config_path = (config_path or "").strip()

    cfg_db: str | None = None
    cfg_art: str | None = None
    cfg_err: str | None = None
    if config_path:
        cfg_db, cfg_art, cfg_err = load_conn_defaults_from_config(config_path)

    with top[4]:
        # Spacer
        st.markdown("", unsafe_allow_html=True)

    with top[5]:
        st.markdown('<div style="height: 1.65rem"></div>', unsafe_allow_html=True)
        connect = st.button("connect", type="primary", width="stretch")

    with top[6]:
        st.markdown('<div style="height: 1.65rem"></div>', unsafe_allow_html=True)
        refresh = st.button("refresh", width="stretch")

    if cfg_err and config_path:
        st.caption(f"⚠️ yaml parse failed: {cfg_err}")

    is_connected = ensure_connected(
        config_path=config_path,
        cfg_db=cfg_db,
        cfg_err=cfg_err,
        env_cfg_path=env_cfg_path,
        connect_clicked=bool(connect),
    )

    if not is_connected or not config_path or not cfg_db:
        with top[1]:
            st.selectbox(
                "table",
                options=[""],
                disabled=True,
                key="af_table",
                width=300,
            )
        with top[2]:
            st.number_input(
                "limit",
                min_value=0,
                max_value=10000,
                value=100,
                step=10,
                key="af_limit",
                disabled=True,
                width=120,
            )
        with top[3]:
            # Align filters with other labeled inputs in the top bar.
            st.markdown('<div style="height: 1.65rem"></div>', unsafe_allow_html=True)
            st.popover(
                "filters",
                type="secondary",
                icon=":material/filter_list:",
                disabled=True,
                width="stretch",
            )

        if not is_connected:
            st.info("Provide a config path (YAML must include db_url), then click connect.")
            return
        if not config_path:
            st.error("config path required")
            return
        if not cfg_db:
            st.error("db_url is required in yaml")
            return

    if refresh:
        # Refresh should be able to pick up schema/table changes.
        st.cache_resource.clear()
        st.cache_data.clear()

    conn = Conn(config_path=config_path, artifact_base_url=cfg_art)
    db = _get_db(conn.config_path)
    st.session_state["af_db"] = db

    table_names = sorted(db.registry.tables.keys())
    if not table_names:
        st.warning("No tables found in config.")
        return

    with top[1]:
        table = st.selectbox(
            "table",
            options=table_names,
            key="af_table",
            width=300,
        )
    with top[2]:
        limit = st.number_input(
            "limit",
            min_value=0,
            max_value=10000,
            value=int(st.session_state.get("af_limit", 100)),
            step=10,
            key="af_limit",
            width=120,
        )

    table_spec = db.registry.tables[table]
    pk_cols = list(table_spec.primary_key)
    if not pk_cols:
        st.error("This table has no primary_key; delete UI is disabled.")

    with top[3]:
        # Align filters with other labeled inputs in the top bar.
        st.markdown('<div style="height: 1.65rem"></div>', unsafe_allow_html=True)
        with st.popover(
            "filters",
            type="secondary",
            icon=":material/filter_list:",
            width="stretch",
        ):
            render_filters_popover_content(db, table, table_spec)

    where = get_applied_where(table, table_spec)

    try:
        rows = query_rows(
            db,
            table,
            where=where,
            limit=int(limit),
            offset=0,
            no_child_rows=others_no_child_rows_enabled(table),
        )
    except Exception as e:
        st.error(f"Query failed: {e}")
        return

    preview_collapsed_key = "af_preview_collapsed"
    preview_collapsed = bool(st.session_state.get(preview_collapsed_key, False))

    if preview_collapsed:
        left, right = st.columns([0.97, 0.03], gap="small")
    else:
        left, right = st.columns([0.62, 0.38], gap="small")

    with left:
        if not rows:
            st.info("No rows.")
            selected_rows: list[dict[str, Any]] = []
        else:
            df = pd.DataFrame(rows)

            # Use a stable index when possible so selection does not drift on reorders.
            if pk_cols and all(c in df.columns for c in pk_cols):
                try:
                    df["__af_pk"] = df[pk_cols].astype(str).agg("\x1f".join, axis=1)
                    df = df.set_index("__af_pk", drop=True)
                except Exception:
                    pass

            if "__selected" not in df.columns:
                df.insert(0, "__selected", False)
            else:
                df["__selected"] = df["__selected"].fillna(False).astype(bool)

            edited = st.data_editor(
                df,
                key=f"af_rows_{table}",
                height=TABLE_HEIGHT,
                hide_index=True,
                column_config={
                    "__selected": st.column_config.CheckboxColumn("select", pinned=True),
                },
            )

            selected = edited[edited["__selected"] == True]  # noqa: E712
            selected_df = selected.drop(columns=["__selected"], errors="ignore").reset_index(drop=True)
            selected_rows = selected_df.to_dict(orient="records")

            render_delete_panel(db, table, pk_cols, selected_rows)

    with right:
        if preview_collapsed:
            # Collapsed mode: show a thin right-side tab.
            if st.button(
                "",
                key="af_preview_expand",
                type="tertiary",
                icon=":material/chevron_left:",
                help="expand preview",
            ):
                st.session_state[preview_collapsed_key] = False
                st.rerun()
        else:
            header_l, header_r = st.columns([0.9, 0.1])
            with header_l:
                st.markdown("**preview**")
            with header_r:
                if st.button(
                    "",
                    key="af_preview_collapse",
                    type="tertiary",
                    icon=":material/chevron_right:",
                    help="collapse preview",
                ):
                    st.session_state[preview_collapsed_key] = True
                    st.rerun()

            row = _pick_preview_row(rows, pk_cols, selected_rows)
            if not row:
                st.info("No row selected.")
            else:
                normalized_row = _normalize_for_preview(row)
                try:
                    row_text = json.dumps(normalized_row, ensure_ascii=False, indent=2, default=str, allow_nan=False)
                except Exception:
                    # Fallback if something is still non-serializable.
                    row_text = str(normalized_row)
                st.code(row_text, language="json")

                url_fields = candidate_url_fields(normalized_row)
                if not url_fields:
                    st.info("No URL-like fields in this row.")
                else:
                    default_field = pick_default_url_field(url_fields)
                    url_field = st.selectbox("url field", options=url_fields, index=url_fields.index(default_field))
                    url = normalized_row.get(url_field)
                    if not isinstance(url, str) or not url.strip():
                        st.info("Empty URL")
                    else:
                        try:
                            data = open_preview_cached(url, conn.artifact_base_url)
                            text = data.decode("utf-8", errors="replace")
                            h_left, h_right = st.columns([0.92, 0.08])
                            with h_left:
                                st.markdown("**content**")
                            with h_right:
                                href = _full_view_href(url, conn.artifact_base_url)
                                st.markdown(
                                    f"<div style='text-align:right; padding-top: 0.25rem'>"
                                    f"<a href='{href}' target='_blank' title='open full content' "
                                    f"style='text-decoration:none; font-size: 1.1rem;'>⤢</a>"
                                    f"</div>",
                                    unsafe_allow_html=True,
                                )
                            _render_preview_content(url, text, height=CONTENT_PANEL_HEIGHT)
                        except Exception as e:
                            st.error(f"Open failed: {e}")


if __name__ == "__main__":
    main()
