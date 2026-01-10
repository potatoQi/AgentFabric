from __future__ import annotations

from datetime import datetime
import re
from typing import Any
from uuid import UUID

import streamlit as st

from agentfabric.fabric import DBManager


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


def infer_ops(col_type: str) -> list[str]:
    if col_type in {"int", "float", "datetime"}:
        return ["eq", "ne", "lt", "lte", "gt", "gte", "in_", "nin", "is_null", "not_null"]
    if col_type == "bool":
        return ["eq", "ne", "is_null", "not_null"]
    if col_type == "list":
        return ["eq", "ne", "is_null", "not_null"]
    if col_type == "uuid":
        # UUID columns: avoid text ops like `like` (may error / be confusing).
        return ["eq", "ne", "in_", "nin", "is_null", "not_null"]
    # text
    return ["eq", "ne", "like", "in_", "nin", "is_null", "not_null"]


def parse_scalar(raw: str, type_name: str) -> Any:
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
        s = raw.strip()

        # Normalize UI-friendly format: YYYY-MM-DD/HH-MM-SS -> YYYY-MM-DD HH:MM:SS
        if "/" in s:
            date_part, time_part = s.split("/", 1)
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_part) and re.fullmatch(
                r"\d{2}-\d{2}-\d{2}", time_part
            ):
                s = f"{date_part} {time_part.replace('-', ':')}"

        # Accept date-only input by interpreting it as midnight UTC-local time.
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return datetime.fromisoformat(f"{s} 00:00:00")

        # Accept ISO 8601 (with optional offset). Handle trailing 'Z'.
        s2 = s
        if s2.endswith("Z"):
            s2 = f"{s2[:-1]}+00:00"

        try:
            return datetime.fromisoformat(s2)
        except ValueError:
            raise ValueError("datetime expects YYYY-MM-DD or YYYY-MM-DD/HH-MM-SS or ISO 8601")
    if type_name == "uuid":
        try:
            return UUID(raw.strip())
        except Exception:
            raise ValueError("uuid expects 8-4-4-4-12 hex (e.g. 550e8400-e29b-41d4-a716-446655440000)")
    return raw


def value_placeholder(op: str, type_name: str, item_type_name: str | None) -> str:
    # NULL checks ignore value.
    if op in {"is_null", "not_null"}:
        return ""

    def _scalar_example(t: str) -> str:
        if t == "int":
            return "123"
        if t == "float":
            return "3.14"
        if t == "bool":
            return "true"
        if t == "uuid":
            return "550e8400-e29b-41d4-a716-446655440000"
        if t == "datetime":
            return "2025-01-10/12-30-00"
        # text default
        return "abc"

    def _scalar_hint(t: str) -> str:
        if t == "datetime":
            return "YYYY-MM-DD or YYYY-MM-DD/HH-MM-SS"
        if t == "bool":
            return "true/false"
        if t == "uuid":
            return "550e8400-e29b-41d4-a716-446655440000"
        if t == "int":
            return "e.g. 123"
        if t == "float":
            return "e.g. 3.14"
        return "e.g. abc"

    def _csv_hint(t: str) -> str:
        if t == "datetime":
            return "YYYY-MM-DD,YYYY-MM-DD or YYYY-MM-DD/HH-MM-SS,..."
        if t == "uuid":
            return "uuid1,uuid2"
        if t == "int":
            return "e.g. 1,2,3"
        if t == "float":
            return "e.g. 0.1,0.2"
        if t == "bool":
            return "e.g. true,false"
        # text default
        return "a,b,c"

    # list columns always accept CSV input (per parse_value implementation).
    if type_name == "list":
        it = item_type_name or "text"
        return _csv_hint(it)

    # op-specific hints
    if op in {"in_", "nin"}:
        return _csv_hint(type_name)
    if op == "like":
        return "e.g. abc%"

    # scalar hints
    if type_name in {"int", "float", "bool", "uuid", "datetime", "text", "str"}:
        return _scalar_hint(type_name)

    # fallback
    return f"e.g. {_scalar_example(type_name)}"


