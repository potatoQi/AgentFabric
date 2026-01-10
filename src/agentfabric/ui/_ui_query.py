from __future__ import annotations

from typing import Any

from sqlalchemy import select

from agentfabric.fabric import DBManager
from agentfabric.db.query import build_where as build_where_clauses
from agentfabric.ui._relations import apply_no_child_rows


def query_rows(
    db: DBManager,
    table: str,
    *,
    where: dict[str, Any],
    limit: int,
    offset: int = 0,
    no_child_rows: bool = False,
) -> list[dict[str, Any]]:
    """Query rows for the UI.

    Notes:
    - Uses the Filter DSL (agentfabric.db.query.build_where).
    - Applies relational filters ("No child rows") at query time via NOT EXISTS.
    """

    t_parent = db.tables[table]
    m_parent = db.models[table]

    allowed_fields = None
    allowed_fields = db.filterable_cols.get(table)

    clauses = build_where_clauses(t_parent, where, allowed_fields=allowed_fields)
    stmt = select(m_parent)
    if clauses:
        stmt = stmt.where(*clauses)

    if no_child_rows:
        stmt = apply_no_child_rows(stmt, db, table)

    stmt = stmt.limit(int(limit)).offset(int(offset))

    with db.Session() as s:
        items = list(s.execute(stmt).scalars().all())

    return [db.obj_to_dict(table, obj) for obj in items]
