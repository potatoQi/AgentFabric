from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text

from agentfabric.db.facade import DB
from agentfabric.config.spec import ColumnSpec, ConfigSpec, TableSpec


def _db_url() -> str | None:
    return os.getenv("AGENTFABRIC_TEST_DB_URL") or os.getenv("DATABASE_URL")


@pytest.fixture(scope="session")
def db_url() -> str:
    url = _db_url()
    if not url:
        pytest.skip("Set AGENTFABRIC_TEST_DB_URL to enable Postgres in-out tests")
    return url


@pytest.fixture(scope="module")
def schema_name() -> str:
    return f"af_stress_{uuid.uuid4().hex[:10]}"


@pytest.fixture(scope="module")
def db(db_url: str, schema_name: str) -> DB:
    cfg = ConfigSpec(
        postgres_schema=schema_name,
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                    "n": ColumnSpec(type="int", nullable=False, filterable=True),
                    "group": ColumnSpec(type="text", nullable=True, filterable=True),
                    "msg": ColumnSpec(type="text", nullable=False, default="Hello"),
                },
            )
        },
    )

    db = DB(url=db_url, config=cfg)
    with db.engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))
    db.init_schema()

    yield db

    with db.engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))


def test_stress_bulk_insert_and_pagination(db: DB) -> None:
    T = db.models["t"]

    rows = [
        T(id=f"k{i}", n=i, group=("A" if i % 2 == 0 else "B"), extra={"tag": "x" if i % 3 == 0 else "y"})
        for i in range(200)
    ]
    db.add_all(rows)

    page1 = db.query("t", {"where": {"group": {"eq": "A"}}, "limit": 10, "offset": 0})
    page2 = db.query("t", {"where": {"group": {"eq": "A"}}, "limit": 10, "offset": 10})

    assert len(page1) == 10
    assert len(page2) == 10
    assert {r.id for r in page1}.isdisjoint({r.id for r in page2})


def test_stress_in_empty_list_returns_empty(db: DB) -> None:
    out = db.query("t", {"where": {"id": {"in_": []}}})
    assert out == []


def test_stress_multiple_ops_and_extra_like(db: DB) -> None:
    # n in [0, 200) and not equal 5
    out = db.query(
        "t",
        {
            "where": {
                "n": {"gte": 0, "lt": 200, "ne": 5},
                "extra.tag": {"like": "x%"},
            },
            "limit": 1000,
        },
    )
    assert all(0 <= r.n < 200 and r.n != 5 for r in out)
    assert all((r.extra or {}).get("tag") == "x" for r in out)


def test_stress_upsert_last_write_wins(db: DB) -> None:
    T = db.models["t"]

    db.upsert("t", T(id="up", n=1, group="A", extra={"v": 1}))
    db.upsert("t", T(id="up", n=2, group="B", extra={"v": 2}))

    got = db.query("t", {"where": {"id": {"eq": "up"}}, "limit": 1})
    assert len(got) == 1
    assert got[0].n == 2
    assert got[0].group == "B"
    assert (got[0].extra or {}).get("v") == 2