def _selectbox_compat(dg: Any, /, **kwargs: Any):
    """Call Streamlit selectbox with best-effort width support.

    Some Streamlit versions do not support `use_container_width` on selectbox.
    """

    try:
        return dg.selectbox(**kwargs, use_container_width=True)
    except TypeError:
        return dg.selectbox(**kwargs)


def _submit_if_null_op(table: str, table_spec: Any, selected: str, op_state_key: str) -> None:
    op = str(st.session_state.get(op_state_key) or "").strip()
    if op in {"is_null", "not_null"}:
        _submit_selected(table, table_spec, selected)


def parse_value(op: str, raw: str, type_name: str, item_type_name: str | None) -> Any:
    if op == "is_null":
        return True
    if op == "not_null":
        return False

    if op in {"in_", "nin"} and type_name != "list":
        # CSV list; parse items based on column type.
        items = [x.strip() for x in raw.split(",") if x.strip()]
        return [parse_scalar(x, type_name) for x in items]

    if type_name == "list":
        # Simple CSV list; parse items based on item_type_name when available.
        items = [x.strip() for x in raw.split(",") if x.strip()]
        it = item_type_name or "text"
        return [parse_scalar(x, it) for x in items]

    return parse_scalar(raw, type_name)


# -----------------
# Saved filter state
# -----------------

def _state_key(table: str, suffix: str) -> str:
    return f"af_filters::{table}::{suffix}"


def _draft_len_key(table: str, field: str) -> str:
    return _state_key(table, f"draft_len::{field}")


def _get_draft_len(table: str, field: str, *, saved_len: int) -> int:
    k = _draft_len_key(table, field)
    v = st.session_state.get(k)
    try:
        n = int(v)
    except Exception:
        n = int(saved_len)
        st.session_state[k] = n
    return max(0, n)


def _set_draft_len(table: str, field: str, n: int) -> None:
    st.session_state[_draft_len_key(table, field)] = max(0, int(n))


def _saved_key(table: str) -> str:
    return _state_key(table, "saved")


def _applied_where_key(table: str) -> str:
    return _state_key(table, "applied_where")


def _submit_error_key(table: str, field: str) -> str:
    return _state_key(table, f"submit_error::{field}")


def _set_submit_error(table: str, field: str, msg: str) -> None:
    st.session_state[_submit_error_key(table, field)] = str(msg)


def _get_submit_error(table: str, field: str) -> str | None:
    v = st.session_state.get(_submit_error_key(table, field))
    if isinstance(v, str) and v.strip():
        return v
    return None


def _clear_submit_error(table: str, field: str) -> None:
    st.session_state.pop(_submit_error_key(table, field), None)


def _rev_key(table: str, field: str) -> str:
    return _state_key(table, f"rev::{field}")


def _get_saved(table: str) -> dict[str, Any]:
    saved = st.session_state.get(_saved_key(table))
    if isinstance(saved, dict):
        saved.setdefault("fields", {})
        saved.setdefault("extra", [])
        saved.setdefault("others", {})
        return saved
    saved = {"fields": {}, "extra": [], "others": {}}
    st.session_state[_saved_key(table)] = saved
    return saved


def _get_others(table: str) -> dict[str, Any]:
    saved = _get_saved(table)
    others = saved.get("others")
    if isinstance(others, dict):
        return others
    saved["others"] = {}
    return saved["others"]


def others_no_child_rows_enabled(table: str) -> bool:
    return bool(_get_others(table).get("no_children"))


def _bump_rev(table: str, field: str) -> int:
    k = _rev_key(table, field)
    st.session_state[k] = int(st.session_state.get(k) or 0) + 1
    return int(st.session_state[k])


def _get_rev(table: str, field: str) -> int:
    return int(st.session_state.get(_rev_key(table, field)) or 0)


def _discard_draft(table: str, field: str) -> None:
    if field == "__others__":
        return
    if field == "__extra__":
        saved_len = len(_get_extra_rows(table))
    else:
        saved_len = len(_get_field_rows(table, field))
    _set_draft_len(table, field, saved_len)
    _bump_rev(table, field)


