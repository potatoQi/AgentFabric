from __future__ import annotations

import inspect
import json
import math
import base64
from urllib.parse import urlparse
from typing import Any

import pandas as pd
import streamlit as st
from sqlalchemy import and_, delete, text

from agentfabric import DB
from agentfabric.db.query import build_where as _build_where_clauses

from agentfabric.ui._conn import Conn, ensure_connected, env, load_conn_defaults_from_config
from agentfabric.ui._preview import candidate_url_fields, open_preview_cached, pick_default_url_field
from agentfabric.ui._styles import apply_global_css

CONTENT_PANEL_HEIGHT = 520
TABLE_HEIGHT = int(700 * 1.8)

@st.cache_resource(show_spinner=False)
def _get_db(db_url: str, config_path: str) -> DB:
    db = DB(url=db_url, config_path=config_path)
    schema = db.registry.postgres_schema
    if schema:
        with db.engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
    db.init_schema()
    return db


def _infer_ops(col_type: str) -> list[str]:
    if col_type in {"int", "float", "datetime"}:
        return ["eq", "ne", "lt", "lte", "gt", "gte", "in_", "nin", "is_null", "not_null"]
    if col_type == "bool":
        return ["eq", "ne", "is_null", "not_null"]
    if col_type == "list":
        return ["eq", "ne", "is_null", "not_null"]
    # text / uuid / json
    return ["eq", "ne", "like", "in_", "nin", "is_null", "not_null"]


_OP_LABELS: dict[str, str] = {
    "eq": "=",
    "ne": "≠",
    "lt": "<",
    "lte": "≤",
    "gt": ">",
    "gte": "≥",
    "in_": "in",
    "nin": "not in",
    "like": "like",
    "is_null": "is null",
    "not_null": "not null",
}


def _parse_scalar(raw: str, type_name: str) -> Any:
    if type_name == "int":
        return int(raw)
    if type_name == "float":
        return float(raw)
    if type_name == "bool":
        v = raw.strip().lower()
        if v in {"1", "true", "t", "yes", "y"}:
            return True
        if v in {"0", "false", "f", "no", "n"}:
            return False
        raise ValueError("bool expects true/false")
    if type_name == "datetime":
        # SQLAlchemy/psycopg can parse ISO-like strings.
        return raw.strip()
    return raw


def _parse_value(op: str, raw: str, type_name: str, item_type_name: str | None) -> Any:
    if op == "is_null":
        return True
    if op == "not_null":
        return False

    if op in {"in_", "nin"} and type_name != "list":
        # CSV list; parse items based on column type.
        items = [x.strip() for x in raw.split(",") if x.strip()]
        return [_parse_scalar(x, type_name) for x in items]

    if type_name == "list":
        # Simple CSV list; parse items based on item_type_name when available.
        items = [x.strip() for x in raw.split(",") if x.strip()]
        it = item_type_name or "text"
        return [_parse_scalar(x, it) for x in items]

    return _parse_scalar(raw, type_name)


def _delete_where(db: DB, table: str, where: dict[str, Any]) -> int:
    """Compatibility wrapper around `DB.delete_where`.

    Streamlit can keep a running process and reuse old objects; this keeps the UI
    safe even if an older AgentFabric build is on the PYTHONPATH.
    """

    fn = getattr(db, "delete_where", None)
    if callable(fn):
        return int(fn(table, where))

    if not where:
        raise ValueError("delete_where requires non-empty where")

    t = db.tables[table]
    allowed_fields = None
    filterable = getattr(db, "_filterable_cols", None)
    if isinstance(filterable, dict):
        allowed_fields = filterable.get(table)
    if allowed_fields is None:
        allowed_fields = set(t.c.keys())

    clauses = _build_where_clauses(t, where, allowed_fields=allowed_fields)
    if not clauses:
        raise ValueError("delete_where requires non-empty where")

    stmt = delete(t).where(and_(*clauses))
    with db.Session() as s:
        res = s.execute(stmt)
        s.commit()
        return int(res.rowcount or 0)


