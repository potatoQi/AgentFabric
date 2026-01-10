from __future__ import annotations

from typing import Any

from sqlalchemy import and_, select


def referencing_foreign_keys(db: Any, ref_table: str) -> list[tuple[str, Any]]:
    """Return (child_table_name, fk_spec) that reference `ref_table`.

    Uses the AgentFabric registry specs rather than DB reflection.
    """

    out: list[tuple[str, Any]] = []
    for tname, tdef in db.registry.tables.items():
        for fk in getattr(tdef, "foreign_keys", []) or []:
            if getattr(fk, "ref_table", None) == ref_table:
                out.append((tname, fk))
    return out


def is_fk_violation(exc: Exception) -> bool:
    """Best-effort detection for FK constraint violations (psycopg3 + SQLAlchemy)."""

    try:
        import psycopg  # type: ignore
        from psycopg.errors import ForeignKeyViolation  # type: ignore

        if isinstance(getattr(exc, "orig", None), ForeignKeyViolation):
            return True
    except Exception:
        pass

    msg = str(exc).lower()
    return "foreignkeyviolation" in msg or "violates foreign key constraint" in msg


def apply_no_child_rows(stmt: Any, db: Any, parent_table: str) -> Any:
    """Add a NOT EXISTS clause for each incoming FK.

    Semantics: keep only parent rows that are not referenced by *any* child table.

    Supports composite keys by AND-ing equality predicates over the FK column pairs.
    """

    t_parent = db.tables[parent_table]
    refs = referencing_foreign_keys(db, parent_table)
    for child_table, fk in refs:
        cols = list(getattr(fk, "columns", []) or [])
        ref_cols = list(getattr(fk, "ref_columns", []) or [])
        if not cols or len(cols) != len(ref_cols):
            continue

        try:
            t_child = db.tables[child_table]
        except Exception:
            continue

        conds = []
        ok = True
        for child_col, ref_col in zip(cols, ref_cols):
            if child_col not in t_child.c or ref_col not in t_parent.c:
                ok = False
                break
            conds.append(t_child.c[child_col] == t_parent.c[ref_col])
        if not ok or not conds:
            continue

        exists_expr = select(1).select_from(t_child).where(and_(*conds)).exists()
        stmt = stmt.where(~exists_expr)

    return stmt
