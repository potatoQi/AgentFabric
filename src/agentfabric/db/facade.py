from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any
from uuid import UUID as PyUUID
import uuid

from sqlalchemy import and_, create_engine, delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import tuple_

from agentfabric.config.spec import ConfigSpec
from agentfabric.schema.builder import SchemaBuilder
from agentfabric.schema.orm import ORMModelFactory
from agentfabric.schema.registry import SchemaRegistry

from .query import build_where


class DB:
    def __init__(
        self,
        *,
        config: ConfigSpec,
        url: str | None = None,
    ):
        if url is None or str(url).strip() == "":
            url = config.db_url
        if not url:
            raise ValueError("provide url (or set db_url in config)")

        self.config = config
        self.registry = SchemaRegistry.from_config(config)

        self.engine = create_engine(url, pool_pre_ping=True)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)

        self.metadata, self.tables = SchemaBuilder(self.registry).build()
        self.models = ORMModelFactory(self.tables).build_models()

        # precompute per-table default specs
        # Semantics: if a column has `default` and the user provides None/missing, SDK will fill it.
        self._defaults: dict[str, dict[str, Any]] = {}
        for tname, tdef in self.registry.tables.items():
            defaults: dict[str, Any] = {}
            for c in tdef.columns.values():
                if c.default is not None:
                    defaults[c.name] = c.default
            self._defaults[tname] = defaults

        # precompute which columns are allowed in `where`
        self._filterable_cols: dict[str, set[str]] = {}
        for tname, tdef in self.registry.tables.items():
            cols = {c.name for c in tdef.columns.values() if c.filterable}
            self._filterable_cols[tname] = cols

    def init_schema(self) -> None:
        self.metadata.create_all(self.engine)

    def add(self, obj: Any) -> None:
        obj = self._apply_sdk_defaults_obj(obj)
        with self.Session() as s:
            s.add(obj)
            s.commit()

    def add_all(self, objs: list[Any]) -> None:
        objs = [self._apply_sdk_defaults_obj(o) for o in objs]
        with self.Session() as s:
            s.add_all(objs)
            s.commit()

    def query(self, table: str, filter: dict, *, as_dict: bool = False) -> list[Any]:
        t = self.tables[table]
        m = self.models[table]

        where = filter.get("where", {})
        limit = int(filter.get("limit", 1000))
        offset = int(filter.get("offset", 0))

        clauses = build_where(t, where, allowed_fields=self._filterable_cols.get(table))
        stmt = select(m)
        if clauses:
            stmt = stmt.where(*clauses)
        stmt = stmt.limit(limit).offset(offset)

        with self.Session() as s:
            items = list(s.execute(stmt).scalars().all())
            if not as_dict:
                return items
            return [self._obj_to_dict(table, obj) for obj in items]

    def update(self, table: str, where: dict, patch: dict) -> int:
        t = self.tables[table]
        clauses = build_where(t, where, allowed_fields=self._filterable_cols.get(table))
        if not clauses:
            raise ValueError("update requires non-empty where")

        stmt = update(t).where(*clauses).values(**patch)
        with self.Session() as s:
            res = s.execute(stmt)
            s.commit()
            return int(res.rowcount or 0)

    def delete_where(self, table: str, where: dict) -> int:
        """Delete rows matching a filter DSL `where`.

        Safety: requires a non-empty `where` (prevents accidental full-table deletes).
        """

        t = self.tables[table]
        clauses = build_where(t, where, allowed_fields=self._filterable_cols.get(table))
        if not clauses:
            raise ValueError("delete_where requires non-empty where")

        stmt = delete(t).where(and_(*clauses))
        with self.Session() as s:
            res = s.execute(stmt)
            s.commit()
            return int(res.rowcount or 0)

    def upsert(self, table: str, obj: Any, *, conflict_cols: list[str] | None = None) -> Any:
        # Optional convenience: keeps idempotency without exposing Session.
        t = self.tables[table]
        row = self._obj_to_dict(table, obj, include_extra=True)
        row = self._apply_sdk_defaults_row(table, row)

        if conflict_cols is None:
            pk = list(self.registry.tables[table].primary_key)
            if not pk:
                raise ValueError("no primary key defined; provide conflict_cols")
            conflict_cols = pk

        stmt = pg_insert(t).values(**row)
        update_cols = {k: stmt.excluded[k] for k in row.keys() if k not in set(conflict_cols)}
        stmt = stmt.on_conflict_do_update(index_elements=conflict_cols, set_=update_cols).returning(t)

        with self.Session() as s:
            out = s.execute(stmt).mappings().one()
            s.commit()

        # rehydrate an ORM instance
        model = self.models[table]
        return model(**dict(out))

    def delete_by_pk(self, table: str, rows: list[dict[str, Any]]) -> int:
        """Delete rows by primary key values.

        Designed for UIs/tools: it prevents accidental full-table deletes by requiring
        PK columns and a non-empty row list.
        """

        if not rows:
            return 0

        pk_cols = list(self.registry.tables[table].primary_key)
        if not pk_cols:
            raise ValueError("no primary key defined")

        t = self.tables[table]
        for c in pk_cols:
            if c not in t.c:
                raise ValueError(f"primary key column not found in table: {c}")

        # Build a tuple IN for composite PKs; for single PK, this is still fine.
        cols = [t.c[c] for c in pk_cols]
        keys: list[tuple[Any, ...]] = []
        for r in rows:
            keys.append(tuple(r.get(c) for c in pk_cols))

        # Filter out incomplete keys.
        keys = [k for k in keys if all(v is not None for v in k)]
        if not keys:
            raise ValueError("no complete primary key values provided")

        if len(cols) == 1:
            stmt = delete(t).where(cols[0].in_([k[0] for k in keys]))
        else:
            stmt = delete(t).where(tuple_(*cols).in_(keys))

        with self.Session() as s:
            res = s.execute(stmt)
            s.commit()
            return int(res.rowcount or 0)

    def _apply_sdk_defaults_row(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        defaults = self._defaults.get(table)
        if not defaults:
            return row

        for col, spec in defaults.items():
            if col in row and row[col] is not None:
                continue

            if spec == "uuid4":
                row[col] = uuid.uuid4()
            elif spec == "now":
                row[col] = datetime.now(timezone.utc)
            else:
                # literal defaults: 0, "", "Hello", True, lists/dicts, etc.
                row[col] = copy.deepcopy(spec)

        return row

    def _apply_sdk_defaults_obj(self, obj: Any) -> Any:
        table_name = getattr(getattr(obj, "__table__", None), "name", None)
        if not table_name:
            return obj
        defaults = self._defaults.get(str(table_name))
        if not defaults:
            return obj

        for col, spec in defaults.items():
            if getattr(obj, col, None) is not None:
                continue
            if spec == "uuid4":
                setattr(obj, col, uuid.uuid4())
            elif spec == "now":
                setattr(obj, col, datetime.now(timezone.utc))
            else:
                setattr(obj, col, copy.deepcopy(spec))
        return obj

    def _obj_to_dict(self, table: str, obj: Any, *, include_extra: bool = True) -> dict[str, Any]:
        t = self.tables[table]
        out: dict[str, Any] = {}
        for col in t.columns:
            if col.name == "extra" and not include_extra:
                continue
            if hasattr(obj, col.name):
                v = getattr(obj, col.name)
                if isinstance(v, PyUUID):
                    out[col.name] = v
                else:
                    out[col.name] = v
        return out