def _build_where(table_spec: Any, ui_state: dict[str, Any]) -> dict[str, Any]:
    where: dict[str, Any] = {}
    for col_name, col_spec in table_spec.columns.items():
        if not getattr(col_spec, "filterable", False):
            continue

        op = ui_state.get(f"op::{col_name}")
        raw = ui_state.get(f"val::{col_name}")
        if not op:
            continue
        if op == "is_null":
            if ui_state.get(f"enabled::{col_name}"):
                where[col_name] = {"is_null": True}
            continue
        if not ui_state.get(f"enabled::{col_name}"):
            continue
        if raw is None:
            continue
        raw_s = str(raw).strip()
        if raw_s == "":
            continue

        type_name = getattr(col_spec, "type_name", "text")
        item_type_name = getattr(col_spec, "item_type_name", None)
        where[col_name] = {op: _parse_value(op, raw_s, type_name, item_type_name)}

    # Optional extra.* filters (top-level key)
    extra_key = (ui_state.get("extra_key") or "").strip()
    extra_op = ui_state.get("extra_op")
    extra_val = (ui_state.get("extra_val") or "").strip()
    if extra_key and extra_op:
        field = f"extra.{extra_key}"
        if extra_op == "is_null":
            where[field] = {"is_null": True}
        elif extra_val:
            where[field] = {extra_op: extra_val}

    return where


def _filters_state_key(table: str, suffix: str) -> str:
    return f"af_filters::{table}::{suffix}"


def _filters_draft_len_key(table: str, field: str) -> str:
    return _filters_state_key(table, f"draft_len::{field}")


def _filters_get_draft_len(table: str, field: str, *, saved_len: int) -> int:
    k = _filters_draft_len_key(table, field)
    v = st.session_state.get(k)
    try:
        n = int(v)
    except Exception:
        n = int(saved_len)
        st.session_state[k] = n
    return max(0, n)


def _filters_set_draft_len(table: str, field: str, n: int) -> None:
    st.session_state[_filters_draft_len_key(table, field)] = max(0, int(n))


def _filters_discard_draft(table: str, field: str) -> None:
    """Discard unsubmitted drafts for a field (including added rows)."""

    if field == "__extra__":
        saved_len = len(_filters_get_extra_rows(table))
    else:
        saved_len = len(_filters_get_field_rows(table, field))
    _filters_set_draft_len(table, field, saved_len)
    # Bump rev so stale draft widget state isn't reused.
    _filters_bump_rev(table, field)


def _filterable_fields(table_spec: Any) -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    for col_name, col_spec in table_spec.columns.items():
        if bool(getattr(col_spec, "filterable", False)):
            out.append((col_name, col_spec))
    return out


def _type_label_for_col(col_spec: Any) -> str:
    type_name = getattr(col_spec, "type_name", "text")
    item_type_name = getattr(col_spec, "item_type_name", None)
    if type_name == "list":
        return f"list[{item_type_name or 'text'}]"
    return str(type_name)


def _filters_saved_key(table: str) -> str:
    return _filters_state_key(table, "saved")


def _filters_applied_where_key(table: str) -> str:
    return _filters_state_key(table, "applied_where")


def _filters_rev_key(table: str, field: str) -> str:
    return _filters_state_key(table, f"rev::{field}")


def _filters_get_saved(table: str) -> dict[str, Any]:
    saved = st.session_state.get(_filters_saved_key(table))
    if isinstance(saved, dict):
        saved.setdefault("fields", {})
        saved.setdefault("extra", [])
        return saved
    saved = {"fields": {}, "extra": []}
    st.session_state[_filters_saved_key(table)] = saved
    return saved


def _filters_bump_rev(table: str, field: str) -> int:
    k = _filters_rev_key(table, field)
    st.session_state[k] = int(st.session_state.get(k) or 0) + 1
    return int(st.session_state[k])


def _filters_get_rev(table: str, field: str) -> int:
    return int(st.session_state.get(_filters_rev_key(table, field)) or 0)


def _filters_set_selected(table: str, field: str) -> None:
    # Discard unsubmitted draft edits for the previously selected field.
    prev = st.session_state.get(_filters_state_key(table, "selected"))
    if isinstance(prev, str) and prev and prev != field:
        prev_key = "__extra__" if prev == "extra.*" else prev
        _filters_discard_draft(table, prev_key)
    st.session_state[_filters_state_key(table, "selected")] = field


