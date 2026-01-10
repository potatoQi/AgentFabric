from __future__ import annotations

from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.schema import MetaData

from .registry import SchemaRegistry


class SchemaDiffError(ValueError):
    """Raised when the live DB schema is incompatible with the config schema."""


def _q(engine: Engine, ident: str) -> str:
    return engine.dialect.identifier_preparer.quote(ident)


def _table_ref(engine: Engine, *, schema: str | None, table: str) -> str:
    if schema:
        return f"{_q(engine, schema)}.{_q(engine, table)}"
    return _q(engine, table)


def _type_sql(engine: Engine, col: Any) -> str:
    return str(col.type.compile(dialect=engine.dialect))


def _default_sql(engine: Engine, col: Any) -> str | None:
    sd = getattr(col, "server_default", None)
    if sd is None:
        return None
    arg = getattr(sd, "arg", None)
    if arg is None:
        return None
    return str(arg.compile(dialect=engine.dialect))


def _norm(s: str | None) -> str | None:
    if s is None:
        return None
    return " ".join(str(s).strip().lower().split())


def _norm_type_sql(s: str | None) -> str | None:
    s2 = _norm(s)
    if s2 is None:
        return None

    # Postgres has type aliases/synonyms that SQLAlchemy may emit differently
    # between CREATE TABLE and Inspector reflection.
    if s2 in {"float", "float8", "double precision"}:
        return "double precision"

    return s2


def _ensure_indexes(conn: Any, metadata: MetaData) -> None:
    # Policy: indexes have no hard constraints.
    # We only create missing indexes; we never drop existing ones.
    for table in metadata.tables.values():
        for idx in table.indexes:
            idx.create(conn, checkfirst=True)


def _fk_key(fk: Any) -> tuple[tuple[str, ...], str, tuple[str, ...], str | None]:
    cols = tuple(str(c) for c in fk.columns)
    ref_table = str(fk.ref_table)
    ref_cols = tuple(str(c) for c in fk.ref_columns)
    on_delete = fk.on_delete
    if isinstance(on_delete, str):
        on_delete = on_delete.strip().lower()
    if on_delete in (None, "", "no_action", "no action"):
        on_delete = None
    return (cols, ref_table, ref_cols, on_delete)


def _inspected_fk_key(fk: dict[str, Any]) -> tuple[tuple[str, ...], str, tuple[str, ...], str | None]:
    cols = tuple(str(c) for c in (fk.get("constrained_columns") or []))
    ref_table = str(fk.get("referred_table") or "")
    ref_cols = tuple(str(c) for c in (fk.get("referred_columns") or []))
    ondelete = None
    opts = fk.get("options") or {}
    if isinstance(opts, dict):
        v = opts.get("ondelete")
        if isinstance(v, str) and v.strip():
            ondelete = v.strip().lower()
    return (cols, ref_table, ref_cols, ondelete)


def apply_incremental_schema(
    engine: Engine,
    *,
    registry: SchemaRegistry,
    metadata: MetaData,
    tables: dict[str, Any],
) -> None:
    """Initialize schema with a strict, safe incremental migration policy.

    Policy (as agreed):
    - PK/FK changes are forbidden
    - Columns: only additions are allowed
      - New columns must be nullable=True OR have a DB/server default
    - Indexes: no hard constraints; create missing, never drop

    This function is intentionally conservative: if the live DB has extra columns
    not present in config, it raises to avoid silent divergence.
    """

    schema = (registry.postgres_schema or "").strip() or None

    # 1) Create missing tables/columns/indexes for fresh DBs.
    metadata.create_all(engine, checkfirst=True)

    # 2) For existing tables, enforce invariants and add new columns.
    with engine.begin() as conn:
        insp = inspect(conn)

        for tname, tdef in registry.tables.items():
            if not insp.has_table(tname, schema=schema):
                # created by create_all above
                continue

            # ---- PK validation
            pk = insp.get_pk_constraint(tname, schema=schema) or {}
            live_pk = list(pk.get("constrained_columns") or [])
            expected_pk = list(tdef.primary_key)
            if live_pk != expected_pk:
                raise SchemaDiffError(
                    f"primary_key changed for table '{tname}': live={live_pk} cfg={expected_pk}"
                )

            # ---- FK validation
            live_fks = insp.get_foreign_keys(tname, schema=schema) or []
            live_fk_keys = sorted(_inspected_fk_key(fk) for fk in live_fks)
            expected_fk_keys = sorted(_fk_key(fk) for fk in (tdef.foreign_keys or []))
            if live_fk_keys != expected_fk_keys:
                raise SchemaDiffError(
                    f"foreign_keys changed for table '{tname}': live={live_fk_keys} cfg={expected_fk_keys}"
                )

            # ---- Column validation / additions
            live_cols = insp.get_columns(tname, schema=schema) or []
            live_by_name = {str(c.get("name")): c for c in live_cols if c.get("name") is not None}

            expected_names = set(tdef.columns.keys()) | {"extra"}
            live_names = set(live_by_name.keys())

            extra_live = sorted(live_names - expected_names)
            if extra_live:
                raise SchemaDiffError(
                    f"table '{tname}' has columns not present in config: {extra_live}"
                )

            missing = sorted(expected_names - live_names)
            if missing:
                table = tables[tname]
                tref = _table_ref(engine, schema=schema, table=tname)

                for cname in missing:
                    col = table.c[cname]

                    # New column rule: must be nullable OR have a DB/server default.
                    if col.nullable is False and _default_sql(engine, col) is None:
                        raise SchemaDiffError(
                            f"new column '{tname}.{cname}' is NOT NULL but has no server default; "
                            "use nullable=true or provide a server-side default"
                        )

                    type_sql = _type_sql(engine, col)
                    default_expr = _default_sql(engine, col)
                    default_sql = f" DEFAULT {default_expr}" if default_expr else ""
                    not_null_sql = " NOT NULL" if col.nullable is False else ""

                    stmt = f"ALTER TABLE {tref} ADD COLUMN {_q(engine, cname)} {type_sql}{default_sql}{not_null_sql}"
                    conn.execute(text(stmt))

            # ---- Column modification checks
            # For columns that exist in both live and config, ensure type/nullability are unchanged.
            table = tables[tname]
            for cname in sorted(expected_names & live_names):
                live = live_by_name[cname]
                exp_col = table.c[cname]

                # nullable
                live_nullable = bool(live.get("nullable"))
                if bool(exp_col.nullable) != live_nullable:
                    raise SchemaDiffError(
                        f"column nullable changed for '{tname}.{cname}': live={live_nullable} cfg={exp_col.nullable}"
                    )

                # type (best-effort string compare)
                live_type = live.get("type")
                live_type_sql = str(live_type.compile(dialect=engine.dialect)) if live_type is not None else ""
                exp_type_sql = _type_sql(engine, exp_col)
                if _norm_type_sql(live_type_sql) != _norm_type_sql(exp_type_sql):
                    raise SchemaDiffError(
                        f"column type changed for '{tname}.{cname}': live={live_type_sql} cfg={exp_type_sql}"
                    )

                # server default (only compare when config expects a server default)
                exp_def = _norm(_default_sql(engine, exp_col))
                live_def = _norm(live.get("default"))
                if exp_def != live_def:
                    # Policy: server-side defaults are part of the DB schema contract.
                    # Disallow both adding/changing and removing them.
                    raise SchemaDiffError(
                        f"column server_default changed for '{tname}.{cname}': live={live_def} cfg={exp_def}"
                    )

        # Indexes: create missing only (no drops)
        _ensure_indexes(conn, metadata)
