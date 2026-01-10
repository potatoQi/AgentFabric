from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import dialect as pg_dialect

from agentfabric.config.spec import ColumnSpec, ConfigSpec, TableSpec
from agentfabric.schema.builder import SchemaBuilder
from agentfabric.schema.migrate import SchemaDiffError, _norm_type_sql, apply_incremental_schema
from agentfabric.schema.registry import SchemaRegistry


class _DummyConn:
    def __init__(self):
        self.executed: list[str] = []

    def execute(self, clause):
        # clause is a sqlalchemy.sql.elements.TextClause
        self.executed.append(str(getattr(clause, "text", clause)))


class _DummyInspector:
    def __init__(
        self,
        *,
        has_tables: set[str],
        columns_by_table: dict[str, list[dict]],
        pk_by_table: dict[str, list[str]] | None = None,
        fks_by_table: dict[str, list[dict]] | None = None,
    ):
        self._has_tables = has_tables
        self._cols = columns_by_table
        self._pks = pk_by_table or {}
        self._fks = fks_by_table or {}

    def has_table(self, table_name: str, schema=None) -> bool:  # noqa: ANN001
        return table_name in self._has_tables

    def get_pk_constraint(self, table_name: str, schema=None) -> dict:  # noqa: ANN001
        return {"constrained_columns": list(self._pks.get(table_name, []))}

    def get_foreign_keys(self, table_name: str, schema=None) -> list[dict]:  # noqa: ANN001
        return list(self._fks.get(table_name, []))

    def get_columns(self, table_name: str, schema=None) -> list[dict]:  # noqa: ANN001
        return list(self._cols.get(table_name, []))


class _DummyEngine:
    def __init__(self, conn: _DummyConn):
        self.dialect = pg_dialect()
        self._conn = conn

    @contextmanager
    def begin(self):
        yield self._conn


def _build(cfg: ConfigSpec):
    reg = SchemaRegistry.from_config(cfg)
    md, tables = SchemaBuilder(reg).build()
    return reg, md, tables


def test_norm_type_sql_equates_float_and_double_precision() -> None:
    assert _norm_type_sql("FLOAT") == "double precision"
    assert _norm_type_sql("double precision") == "double precision"
    assert _norm_type_sql("float8") == "double precision"


def test_incremental_schema_raises_on_live_extra_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = ConfigSpec(
        postgres_schema="s",
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),
                },
            )
        },
    )
    reg, md, tables = _build(cfg)

    # Create a fake live table with an extra column that config doesn't know about.
    insp = _DummyInspector(
        has_tables={"t"},
        pk_by_table={"t": ["id"]},
        columns_by_table={
            "t": [
                {"name": "id", "nullable": False, "type": None},
                {"name": "extra", "nullable": False, "type": None},
                {"name": "hacker_col", "nullable": True, "type": None},
            ]
        },
    )

    # Patch inspect() used by migrate.py
    monkeypatch.setattr("agentfabric.schema.migrate.inspect", lambda _conn: insp)

    # Avoid calling real create_all; this unit test focuses on diff logic.
    monkeypatch.setattr(md, "create_all", lambda _engine, checkfirst=True: None)

    conn = _DummyConn()
    eng = _DummyEngine(conn)

    with pytest.raises(SchemaDiffError, match="columns not present in config"):
        apply_incremental_schema(eng, registry=reg, metadata=md, tables=tables)


def test_incremental_schema_adds_missing_column_with_quoted_identifiers(monkeypatch: pytest.MonkeyPatch) -> None:
    # Use a schema + identifiers that need quoting.
    cfg = ConfigSpec(
        postgres_schema="My-Schema",
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),
                    "user.name": ColumnSpec(type="text", nullable=True),
                },
            )
        },
    )
    reg, md, tables = _build(cfg)

    # Live only has id + extra; user.name is missing.
    insp = _DummyInspector(
        has_tables={"t"},
        pk_by_table={"t": ["id"]},
        columns_by_table={
            "t": [
                {"name": "id", "nullable": False, "type": Text()},
                {"name": "extra", "nullable": False, "type": JSONB(), "default": "'{}'::jsonb"},
            ]
        },
    )
    monkeypatch.setattr("agentfabric.schema.migrate.inspect", lambda _conn: insp)
    monkeypatch.setattr(md, "create_all", lambda _engine, checkfirst=True: None)

    conn = _DummyConn()
    eng = _DummyEngine(conn)

    apply_incremental_schema(eng, registry=reg, metadata=md, tables=tables)

    # Ensure an ALTER TABLE ADD COLUMN was issued and the identifiers were quoted.
    ddl = "\n".join(conn.executed)
    assert "ALTER TABLE" in ddl
    assert '"My-Schema".t' in ddl
    assert 'ADD COLUMN "user.name"' in ddl