def _filters_get_selected(table: str, default: str | None = None) -> str | None:
    v = st.session_state.get(_filters_state_key(table, "selected"))
    if isinstance(v, str) and v:
        return v
    return default


def _filters_get_field_rows(table: str, field: str) -> list[dict[str, Any]]:
    saved = _filters_get_saved(table)
    fields = saved["fields"]
    rows = fields.get(field)
    if isinstance(rows, list):
        return rows
    fields[field] = []
    return fields[field]


def _filters_set_field_rows(table: str, field: str, rows: list[dict[str, Any]]) -> None:
    saved = _filters_get_saved(table)
    saved["fields"][field] = rows


def _filters_get_extra_rows(table: str) -> list[dict[str, Any]]:
    saved = _filters_get_saved(table)
    rows = saved.get("extra")
    if isinstance(rows, list):
        return rows
    saved["extra"] = []
    return saved["extra"]


def _filters_set_extra_rows(table: str, rows: list[dict[str, Any]]) -> None:
    saved = _filters_get_saved(table)
    saved["extra"] = rows


def _filters_row_is_effective(row: dict[str, Any], *, is_extra: bool) -> bool:
    op = (row.get("op") or "").strip()
    if not op:
        return False
    if op in {"is_null", "not_null"}:
        return True
    if is_extra:
        key = (row.get("key") or "").strip()
        raw = (row.get("raw") or "").strip()
        return bool(key and raw)
    raw = (row.get("raw") or "").strip()
    return bool(raw)


def _filters_has_effective_conditions(table: str, field: str) -> bool:
    if field == "__extra__":
        return any(_filters_row_is_effective(r, is_extra=True) for r in _filters_get_extra_rows(table))
    return any(_filters_row_is_effective(r, is_extra=False) for r in _filters_get_field_rows(table, field))


def _filters_build_where_from_saved(table: str, table_spec: Any) -> dict[str, Any]:
    conds: list[dict[str, Any]] = []

    # Columns
    for col_name, col_spec in _filterable_fields(table_spec):
        type_name = getattr(col_spec, "type_name", "text")
        item_type_name = getattr(col_spec, "item_type_name", None)
        for r in _filters_get_field_rows(table, col_name):
            op = (r.get("op") or "").strip()
            raw = (r.get("raw") or "")
            if not op:
                continue
            if op == "is_null":
                conds.append({col_name: {"is_null": True}})
                continue
            if op == "not_null":
                conds.append({col_name: {"is_null": False}})
                continue
            raw_s = str(raw).strip()
            if raw_s == "":
                continue
            conds.append({col_name: {op: _parse_value(op, raw_s, type_name, item_type_name)}})

    # extra.*
    for r in _filters_get_extra_rows(table):
        key = (r.get("key") or "").strip()
        op = (r.get("op") or "").strip()
        raw = (r.get("raw") or "")
        if not key or not op:
            continue
        field = f"extra.{key}"
        if op == "is_null":
            conds.append({field: {"is_null": True}})
            continue
        if op == "not_null":
            conds.append({field: {"is_null": False}})
            continue
        raw_s = str(raw).strip()
        if raw_s == "":
            continue
        if op in {"in_", "nin"}:
            items = [x.strip() for x in raw_s.split(",") if x.strip()]
            conds.append({field: {op: items}})
        else:
            conds.append({field: {op: raw_s}})

    if not conds:
        return {}
    if len(conds) == 1:
        return conds[0]
    return {"and": conds}


def _filters_rebuild_applied(table: str, table_spec: Any) -> None:
    st.session_state[_filters_applied_where_key(table)] = _filters_build_where_from_saved(table, table_spec)


def _filters_add_row(table: str, field: str, table_spec: Any) -> None:
    # Add a draft row only. Persist + apply happens on Enter.
    if field == "__extra__":
        saved_len = len(_filters_get_extra_rows(table))
        n = _filters_get_draft_len(table, "__extra__", saved_len=saved_len)
        _filters_set_draft_len(table, "__extra__", n + 1)
        return
    saved_len = len(_filters_get_field_rows(table, field))
    n = _filters_get_draft_len(table, field, saved_len=saved_len)
    _filters_set_draft_len(table, field, n + 1)


