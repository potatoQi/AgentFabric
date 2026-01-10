from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text

from agentfabric.config.spec import ColumnSpec, ConfigSpec, TableSpec
from agentfabric.db.facade import DB


def _db_url() -> str | None:
    return os.getenv("AGENTFABRIC_TEST_DB_URL") or os.getenv("DATABASE_URL")


@pytest.fixture(scope="session")
def db_url() -> str:
    url = _db_url()
    if not url:
        pytest.skip("Set AGENTFABRIC_TEST_DB_URL to enable Postgres in-out tests")
    return url


@pytest.fixture
def schema_name() -> str:
    return f"af_mig_{uuid.uuid4().hex[:10]}"


def _create_schema(db: DB, schema_name: str) -> None:
    with db.engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))


def _drop_schema(db: DB, schema_name: str) -> None:
    with db.engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))


def test_migration_add_nullable_column_is_allowed(db_url: str, schema_name: str) -> None:
    cfg1 = ConfigSpec(
        postgres_schema=schema_name,
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                    "n": ColumnSpec(type="int", nullable=False, filterable=True),
                },
            )
        },
    )

    db1 = DB(url=db_url, config=cfg1)
    _create_schema(db1, schema_name)
    db1.init_schema()

    T1 = db1.models["t"]
    db1.add(T1(id="r1", n=1, extra={"kind": "v1"}))

    # Add a new nullable column.
    cfg2 = ConfigSpec(
        postgres_schema=schema_name,
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                    "n": ColumnSpec(type="int", nullable=False, filterable=True),
                    "tags": ColumnSpec(type="list", item_type="text", nullable=True, filterable=True),
                },
                indexes=[{"name": "idx_t_n", "columns": ["n"]}],
            )
        },
    )

    db2 = DB(url=db_url, config=cfg2)
    db2.init_schema()

    # Existing row should still be readable; new col should be NULL.
    out = db2.query("t", {"where": {"id": {"eq": "r1"}}, "limit": 10})
    assert len(out) == 1
    assert out[0].tags is None

    # New writes can include the new column.
    T2 = db2.models["t"]
    db2.add(T2(id="r2", n=2, tags=["a"], extra={"kind": "v2"}))
    out2 = db2.query("t", {"where": {"id": {"eq": "r2"}}, "limit": 10})
    assert len(out2) == 1
    assert out2[0].tags == ["a"]

    _drop_schema(db2, schema_name)


def test_migration_pk_change_is_rejected(db_url: str, schema_name: str) -> None:
    cfg1 = ConfigSpec(
        postgres_schema=schema_name,
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                    "n": ColumnSpec(type="int", nullable=False, filterable=True),
                },
            )
        },
    )
    db1 = DB(url=db_url, config=cfg1)
    _create_schema(db1, schema_name)
    db1.init_schema()

    cfg2 = ConfigSpec(
        postgres_schema=schema_name,
        tables={
            "t": TableSpec(
                primary_key=["id", "n"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                    "n": ColumnSpec(type="int", nullable=False, filterable=True),
                },
            )
        },
    )

    db2 = DB(url=db_url, config=cfg2)
    with pytest.raises(ValueError, match="primary_key changed"):
        db2.init_schema()

    _drop_schema(db1, schema_name)


def test_migration_fk_change_is_rejected(db_url: str, schema_name: str) -> None:
    cfg1 = ConfigSpec(
        postgres_schema=schema_name,
        tables={
            "parent": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                },
            ),
            "child": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                    "parent_id": ColumnSpec(type="text", nullable=False, filterable=True),
                },
                foreign_keys=[
                    {
                        "columns": ["parent_id"],
                        "ref_table": "parent",
                        "ref_columns": ["id"],
                        "on_delete": "cascade",
                    }
                ],
            ),
        },
    )

    db1 = DB(url=db_url, config=cfg1)
    _create_schema(db1, schema_name)
    db1.init_schema()

    # Remove the FK in cfg2 => should be rejected.
    cfg2 = ConfigSpec(
        postgres_schema=schema_name,
        tables={
            "parent": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                },
            ),
            "child": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                    "parent_id": ColumnSpec(type="text", nullable=False, filterable=True),
                },
                foreign_keys=[],
            ),
        },
    )

    db2 = DB(url=db_url, config=cfg2)
    with pytest.raises(ValueError, match="foreign_keys changed"):
        db2.init_schema()

    _drop_schema(db1, schema_name)


