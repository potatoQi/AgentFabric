from __future__ import annotations

from sqlalchemy import Column, Integer, MetaData, String, Table
from sqlalchemy.dialects.postgresql import JSONB

import pytest

from agentfabric.db.query import build_where


def _table() -> Table:
    md = MetaData()
    return Table(
        "t",
        md,
        Column("repo", String, nullable=True),
        Column("attempt", Integer, nullable=True),
        Column("extra", JSONB, nullable=False),
    )


def test_build_where_requires_dict_ops() -> None:
    t = _table()
    with pytest.raises(TypeError):
        build_where(t, {"attempt": 1})


def test_build_where_enforces_allowed_fields_for_non_extra() -> None:
    t = _table()
    with pytest.raises(ValueError, match="not filterable"):
        build_where(t, {"attempt": {"eq": 1}}, allowed_fields={"repo"})


def test_build_where_allows_multiple_ops_per_field_and_and_semantics() -> None:
    t = _table()
    clauses = build_where(t, {"attempt": {"gte": 0, "lt": 3, "ne": 2}}, allowed_fields={"attempt"})
    # gte, lt, ne => 3 clauses
    assert len(clauses) == 3


def test_build_where_in_empty_list_returns_empty_result_clause() -> None:
    t = _table()
    clauses = build_where(t, {"attempt": {"in_": []}}, allowed_fields={"attempt"})
    assert clauses == [False]


def test_build_where_nin_empty_list_is_noop() -> None:
    t = _table()
    clauses = build_where(t, {"attempt": {"nin": []}}, allowed_fields={"attempt"})
    assert clauses == []


def test_build_where_is_null_true_false() -> None:
    t = _table()
    c1 = build_where(t, {"attempt": {"is_null": True}}, allowed_fields={"attempt"})
    assert len(c1) == 1
    c2 = build_where(t, {"attempt": {"is_null": False}}, allowed_fields={"attempt"})
    assert len(c2) == 1


def test_build_where_unknown_op_is_ignored_for_normal_fields() -> None:
    t = _table()
    clauses = build_where(
        t,
        {"attempt": {"eq": 1, "unknown": 2}},
        allowed_fields={"attempt"},
    )
    assert len(clauses) == 1


def test_build_where_is_null_can_be_combined_with_other_ops() -> None:
    t = _table()
    clauses = build_where(
        t,
        {"attempt": {"is_null": False, "eq": 1}},
        allowed_fields={"attempt"},
    )
    assert len(clauses) == 2


def test_build_where_extra_allows_only_text_safe_ops() -> None:
    t = _table()

    ok = build_where(t, {"extra.tag": {"eq": "debug", "like": "d%", "is_null": False}})
    assert len(ok) == 3

    with pytest.raises(ValueError, match="unsupported op"):
        build_where(t, {"extra.tag": {"gt": 1}})


def test_build_where_extra_in_empty_list_returns_empty_result_clause() -> None:
    t = _table()
    clauses = build_where(t, {"extra.tag": {"in_": []}})
    assert clauses == [False]


def test_build_where_extra_nin_empty_list_is_noop() -> None:
    t = _table()
    clauses = build_where(t, {"extra.tag": {"nin": []}})
    assert clauses == []
