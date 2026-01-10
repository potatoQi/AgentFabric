from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, MetaData, Table, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from agentfabric.db.query import build_where


def _table() -> Table:
    md = MetaData()
    return Table(
        "t",
        md,
        Column("ints", ARRAY(Integer), nullable=True),
        Column("floats", ARRAY(Float), nullable=True),
        Column("bools", ARRAY(Boolean), nullable=True),
        Column("times", ARRAY(DateTime(timezone=True)), nullable=True),
        Column("uuids", ARRAY(PG_UUID(as_uuid=True)), nullable=True),
        Column("tags", ARRAY(Text), nullable=True),
        Column("n", Integer, nullable=True),
    )


def test_list_contains_int_builds_any_clause() -> None:
    t = _table()
    clauses = build_where(t, {"ints": {"contains": 3}}, allowed_fields={"ints"})
    assert len(clauses) == 1
    s = str(clauses[0])
    assert "ANY" in s
    assert "ints" in s


def test_list_contains_text_builds_any_clause() -> None:
    t = _table()
    clauses = build_where(t, {"tags": {"contains": "a"}}, allowed_fields={"tags"})
    assert len(clauses) == 1
    s = str(clauses[0])
    assert "ANY" in s
    assert "tags" in s


def test_list_contains_bool_is_strict() -> None:
    t = _table()
    ok = build_where(t, {"bools": {"contains": True}}, allowed_fields={"bools"})
    assert len(ok) == 1

    with pytest.raises(TypeError, match="expects a bool element"):
        build_where(t, {"bools": {"contains": 1}}, allowed_fields={"bools"})


def test_list_contains_float_is_strict() -> None:
    t = _table()
    ok = build_where(t, {"floats": {"contains": 1.5}}, allowed_fields={"floats"})
    assert len(ok) == 1

    # Strict: int is not accepted for float arrays
    with pytest.raises(TypeError, match="expects a float element"):
        build_where(t, {"floats": {"contains": 1}}, allowed_fields={"floats"})


def test_list_contains_datetime_requires_datetime_value() -> None:
    t = _table()
    dt = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    ok = build_where(t, {"times": {"contains": dt}}, allowed_fields={"times"})
    assert len(ok) == 1

    with pytest.raises(TypeError, match="expects a datetime element"):
        build_where(t, {"times": {"contains": "2025-01-01"}}, allowed_fields={"times"})


def test_list_contains_uuid_requires_uuid_value() -> None:
    t = _table()
    u = UUID("550e8400-e29b-41d4-a716-446655440000")
    ok = build_where(t, {"uuids": {"contains": u}}, allowed_fields={"uuids"})
    assert len(ok) == 1

    with pytest.raises(TypeError, match="expects a uuid element"):
        build_where(t, {"uuids": {"contains": "550e8400-e29b-41d4-a716-446655440000"}}, allowed_fields={"uuids"})


def test_list_contains_rejects_non_scalar_rhs() -> None:
    t = _table()
    with pytest.raises(TypeError, match="expects a scalar element"):
        build_where(t, {"ints": {"contains": [1, 2]}}, allowed_fields={"ints"})


def test_list_contains_rejects_none_rhs() -> None:
    t = _table()
    with pytest.raises(TypeError, match="does not accept None"):
        build_where(t, {"ints": {"contains": None}}, allowed_fields={"ints"})


def test_list_contains_type_mismatch_raises() -> None:
    t = _table()
    with pytest.raises(TypeError, match="expects an int element"):
        build_where(t, {"ints": {"contains": "3"}}, allowed_fields={"ints"})

    with pytest.raises(TypeError, match="expects a text element"):
        build_where(t, {"tags": {"contains": 3}}, allowed_fields={"tags"})


def test_list_contains_rejected_on_non_list_column() -> None:
    t = _table()
    with pytest.raises(TypeError, match="only supported for list/ARRAY"):
        build_where(t, {"n": {"contains": 1}}, allowed_fields={"n"})


def test_list_contains_works_inside_or_group() -> None:
    t = _table()
    clauses = build_where(
        t,
        {
            "or": [
                {"ints": {"contains": 1}},
                {"tags": {"contains": "x"}},
            ]
        },
        allowed_fields={"ints", "tags"},
    )
    assert len(clauses) == 1
    s = str(clauses[0])
    assert " OR " in s
    assert "ANY" in s