def _filters_remove_row(table: str, field: str, table_spec: Any) -> None:
    # '-' is immediate:
    # - If there are unsubmitted draft rows, just remove the last draft row.
    # - Otherwise, remove the last saved condition and apply immediately.
    if field == "__extra__":
        saved_rows = _filters_get_extra_rows(table)
        saved_len = len(saved_rows)
        draft_len = _filters_get_draft_len(table, "__extra__", saved_len=saved_len)
        if draft_len > saved_len:
            _filters_set_draft_len(table, "__extra__", draft_len - 1)
            return
        if not saved_rows:
            return
        saved_rows.pop()
        _filters_set_extra_rows(table, saved_rows)
        _filters_set_draft_len(table, "__extra__", len(saved_rows))
        _filters_bump_rev(table, "__extra__")
        _filters_rebuild_applied(table, table_spec)
        return

    saved_rows = _filters_get_field_rows(table, field)
    saved_len = len(saved_rows)
    draft_len = _filters_get_draft_len(table, field, saved_len=saved_len)
    if draft_len > saved_len:
        _filters_set_draft_len(table, field, draft_len - 1)
        return
    if not saved_rows:
        return
    saved_rows.pop()
    _filters_set_field_rows(table, field, saved_rows)
    _filters_set_draft_len(table, field, len(saved_rows))
    _filters_bump_rev(table, field)
    _filters_rebuild_applied(table, table_spec)


def _filters_clear_field(table: str, field: str, table_spec: Any) -> None:
    if field == "__extra__":
        _filters_set_extra_rows(table, [])
        _filters_set_draft_len(table, "__extra__", 0)
        _filters_bump_rev(table, "__extra__")
        _filters_rebuild_applied(table, table_spec)
        return
    _filters_set_field_rows(table, field, [])
    _filters_set_draft_len(table, field, 0)
    _filters_bump_rev(table, field)
    _filters_rebuild_applied(table, table_spec)


def _filters_clear_all(table: str, table_spec: Any) -> None:
    st.session_state.pop(_filters_saved_key(table), None)
    st.session_state.pop(_filters_applied_where_key(table), None)
    # Bump a generic rev so widgets refresh.
    _filters_bump_rev(table, "__extra__")
    _filters_rebuild_applied(table, table_spec)


def _filters_submit_selected(table: str, table_spec: Any, field: str) -> None:
    """Persist currently visible draft widgets into saved store and apply.

    This is intended to be triggered by pressing Enter inside the form.
    """

    if field == "extra.*":
        field = "__extra__"

    rev = _filters_get_rev(table, field)
    if field == "__extra__":
        saved_rows = _filters_get_extra_rows(table)
        draft_len = _filters_get_draft_len(table, "__extra__", saved_len=len(saved_rows))
        committed: list[dict[str, Any]] = []
        for i in range(draft_len):
            k_key = _filters_state_key(table, f"draft_extra_key::{i}::{rev}")
            op_key = _filters_state_key(table, f"draft_extra_op::{i}::{rev}")
            v_key = _filters_state_key(table, f"draft_extra_val::{i}::{rev}")
            row = {
                "key": str(st.session_state.get(k_key) or ""),
                "op": str(st.session_state.get(op_key) or ""),
                "raw": str(st.session_state.get(v_key) or ""),
            }
            if _filters_row_is_effective(row, is_extra=True):
                committed.append(row)
        _filters_set_extra_rows(table, committed)
        _filters_set_draft_len(table, "__extra__", len(committed))
        _filters_bump_rev(table, "__extra__")
        _filters_rebuild_applied(table, table_spec)
        return

    saved_rows = _filters_get_field_rows(table, field)
    draft_len = _filters_get_draft_len(table, field, saved_len=len(saved_rows))
    committed = []
    for i in range(draft_len):
        op_key = _filters_state_key(table, f"draft_op::{field}::{i}::{rev}")
        v_key = _filters_state_key(table, f"draft_val::{field}::{i}::{rev}")
        row = {
            "op": str(st.session_state.get(op_key) or ""),
            "raw": str(st.session_state.get(v_key) or ""),
        }
        if _filters_row_is_effective(row, is_extra=False):
            committed.append(row)
    _filters_set_field_rows(table, field, committed)
    _filters_set_draft_len(table, field, len(committed))
    _filters_bump_rev(table, field)
    _filters_rebuild_applied(table, table_spec)




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