def _set_selected(table: str, field: str) -> None:
    prev = st.session_state.get(_state_key(table, "selected"))
    if isinstance(prev, str) and prev and prev != field:
        if prev == "extra.*":
            prev_key = "__extra__"
        elif prev == "others":
            prev_key = "__others__"
        else:
            prev_key = prev
        _discard_draft(table, prev_key)
        _clear_submit_error(table, prev_key)
    st.session_state[_state_key(table, "selected")] = field


def _get_selected(table: str, default: str | None = None) -> str | None:
    v = st.session_state.get(_state_key(table, "selected"))
    if isinstance(v, str) and v:
        return v
    return default


def _get_field_rows(table: str, field: str) -> list[dict[str, Any]]:
    saved = _get_saved(table)
    fields = saved["fields"]
    rows = fields.get(field)
    if isinstance(rows, list):
        return rows
    fields[field] = []
    return fields[field]


def _set_field_rows(table: str, field: str, rows: list[dict[str, Any]]) -> None:
    saved = _get_saved(table)
    saved["fields"][field] = rows


def _get_extra_rows(table: str) -> list[dict[str, Any]]:
    saved = _get_saved(table)
    rows = saved.get("extra")
    if isinstance(rows, list):
        return rows
    saved["extra"] = []
    return saved["extra"]


def _set_extra_rows(table: str, rows: list[dict[str, Any]]) -> None:
    saved = _get_saved(table)
    saved["extra"] = rows


def _row_is_effective(row: dict[str, Any], *, is_extra: bool) -> bool:
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


def _has_effective_conditions(table: str, field: str) -> bool:
    if field == "__extra__":
        return any(_row_is_effective(r, is_extra=True) for r in _get_extra_rows(table))
    if field == "__others__":
        return others_no_child_rows_enabled(table)
    return any(_row_is_effective(r, is_extra=False) for r in _get_field_rows(table, field))


def filterable_fields(table_spec: Any) -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    for col_name, col_spec in table_spec.columns.items():
        if bool(getattr(col_spec, "filterable", False)):
            out.append((col_name, col_spec))
    return out


def type_label_for_col(col_spec: Any) -> str:
    type_name = getattr(col_spec, "type_name", "text")
    item_type_name = getattr(col_spec, "item_type_name", None)
    if type_name == "list":
        return f"list[{item_type_name or 'text'}]"
    return str(type_name)


def build_where_from_saved(table: str, table_spec: Any) -> dict[str, Any]:
    conds: list[dict[str, Any]] = []

    for col_name, col_spec in filterable_fields(table_spec):
        type_name = getattr(col_spec, "type_name", "text")
        item_type_name = getattr(col_spec, "item_type_name", None)
        for r in _get_field_rows(table, col_name):
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
            conds.append({col_name: {op: parse_value(op, raw_s, type_name, item_type_name)}})

    for r in _get_extra_rows(table):
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


def rebuild_applied(table: str, table_spec: Any) -> None:
    st.session_state[_applied_where_key(table)] = build_where_from_saved(table, table_spec)


def get_applied_where(table: str, table_spec: Any) -> dict[str, Any]:
    if _applied_where_key(table) not in st.session_state:
        rebuild_applied(table, table_spec)
    return st.session_state.get(_applied_where_key(table)) or {}


def _add_row(table: str, field: str, table_spec: Any) -> None:
    if field == "__extra__":
        saved_len = len(_get_extra_rows(table))
        n = _get_draft_len(table, "__extra__", saved_len=saved_len)
        _set_draft_len(table, "__extra__", n + 1)
        return
    saved_len = len(_get_field_rows(table, field))
    n = _get_draft_len(table, field, saved_len=saved_len)
    _set_draft_len(table, field, n + 1)


