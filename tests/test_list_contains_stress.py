from __future__ import annotations

from sqlalchemy import Column, Integer, MetaData, Table
from sqlalchemy.dialects.postgresql import ARRAY

from agentfabric.db.query import build_where


def _table() -> Table:
    md = MetaData()
    return Table(
        "t",
        md,
        Column("ints", ARRAY(Integer), nullable=True),
    )


def test_contains_stress_large_or_group_builds_fast() -> None:
    # Pure builder stress: ensure large boolean compositions don't explode.
    t = _table()

    # 500 OR branches: ints contains i
    where = {"or": [{"ints": {"contains": i}} for i in range(500)]}
    clauses = build_where(t, where, allowed_fields={"ints"})

    # build_where collapses an OR group into a single clause.
    assert len(clauses) == 1
    s = str(clauses[0])
    assert " OR " in s
    assert "ANY" in s


def test_contains_stress_nested_and_or_groups() -> None:
    t = _table()

    # 100 branches, each branch is AND of 3 contains.
    where = {
        "or": [
            {
                "and": [
                    {"ints": {"contains": i}},
                    {"ints": {"contains": i + 1}},
                    {"ints": {"contains": i + 2}},
                ]
            }
            for i in range(0, 300, 3)
        ]
    }

    clauses = build_where(t, where, allowed_fields={"ints"})
    assert len(clauses) == 1
    s = str(clauses[0])
    assert " OR " in s
    assert " AND " in s
