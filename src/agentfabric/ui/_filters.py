from __future__ import annotations

from typing import Any

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
    # text / uuid / json
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
        # SQLAlchemy/psycopg can parse ISO-like strings.
        return raw.strip()
    return raw


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
        rebuild_applied(table, table_spec)
        return

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
        if _row_is_effective(row, is_extra=False):
            committed.append(row)
    _set_field_rows(table, field, committed)
    _set_draft_len(table, field, len(committed))
    _bump_rev(table, field)
    rebuild_applied(table, table_spec)


def render_filters_popover_content(db: DBManager, table: str, table_spec: Any) -> None:
    """Render the two-level Filters popover content.

    Side effects: updates saved/applied filters state in st.session_state.
    """

    filterable = filterable_fields(table_spec)
    if not filterable:
        st.caption("No filterable fields in this table.")
        return

    spec_by_name = {n: s for n, s in filterable}
    left, right = st.columns([1.15, 2.0], gap="medium")

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
            st.markdown("**extra.* (top-level key)**")
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
            with st.form(key=_state_key(table, f"form::{field_key}::{rev}"), clear_on_submit=False):
                if draft_len == 0:
                    st.caption("No conditions. Click + to add one.")

                for i in range(draft_len):
                    r = saved_rows[i] if i < len(saved_rows) else {"key": "", "op": "", "raw": ""}
                    row = st.columns([1.4, 1.0, 2.0])
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
                    extra_op = row[1].selectbox(
                        "op",
                        options=extra_ops,
                        index=idx,
                        key=_state_key(table, f"draft_extra_op::{i}::{rev}"),
                        label_visibility="collapsed",
                        format_func=lambda v: _OP_LABELS.get(v, v),
                    )

                    if extra_op in {"is_null", "not_null"}:
                        row[2].caption("NULL check ignores value")
                    else:
                        row[2].text_input(
                            "value",
                            key=_state_key(table, f"draft_extra_val::{i}::{rev}"),
                            value=str(r.get("raw") or ""),
                            placeholder=("a,b,c" if extra_op in {"in_", "nin"} else "value"),
                            label_visibility="collapsed",
                        )

                submitted = st.form_submit_button(
                    " ",
                    help="__AF_APPLY__",
                    key=_state_key(table, f"submit::{field_key}::{rev}"),
                    type="tertiary",
                )
                if submitted:
                    _submit_selected(table, table_spec, selected)

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
            with st.form(key=_state_key(table, f"form::{selected}::{rev}"), clear_on_submit=False):
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
                        key=_state_key(table, f"draft_op::{selected}::{i}::{rev}"),
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
                            key=_state_key(table, f"draft_val::{selected}::{i}::{rev}"),
                            value=str(r.get("raw") or ""),
                            placeholder=placeholder,
                            label_visibility="collapsed",
                        )

                submitted = st.form_submit_button(
                    " ",
                    help="__AF_APPLY__",
                    key=_state_key(table, f"submit::{selected}::{rev}"),
                    type="tertiary",
                )
                if submitted:
                    _submit_selected(table, table_spec, selected)

    st.divider()
    # No explicit clear-all in the UI; users can remove conditions per-field.