def _remove_row(table: str, field: str, table_spec: Any) -> None:
    # '-' immediate (matches current UX):
    # - remove draft row if present
    # - else remove last saved row and apply immediately
    if field == "__extra__":
        saved_rows = _get_extra_rows(table)
        saved_len = len(saved_rows)
        draft_len = _get_draft_len(table, "__extra__", saved_len=saved_len)
        if draft_len > saved_len:
            _set_draft_len(table, "__extra__", draft_len - 1)
            return
        if not saved_rows:
            return
        saved_rows.pop()
        _set_extra_rows(table, saved_rows)
        _set_draft_len(table, "__extra__", len(saved_rows))
        _bump_rev(table, "__extra__")
        rebuild_applied(table, table_spec)
        return

    saved_rows = _get_field_rows(table, field)
    saved_len = len(saved_rows)
    draft_len = _get_draft_len(table, field, saved_len=saved_len)
    if draft_len > saved_len:
        _set_draft_len(table, field, draft_len - 1)
        return
    if not saved_rows:
        return
    saved_rows.pop()
    _set_field_rows(table, field, saved_rows)
    _set_draft_len(table, field, len(saved_rows))
    _bump_rev(table, field)
    rebuild_applied(table, table_spec)


def _submit_selected(table: str, table_spec: Any, field: str) -> None:
    if field == "extra.*":
        field = "__extra__"

    rev = _get_rev(table, field)
    if field == "__extra__":
        saved_rows = _get_extra_rows(table)
        draft_len = _get_draft_len(table, "__extra__", saved_len=len(saved_rows))
        committed: list[dict[str, Any]] = []
        for i in range(draft_len):
            k_key = _state_key(table, f"draft_extra_key::{i}::{rev}")
            op_key = _state_key(table, f"draft_extra_op::{i}::{rev}")
            v_key = _state_key(table, f"draft_extra_val::{i}::{rev}")
            row = {
                "key": str(st.session_state.get(k_key) or ""),
                "op": str(st.session_state.get(op_key) or ""),
                "raw": str(st.session_state.get(v_key) or ""),
            }
            if _row_is_effective(row, is_extra=True):
                committed.append(row)
        _set_extra_rows(table, committed)
        _set_draft_len(table, "__extra__", len(committed))
        _bump_rev(table, "__extra__")
        _clear_submit_error(table, "__extra__")
        rebuild_applied(table, table_spec)
        return

    cols = getattr(table_spec, "columns", {})
    col_spec = cols.get(field)
    type_name = getattr(col_spec, "type_name", "text")
    item_type_name = getattr(col_spec, "item_type_name", None)

    saved_rows = _get_field_rows(table, field)
    draft_len = _get_draft_len(table, field, saved_len=len(saved_rows))
    committed = []
    for i in range(draft_len):
        op_key = _state_key(table, f"draft_op::{field}::{i}::{rev}")
        v_key = _state_key(table, f"draft_val::{field}::{i}::{rev}")
        row = {
            "op": str(st.session_state.get(op_key) or ""),
            "raw": str(st.session_state.get(v_key) or ""),
        }

        if not _row_is_effective(row, is_extra=False):
            continue

        op = (row.get("op") or "").strip()
        if op in {"is_null", "not_null"}:
            committed.append({"op": op, "raw": ""})
            continue

        raw_s = (row.get("raw") or "").strip()
        try:
            parse_value(op, raw_s, type_name, item_type_name)
        except Exception as e:
            ph = value_placeholder(op, type_name, item_type_name)
            # Keep message short; show it inside the filters panel (stored in session_state).
            _set_submit_error(
                table,
                field,
                f"Invalid value (#{i + 1}, op={_OP_LABELS.get(op, op)}). Expected: {ph}.",
            )
            # Ensure the error appears on the *first* Enter: the error banner is
            # rendered above the form, so we force a rerun after storing it.
            try:
                st.rerun()
            except Exception:
                pass
            return

        committed.append(row)
    _set_field_rows(table, field, committed)
    _set_draft_len(table, field, len(committed))
    _bump_rev(table, field)
    _clear_submit_error(table, field)
    rebuild_applied(table, table_spec)