def _referencing_foreign_keys(db: DB, ref_table: str) -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    for tname, tdef in db.registry.tables.items():
        for fk in getattr(tdef, "foreign_keys", []) or []:
            if getattr(fk, "ref_table", None) == ref_table:
                out.append((tname, fk))
    return out


def _is_fk_violation(exc: Exception) -> bool:
    # psycopg3 raises psycopg.errors.ForeignKeyViolation; SQLAlchemy wraps it.
    try:
        import psycopg  # type: ignore

        from psycopg.errors import ForeignKeyViolation  # type: ignore

        if isinstance(getattr(exc, "orig", None), ForeignKeyViolation):
            return True
    except Exception:
        pass
    msg = str(exc).lower()
    return "foreignkeyviolation" in msg or "violates foreign key constraint" in msg
def _stretch_kwargs(fn: Any) -> dict[str, Any]:
    """Return kwargs that make widgets stretch to container width.

    Streamlit migrated from use_container_width=True to width='stretch'.
    This helper keeps compatibility across versions.
    """

    try:
        params = inspect.signature(fn).parameters
    except Exception:
        return {}
    if "width" in params:
        return {"width": "stretch"}
    if "use_container_width" in params:
        return {"use_container_width": True}
    return {}


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
                value=20,
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

    conn = Conn(db_url=cfg_db, config_path=config_path, artifact_base_url=cfg_art)
    db = _get_db(conn.db_url, conn.config_path)

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
            value=int(st.session_state.get("af_limit", 20)),
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
            filterable = _filterable_fields(table_spec)
            if not filterable:
                st.caption("No filterable fields in this table.")
            else:
                spec_by_name = {n: s for n, s in filterable}
                left, right = st.columns([1.15, 2.0], gap="medium")

                with left:
                    options = [n for n, _ in filterable] + ["extra.*"]
                    default_selected = options[0] if options else "extra.*"
                    selected = _filters_get_selected(table, default_selected) or default_selected
                    if selected not in options:
                        selected = default_selected
                        _filters_set_selected(table, selected)

                    with st.container(height=420, border=False):
                        for name in options:
                            is_extra = name == "extra.*"
                            field_key = "__extra__" if is_extra else name
                            active = _filters_has_effective_conditions(table, field_key)

                            if is_extra:
                                label = "extra.*"
                            else:
                                label = name
                            if name == selected:
                                label = f"▶ {label}"

                            st.button(
                                label,
                                key=_filters_state_key(table, f"pick::{name}"),
                                type=("primary" if active else "secondary"),
                                on_click=_filters_set_selected,
                                args=(table, name),
                                use_container_width=True,
                            )

                with right:
                    if selected == "extra.*":
                        st.markdown("**extra.* (top-level key)**")
                        field_key = "__extra__"
                        saved_rows = _filters_get_extra_rows(table)
                        rev = _filters_get_rev(table, field_key)
                        draft_len = _filters_get_draft_len(table, field_key, saved_len=len(saved_rows))

                        hdr = st.columns([0.18, 0.18, 1.0])
                        hdr[0].button(
                            "",
                            key=_filters_state_key(table, "extra_add"),
                            icon=":material/add:",
                            help="add condition",
                            on_click=_filters_add_row,
                            args=(table, field_key, table_spec),
                        )
                        hdr[1].button(
                            "",
                            key=_filters_state_key(table, "extra_rm"),
                            icon=":material/remove:",
                            help="remove last condition",
                            on_click=_filters_remove_row,
                            args=(table, field_key, table_spec),
                        )

                        st.caption("Press Enter to apply conditions for this field")
                        with st.form(key=_filters_state_key(table, f"form::{field_key}::{rev}"), clear_on_submit=False):
                            if draft_len == 0:
                                st.caption("No conditions. Click + to add one.")
                            for i in range(draft_len):
                                r = saved_rows[i] if i < len(saved_rows) else {"key": "", "op": "", "raw": ""}
                                row = st.columns([1.4, 1.0, 2.0])
                                row[0].text_input(
                                    "extra key",
                                    key=_filters_state_key(table, f"draft_extra_key::{i}::{rev}"),
                                    value=str(r.get("key") or ""),
                                    placeholder="tag",
                                    label_visibility="collapsed",
                                )

                                extra_ops = ["", "eq", "ne", "like", "in_", "nin", "is_null", "not_null"]
                                cur_op = str(r.get("op") or "")
                                idx = extra_ops.index(cur_op) if cur_op in extra_ops else 0
                                extra_op = row[1].selectbox(
                                    "op",
                                    options=extra_ops,
                                    index=idx,
                                    key=_filters_state_key(table, f"draft_extra_op::{i}::{rev}"),
                                    label_visibility="collapsed",
                                    format_func=lambda v: _OP_LABELS.get(v, v),
                                )

                                if extra_op in {"is_null", "not_null"}:
                                    row[2].caption("NULL check ignores value")
                                else:
                                    row[2].text_input(
                                        "value",
                                        key=_filters_state_key(table, f"draft_extra_val::{i}::{rev}"),
                                        value=str(r.get("raw") or ""),
                                        placeholder=("a,b,c" if extra_op in {"in_", "nin"} else "value"),
                                        label_visibility="collapsed",
                                    )

                            submitted = st.form_submit_button(
                                " ",
                                help="__AF_APPLY__",
                                key=_filters_state_key(table, f"submit::{field_key}::{rev}"),
                                type="tertiary",
                            )
                            if submitted:
                                _filters_submit_selected(table, table_spec, selected)
                    else:
                        col_spec = spec_by_name[selected]
                        type_name = getattr(col_spec, "type_name", "text")
                        type_label = _type_label_for_col(col_spec)
                        st.markdown(f"**{selected}** ({type_label})")

                        saved_rows = _filters_get_field_rows(table, selected)
                        rev = _filters_get_rev(table, selected)
                        draft_len = _filters_get_draft_len(table, selected, saved_len=len(saved_rows))

                        hdr = st.columns([0.18, 0.18, 1.0])
                        hdr[0].button(
                            "",
                            key=_filters_state_key(table, f"add::{selected}"),
                            icon=":material/add:",
                            help="add condition",
                            on_click=_filters_add_row,
                            args=(table, selected, table_spec),
                        )
                        hdr[1].button(
                            "",
                            key=_filters_state_key(table, f"rm::{selected}"),
                            icon=":material/remove:",
                            help="remove last condition",
                            on_click=_filters_remove_row,
                            args=(table, selected, table_spec),
                        )

                        st.caption("Press Enter to apply conditions for this field")
                        ops = [""] + _infer_ops(type_name)
                        with st.form(key=_filters_state_key(table, f"form::{selected}::{rev}"), clear_on_submit=False):
                            if draft_len == 0:
                                st.caption("No conditions. Click + to add one.")

                            for i in range(draft_len):
                                r = saved_rows[i] if i < len(saved_rows) else {"op": "", "raw": ""}
                                row = st.columns([1.0, 2.2])
                                cur_op = str(r.get("op") or "")
                                idx = ops.index(cur_op) if cur_op in ops else 0
                                op = row[0].selectbox(
                                    "op",
                                    options=ops,
                                    index=idx,
                                    key=_filters_state_key(table, f"draft_op::{selected}::{i}::{rev}"),
                                    label_visibility="collapsed",
                                    format_func=lambda v: _OP_LABELS.get(v, v),
                                )

                                if op in {"is_null", "not_null"}:
                                    row[1].caption("NULL check ignores value")
                                else:
                                    placeholder = "value"
                                    if op in {"in_", "nin"}:
                                        placeholder = "a,b,c"
                                    elif op == "like":
                                        placeholder = "e.g. abc%"
                                    elif type_name == "datetime":
                                        placeholder = "YYYY-MM-DD"
                                    elif type_name == "list":
                                        placeholder = "a,b,c"
                                    elif type_name == "bool":
                                        placeholder = "true/false"

                                    row[1].text_input(
                                        "value",
                                        key=_filters_state_key(table, f"draft_val::{selected}::{i}::{rev}"),
                                        value=str(r.get("raw") or ""),
                                        placeholder=placeholder,
                                        label_visibility="collapsed",
                                    )

                            submitted = st.form_submit_button(
                                " ",
                                help="__AF_APPLY__",
                                key=_filters_state_key(table, f"submit::{selected}::{rev}"),
                                type="tertiary",
                            )
                            if submitted:
                                _filters_submit_selected(table, table_spec, selected)

                st.divider()
                # No explicit clear-all in the UI; users can remove conditions per-field.

    if _filters_applied_where_key(table) not in st.session_state:
        _filters_rebuild_applied(table, table_spec)
    where = st.session_state.get(_filters_applied_where_key(table)) or {}
    filter_obj = {"where": where, "limit": int(limit), "offset": 0}

    try:
        rows = db.query(table, filter_obj, as_dict=True)
    except Exception as e:
        st.error(f"Query failed: {e}")
        return

    preview_collapsed_key = "af_preview_collapsed"
    preview_collapsed = bool(st.session_state.get(preview_collapsed_key, False))

    # In collapsed mode we want the table to take essentially all width.
    # Reduce column gap and make the preview column extremely thin.
    cols_gap = "small" if preview_collapsed else "large"
    left, right = st.columns(([5000, 1] if preview_collapsed else [3, 2]), gap=cols_gap)

    with left:
        if not rows:
            st.info("No rows.")
            return

        df = pd.DataFrame(rows)
        df.insert(0, "__selected", False)

        edited = st.data_editor(
            df,
            **_stretch_kwargs(st.data_editor),
            hide_index=True,
            height=TABLE_HEIGHT,
            key=f"editor::{table}",
            disabled=[c for c in df.columns if c != "__selected"],
            column_config={
                "__selected": st.column_config.CheckboxColumn("select", pinned=True),
            },
        )

        selected = edited[edited["__selected"] == True]  # noqa: E712
        selected_rows = selected.drop(columns=["__selected"]).to_dict(orient="records")

        if pk_cols and selected_rows:
            refs = _referencing_foreign_keys(db, table)
            with st.form(key=f"delete_form::{table}", clear_on_submit=True):
                cascade = False
                if refs:
                    cascade = st.checkbox(
                        "cascade delete referencing rows",
                        value=False,
                        key=f"cascade::{table}",
                        help=(
                            "If the row is referenced by other tables, delete those dependent rows first. "
                            "This is a UI convenience; your schema on_delete may still be restrict."
                        ),
                    )

                confirm = st.checkbox(
                    "I understand this will DELETE selected rows",
                    value=False,
                    key=f"confirm_delete::{table}",
                )

                submitted = st.form_submit_button(
                    "delete selected",
                    type="secondary",
                )

            if submitted:
                if not confirm:
                    # Safety: do nothing without explicit confirmation.
                    st.warning("Please tick the confirmation checkbox before deleting.")
                else:
                    try:
                        if cascade and refs:
                            for row in selected_rows:
                                for child_table, fk in refs:
                                    where: dict[str, Any] = {}
                                    for child_col, ref_col in zip(fk.columns, fk.ref_columns):
                                        where[child_col] = {"eq": row.get(ref_col)}
                                    # Best-effort: skip if any key missing
                                    if any(v.get("eq") is None for v in where.values()):
                                        continue
                                    _delete_where(db, child_table, where)

                        n = db.delete_by_pk(table, selected_rows)
                        st.success(f"Deleted {n} rows")

                        # Clear selection so a new selection doesn't inherit old checkmarks.
                        st.session_state.pop(f"editor::{table}", None)
                        st.rerun()
                    except Exception as e:
                        if _is_fk_violation(e) and refs and not cascade:
                            tables = ", ".join(sorted({t for t, _ in refs}))
                            st.error(
                                "Delete failed due to foreign key references. "
                                f"This table is referenced by: {tables}. "
                                "Either delete dependent rows first, or enable 'cascade delete referencing rows'."
                            )
                        else:
                            st.error(f"Delete failed: {e}")

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