def test_migration_column_delete_or_modify_is_rejected(db_url: str, schema_name: str) -> None:
    cfg1 = ConfigSpec(
        postgres_schema=schema_name,
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                    "n": ColumnSpec(type="int", nullable=False, filterable=True),
                },
            )
        },
    )

    db1 = DB(url=db_url, config=cfg1)
    _create_schema(db1, schema_name)
    db1.init_schema()

    # Delete column n in config => rejected.
    cfg_del = ConfigSpec(
        postgres_schema=schema_name,
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                },
            )
        },
    )
    db_del = DB(url=db_url, config=cfg_del)
    with pytest.raises(ValueError, match="columns not present in config"):
        db_del.init_schema()

    # Modify column type in config => rejected.
    cfg_mod = ConfigSpec(
        postgres_schema=schema_name,
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                    "n": ColumnSpec(type="float", nullable=False, filterable=True),
                },
            )
        },
    )
    db_mod = DB(url=db_url, config=cfg_mod)
    with pytest.raises(ValueError, match="column type changed"):
        db_mod.init_schema()

    _drop_schema(db1, schema_name)


def test_migration_add_not_null_column_without_default_is_rejected(db_url: str, schema_name: str) -> None:
    cfg1 = ConfigSpec(
        postgres_schema=schema_name,
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                },
            )
        },
    )

    db1 = DB(url=db_url, config=cfg1)
    _create_schema(db1, schema_name)
    db1.init_schema()

    # Add NOT NULL without server default => rejected.
    cfg2 = ConfigSpec(
        postgres_schema=schema_name,
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                    "created_at": ColumnSpec(type="datetime", nullable=False, filterable=True),
                },
            )
        },
    )
    db2 = DB(url=db_url, config=cfg2)
    with pytest.raises(ValueError, match="NOT NULL.*no server default"):
        db2.init_schema()

    _drop_schema(db1, schema_name)


def test_migration_add_not_null_column_with_server_default_is_allowed(db_url: str, schema_name: str) -> None:
    cfg1 = ConfigSpec(
        postgres_schema=schema_name,
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                    "n": ColumnSpec(type="int", nullable=False, filterable=True),
                },
            )
        },
    )

    db1 = DB(url=db_url, config=cfg1)
    _create_schema(db1, schema_name)
    db1.init_schema()
    T1 = db1.models["t"]
    db1.add(T1(id="r1", n=1, extra={"kind": "v1"}))

    # Add NOT NULL datetime with server default now() => allowed.
    cfg2 = ConfigSpec(
        postgres_schema=schema_name,
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                    "n": ColumnSpec(type="int", nullable=False, filterable=True),
                    "created_at": ColumnSpec(
                        type="datetime",
                        nullable=False,
                        default="now",
                        filterable=True,
                    ),
                },
            )
        },
    )
    db2 = DB(url=db_url, config=cfg2)
    db2.init_schema()

    out = db2.query("t", {"where": {"id": {"eq": "r1"}}, "limit": 10})
    assert len(out) == 1
    assert out[0].created_at is not None

    _drop_schema(db2, schema_name)


def test_migration_removing_server_default_is_rejected(db_url: str, schema_name: str) -> None:
    # Create schema with a server default.
    cfg1 = ConfigSpec(
        postgres_schema=schema_name,
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                    "created_at": ColumnSpec(
                        type="datetime",
                        nullable=False,
                        default="now",
                        filterable=True,
                    ),
                },
            )
        },
    )

    db1 = DB(url=db_url, config=cfg1)
    _create_schema(db1, schema_name)
    db1.init_schema()

    # Remove the default in config (would imply dropping DEFAULT in DB) => rejected.
    cfg2 = ConfigSpec(
        postgres_schema=schema_name,
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                    "created_at": ColumnSpec(type="datetime", nullable=False, filterable=True),
                },
            )
        },
    )
    db2 = DB(url=db_url, config=cfg2)
    with pytest.raises(ValueError, match="server_default changed"):
        db2.init_schema()

    _drop_schema(db1, schema_name)


def test_migration_live_has_extra_column_is_rejected(db_url: str, schema_name: str) -> None:
    cfg = ConfigSpec(
        postgres_schema=schema_name,
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                },
            )
        },
    )

    db = DB(url=db_url, config=cfg)
    _create_schema(db, schema_name)
    db.init_schema()

    # Simulate drift: someone added a column out-of-band.
    with db.engine.begin() as conn:
        conn.execute(text(f'ALTER TABLE "{schema_name}"."t" ADD COLUMN rogue_col TEXT'))

    db2 = DB(url=db_url, config=cfg)
    with pytest.raises(ValueError, match="columns not present in config"):
        db2.init_schema()

    _drop_schema(db, schema_name)