def render_filters_popover_content(db: DBManager, table: str, table_spec: Any) -> None:
    """Render the two-level Filters popover content.

    Side effects: updates saved/applied filters state in st.session_state.
    """

    filterable = filterable_fields(table_spec)
    if not filterable:
        st.caption("No filterable fields in this table.")
        return

    # Streamlit versions differ in selectbox width behavior (and some don't support
    # `use_container_width`). Enforce a sensible minimum so labels like "not null"
    # don't get truncated in narrow popovers.
    st.markdown(
        """
        <style>
        /* Keep the Filters trigger button constrained to its column. */
        div[data-testid="stPopover"] {
          width: 100% !important;
          max-width: 100% !important;
        }

        /* Widen only the floating panel (body/content), not the trigger.
           Streamlit DOM varies by version; the actual panel is BaseWeb "popover" Body.
           Target specific stPopoverBody to avoid affecting nested popovers like selectbox menus. */
        div[data-testid="stPopoverBody"] {
          width: min(1200px, 95vw) !important;
          min-width: min(1200px, 95vw) !important;
          max-width: 95vw !important;
        }

        div[data-baseweb="select"] > div { min-width: 100%; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Some Streamlit versions auto-size popovers to the intrinsic content width.
    # Normal fields may stay narrow (2 columns) while extra.* appears wider.
    # Add a zero-height spacer to request a wider floating panel without affecting
    # the trigger button width.
    st.markdown(
        '<div style="width: min(1200px, 95vw); height: 0; overflow: hidden;"></div>',
        unsafe_allow_html=True,
    )

    spec_by_name = {n: s for n, s in filterable}
    # Give more space to the condition editor panel.
    left, right = st.columns([0.9, 3.1], gap="medium")

    with left:
        options = [n for n, _ in filterable] + ["extra.*", "others"]
        default_selected = options[0] if options else "others"
        selected = _get_selected(table, default_selected) or default_selected
        if selected not in options:
            selected = default_selected
            _set_selected(table, selected)

        with st.container(height=420, border=False):
            for name in options:
                is_extra = name == "extra.*"
                is_others = name == "others"
                if is_extra:
                    field_key = "__extra__"
                elif is_others:
                    field_key = "__others__"
                else:
                    field_key = name
                active = _has_effective_conditions(table, field_key)

                if is_extra:
                    label = "extra.*"
                elif is_others:
                    label = "others"
                else:
                    label = name
                if name == selected:
                    label = f"▶ {label}"

                st.button(
                    label,
                    key=_state_key(table, f"pick::{name}"),
                    type=("primary" if active else "secondary"),
                    on_click=_set_selected,
                    args=(table, name),
                    use_container_width=True,
                )

    with right:
        # Show submit/validation errors inside the 2nd-level panel (not the main page).
        # Map the UI selection to the internal field key.
        if selected == "extra.*":
            _err_field = "__extra__"
        elif selected == "others":
            _err_field = "__others__"
        else:
            _err_field = selected

        err = _get_submit_error(table, _err_field)
        if err:
            st.error(err)

        if selected == "others":
            st.markdown("**others**")

            enabled = others_no_child_rows_enabled(table)
            # Note: whether it is a no-op depends on incoming FKs.
            from agentfabric.ui._relations import referencing_foreign_keys

            refs = referencing_foreign_keys(db, table)
            if not refs:
                st.caption("This table is not referenced by any other table; this filter is a no-op.")
            else:
                st.caption("Show rows that are not referenced by any other table via foreign keys.")

            def _toggle_no_children() -> None:
                others = _get_others(table)
                others["no_children"] = not bool(others.get("no_children"))
                rebuild_applied(table, table_spec)

            st.button(
                "No child rows",
                type=("primary" if enabled else "secondary"),
                on_click=_toggle_no_children,
                use_container_width=True,
            )

        elif selected == "extra.*":
            st.markdown("**extra.\\***")
            field_key = "__extra__"
            saved_rows = _get_extra_rows(table)
            rev = _get_rev(table, field_key)
            draft_len = _get_draft_len(table, field_key, saved_len=len(saved_rows))

            hdr = st.columns([0.18, 0.18, 1.0])
            hdr[0].button(
                "",
                key=_state_key(table, "extra_add"),
                icon=":material/add:",
                help="add condition",
                on_click=_add_row,
                args=(table, field_key, table_spec),
            )
            hdr[1].button(
                "",
                key=_state_key(table, "extra_rm"),
                icon=":material/remove:",
                help="remove last condition",
                on_click=_remove_row,
                args=(table, field_key, table_spec),
            )

            st.caption("Press Enter to apply conditions for this field")

            if draft_len == 0:
                st.caption("No conditions. Click + to add one.")

            for i in range(draft_len):
                r = saved_rows[i] if i < len(saved_rows) else {"key": "", "op": "", "raw": ""}
                row = st.columns([1.5, 1.0, 3.5])
                row[0].text_input(
                    "extra key",
                    key=_state_key(table, f"draft_extra_key::{i}::{rev}"),
                    value=str(r.get("key") or ""),
                    placeholder="tag",
                    label_visibility="collapsed",
                )

                extra_ops = ["", "eq", "ne", "like", "in_", "nin", "is_null", "not_null"]
                cur_op = str(r.get("op") or "")
                idx = extra_ops.index(cur_op) if cur_op in extra_ops else 0
                extra_op_key = _state_key(table, f"draft_extra_op::{i}::{rev}")
                extra_op = _selectbox_compat(
                    row[1],
                    label="op",
                    options=extra_ops,
                    index=idx,
                    key=extra_op_key,
                    label_visibility="collapsed",
                    format_func=lambda v: _OP_LABELS.get(v, v),
                    on_change=_submit_if_null_op,
                    args=(table, table_spec, selected, extra_op_key),
                )

                if extra_op in {"is_null", "not_null"}:
                    row[2].caption("NULL check ignores value")
                else:
                    extra_placeholder = value_placeholder(extra_op, "text", None) or "value"

                    row[2].text_input(
                        "value",
                        key=_state_key(table, f"draft_extra_val::{i}::{rev}"),
                        value=str(r.get("raw") or ""),
                        placeholder=extra_placeholder,
                        label_visibility="collapsed",
                        on_change=_submit_selected,
                        args=(table, table_spec, selected),
                    )


        else:
            col_spec = spec_by_name[selected]
            type_name = getattr(col_spec, "type_name", "text")
            type_label = type_label_for_col(col_spec)
            st.markdown(f"**{selected}** ({type_label})")

            saved_rows = _get_field_rows(table, selected)
            rev = _get_rev(table, selected)
            draft_len = _get_draft_len(table, selected, saved_len=len(saved_rows))

            hdr = st.columns([0.18, 0.18, 1.0])
            hdr[0].button(
                "",
                key=_state_key(table, f"add::{selected}"),
                icon=":material/add:",
                help="add condition",
                on_click=_add_row,
                args=(table, selected, table_spec),
            )
            hdr[1].button(
                "",
                key=_state_key(table, f"rm::{selected}"),
                icon=":material/remove:",
                help="remove last condition",
                on_click=_remove_row,
                args=(table, selected, table_spec),
            )

            st.caption("Press Enter to apply conditions for this field")
            ops = [""] + infer_ops(type_name)

            if draft_len == 0:
                st.caption("No conditions. Click + to add one.")

            for i in range(draft_len):
                r = saved_rows[i] if i < len(saved_rows) else {"op": "", "raw": ""}
                row = st.columns([1.0, 4.0])
                cur_op = str(r.get("op") or "")
                idx = ops.index(cur_op) if cur_op in ops else 0
                op_key = _state_key(table, f"draft_op::{selected}::{i}::{rev}")
                op = _selectbox_compat(
                    row[0],
                    label="op",
                    options=ops,
                    index=idx,
                    key=op_key,
                    label_visibility="collapsed",
                    format_func=lambda v: _OP_LABELS.get(v, v),
                    on_change=_submit_if_null_op,
                    args=(table, table_spec, selected, op_key),
                )

                if op in {"is_null", "not_null"}:
                    row[1].caption("NULL check ignores value")
                else:
                    row[1].text_input(
                        "value",
                        key=_state_key(table, f"draft_val::{selected}::{i}::{rev}"),
                        value=str(r.get("raw") or ""),
                        placeholder=value_placeholder(op, type_name, getattr(col_spec, "item_type_name", None)),
                        label_visibility="collapsed",
                        on_change=_submit_selected,
                        args=(table, table_spec, selected),
                    )

    st.divider()
    # No explicit clear-all in the UI; users can remove conditions per-field.
