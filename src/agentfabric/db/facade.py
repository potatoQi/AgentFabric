from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any
from uuid import UUID as PyUUID
import uuid

from sqlalchemy import create_engine, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import sessionmaker

from agentfabric.config.spec import ConfigSpec
from agentfabric.schema.builder import SchemaBuilder
from agentfabric.schema.orm import ORMModelFactory
from agentfabric.schema.registry import SchemaRegistry

from .query import build_where


class DB:
    def __init__(
        self,
        url: str,
        *,
        config: ConfigSpec | None = None,
        config_path: str | None = None,
    ):
        if not url:
            raise ValueError("provide url")

        if (config is None) == (config_path is None):
            raise ValueError("provide exactly one of config or config_path")

        if config is None:
            from agentfabric.config.loader import load_config

            config = load_config(config_path)  # type: ignore[arg-type]

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