def test_migration_add_new_table_is_allowed(db_url: str, schema_name: str) -> None:
    cfg1 = ConfigSpec(
        postgres_schema=schema_name,
        tables={
            "t1": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                },
            )
        },
    )
    db1 = DB(url=db_url, config=cfg1)
    _create_schema(db1, schema_name)
    db1.init_schema()

    cfg2 = ConfigSpec(
        postgres_schema=schema_name,
        tables={
            "t1": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                },
            ),
            "t2": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                    "msg": ColumnSpec(type="text", nullable=True, filterable=True),
                },
            ),
        },
    )

    db2 = DB(url=db_url, config=cfg2)
    db2.init_schema()

    T2 = db2.models["t2"]
    db2.add(T2(id="x", msg="hello", extra={}))
    out = db2.query("t2", {"where": {"id": {"eq": "x"}}, "limit": 10})
    assert len(out) == 1
    assert out[0].msg == "hello"

    _drop_schema(db2, schema_name)


def test_migration_fk_no_action_is_equivalent_to_none(db_url: str, schema_name: str) -> None:
    cfg1 = ConfigSpec(
        postgres_schema=schema_name,
        tables={
            "parent": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                },
            ),
            "child": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                    "parent_id": ColumnSpec(type="text", nullable=False, filterable=True),
                },
                foreign_keys=[
                    {
                        "columns": ["parent_id"],
                        "ref_table": "parent",
                        "ref_columns": ["id"],
                        "on_delete": "no_action",
                    }
                ],
            ),
        },
    )
    db = DB(url=db_url, config=cfg1)
    _create_schema(db, schema_name)
    db.init_schema()

    # Re-init with on_delete omitted (None) should still be accepted.
    cfg2 = ConfigSpec(
        postgres_schema=schema_name,
        tables={
            "parent": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                },
            ),
            "child": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                    "parent_id": ColumnSpec(type="text", nullable=False, filterable=True),
                },
                foreign_keys=[
                    {
                        "columns": ["parent_id"],
                        "ref_table": "parent",
                        "ref_columns": ["id"],
                    }
                ],
            ),
        },
    )
    DB(url=db_url, config=cfg2).init_schema()

    _drop_schema(db, schema_name)


def test_migration_recreates_dropped_index(db_url: str, schema_name: str) -> None:
    cfg = ConfigSpec(
        postgres_schema=schema_name,
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                    "n": ColumnSpec(type="int", nullable=False, filterable=True),
                },
                indexes=[{"name": "idx_t_n", "columns": ["n"]}],
            )
        },
    )

    db = DB(url=db_url, config=cfg)
    _create_schema(db, schema_name)
    db.init_schema()

    # Drop index out-of-band.
    with db.engine.begin() as conn:
        conn.execute(text(f'DROP INDEX IF EXISTS "{schema_name}"."idx_t_n"'))

    # init_schema should recreate it.
    db2 = DB(url=db_url, config=cfg)
    db2.init_schema()

    with db2.engine.begin() as conn:
        res = conn.execute(
            text(
                """
                SELECT 1
                FROM pg_indexes
                WHERE schemaname = :s AND indexname = :i
                """
            ),
            {"s": schema_name, "i": "idx_t_n"},
        ).fetchall()
    assert res, "expected idx_t_n to exist after re-init"

    _drop_schema(db2, schema_name)


def test_migration_wide_table_add_many_columns_stress(db_url: str, schema_name: str) -> None:
    cfg1 = ConfigSpec(
        postgres_schema=schema_name,
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                },
            )
        },
    )
    db1 = DB(url=db_url, config=cfg1)
    _create_schema(db1, schema_name)
    db1.init_schema()

    # Add a lot of nullable columns in one config update.
    extra_cols = {f"c{i}": ColumnSpec(type="text", nullable=True, filterable=True) for i in range(200)}
    cols2 = {"id": ColumnSpec(type="text", nullable=False, filterable=True), **extra_cols}
    cfg2 = ConfigSpec(
        postgres_schema=schema_name,
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns=cols2,
            )
        },
    )
    db2 = DB(url=db_url, config=cfg2)
    db2.init_schema()

    # Sanity: model includes some of the new cols.
    assert "c0" in db2.tables["t"].c
    assert "c199" in db2.tables["t"].c

    _drop_schema(db2, schema_name)
