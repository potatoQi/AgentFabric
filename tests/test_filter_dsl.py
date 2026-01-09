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

    def test_build_where_eq_ne_none_are_rejected() -> None:
        from sqlalchemy import Column, Integer, MetaData, Table
        from sqlalchemy.dialects.postgresql import JSONB

        md = MetaData()
        t = Table(
            "test",
            md,
            Column("id", Integer, nullable=True),
            Column("extra", JSONB, nullable=False),
        )

        with pytest.raises(ValueError, match="Use 'is_null: True/False'"):
            build_where(t, {"id": {"eq": None}}, allowed_fields={"id"})

        with pytest.raises(ValueError, match="Use 'is_null: True/False'"):
            build_where(t, {"id": {"ne": None}}, allowed_fields={"id"})

        with pytest.raises(ValueError, match="Use 'is_null: True/False'"):
            build_where(t, {"extra.tag": {"eq": None}})


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


    def test_build_where_extra_nested_path_is_supported() -> None:
        t = _table()
        clauses = build_where(t, {"extra.a.b": {"eq": "x"}})
        assert len(clauses) == 1
        s = str(clauses[0])
        assert "extra" in s
        # Postgres JSON traversal should mention both keys in compiled SQL.
        assert "a" in s and "b" in s


    def test_build_where_extra_nested_path_dot_escape() -> None:
        t = _table()
        clauses = build_where(t, {"extra.a\\.b.c": {"eq": "x"}})
        assert len(clauses) == 1


    def test_build_where_extra_nested_path_rejects_empty_segment() -> None:
        t = _table()
        with pytest.raises(ValueError, match="empty segment"):
            build_where(t, {"extra.a..b": {"eq": "x"}})


def test_build_where_extra_in_empty_list_returns_empty_result_clause() -> None:
    t = _table()
    clauses = build_where(t, {"extra.tag": {"in_": []}})
    assert clauses == [False]


def test_build_where_extra_nin_empty_list_is_noop() -> None:
    t = _table()
    clauses = build_where(t, {"extra.tag": {"nin": []}})
    assert clauses == []


def test_build_where_and_group_allows_multiple_constraints_same_field() -> None:
    t = _table()
    clauses = build_where(
        t,
        {
            "and": [
                {"attempt": {"gte": 0}},
                {"attempt": {"lt": 3}},
                {"attempt": {"ne": 2}},
            ]
        },
        allowed_fields={"attempt"},
    )
    assert len(clauses) == 3


def test_build_where_or_group_builds_single_or_clause() -> None:
    t = _table()
    clauses = build_where(
        t,
        {"or": [{"attempt": {"eq": 1}}, {"attempt": {"eq": 2}}]},
        allowed_fields={"attempt"},
    )
    assert len(clauses) == 1
