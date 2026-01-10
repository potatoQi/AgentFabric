from __future__ import annotations

from typing import Any

import streamlit as st
from sqlalchemy import delete

from agentfabric.fabric import DBManager
from agentfabric.db.query import build_where as build_where_clauses
from agentfabric.ui._relations import is_fk_violation, referencing_foreign_keys


def delete_where_compat(db: DBManager, table: str, where: dict[str, Any]) -> int:
    if not where:
        raise ValueError("delete_where requires non-empty where")

    t = db.tables[table]
    allowed_fields = db.filterable_cols.get(table) or set(t.c.keys())

    clauses = build_where_clauses(t, where, allowed_fields=allowed_fields)
    if not clauses:
        raise ValueError("delete_where produced empty clauses")

    stmt = delete(t).where(*clauses)
    with db.engine.begin() as conn:
        res = conn.execute(stmt)
    return int(getattr(res, "rowcount", 0) or 0)


def render_delete_panel(db: DBManager, table: str, pk_cols: list[str], selected_rows: list[dict[str, Any]]) -> None:
    """Render the safe delete UI for the selected rows.

    Side effects:
    - May delete rows.
    - May clear the table editor selection state and trigger st.rerun().
    """

    if not pk_cols or not selected_rows:
        return

    refs = referencing_foreign_keys(db, table)
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

    if not submitted:
        return

    if not confirm:
        st.warning("Please tick the confirmation checkbox before deleting.")
        return

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
                    delete_where_compat(db, child_table, where)

        n = db.delete_by_pk(table, selected_rows)
        st.success(f"Deleted {n} rows")

        # Clear selection so a new selection doesn't inherit old checkmarks.
        st.session_state.pop(f"editor::{table}", None)
        st.rerun()

    except Exception as e:
        if is_fk_violation(e) and refs and not cascade:
            tables = ", ".join(sorted({t for t, _ in refs}))
            st.error(
                "Delete failed due to foreign key references. "
                f"This table is referenced by: {tables}. "
                "Either delete dependent rows first, or enable 'cascade delete referencing rows'."
            )
        else:
            st.error(f"Delete failed: {e}")
