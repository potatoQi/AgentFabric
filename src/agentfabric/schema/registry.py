from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agentfabric.config.spec import ConfigSpec


@dataclass(frozen=True)
class ColumnDef:
    name: str
    type_name: str
    item_type_name: str | None
    nullable: bool
    default: Any | None
    index: bool
    filterable: bool


@dataclass
class ForeignKeyDef:
    columns: list[str]
    ref_table: str
    ref_columns: list[str]
    on_delete: str | None


@dataclass
class IndexDef:
    name: str
    columns: list[str]


@dataclass
class TableDef:
    name: str
    columns: dict[str, ColumnDef] = field(default_factory=dict)
    primary_key: list[str] = field(default_factory=list)
    indexes: list[IndexDef] = field(default_factory=list)
    foreign_keys: list[ForeignKeyDef] = field(default_factory=list)


class SchemaRegistry:
    def __init__(self, *, postgres_schema: str | None = None):
        self.postgres_schema = postgres_schema
        self.tables: dict[str, TableDef] = {}
        self._frozen = False

    def freeze(self) -> None:
        self._frozen = True

    def register_table(self, name: str) -> TableDef:
        if self._frozen:
            raise RuntimeError("schema frozen")
        if name in self.tables:
            return self.tables[name]
        t = TableDef(name=name)
        self.tables[name] = t
        return t

    @classmethod
    def from_config(cls, cfg: ConfigSpec) -> "SchemaRegistry":
        reg = cls(postgres_schema=cfg.postgres_schema)

        def _get(obj: Any, key: str) -> Any:
            if hasattr(obj, key):
                return getattr(obj, key)
            if isinstance(obj, dict):
                if key in obj:
                    return obj[key]
                if key == "on_delete":
                    return None
                raise TypeError(f"invalid foreign key spec item: missing '{key}'")
            if key == "on_delete":
                return None
            raise TypeError(f"invalid foreign key spec item: missing '{key}'")

        for table_name, ts in cfg.tables.items():
            t = reg.register_table(table_name)
            t.primary_key = list(ts.primary_key)

            for col_name, cs in ts.columns.items():
                t.columns[col_name] = ColumnDef(
                    name=col_name,
                    type_name=cs.type,
                    item_type_name=cs.item_type,
                    nullable=cs.nullable,
                    default=cs.default,
                    index=cs.index,
                    filterable=cs.filterable,
                )

            t.indexes = [IndexDef(name=i.name, columns=list(i.columns)) for i in ts.indexes]
            t.foreign_keys = [
                ForeignKeyDef(
                    columns=list(_get(fk, "columns")),
                    ref_table=str(_get(fk, "ref_table")),
                    ref_columns=list(_get(fk, "ref_columns")),
                    on_delete=_get(fk, "on_delete"),
                )
                for fk in ts.foreign_keys
            ]

        reg._validate()
        reg.freeze()
        return reg

    def _validate(self) -> None:
        # Index names must be unique within a Postgres schema.
        # Validate both implicit column indexes (idx_{table}_{col}) and explicit indexes.
        index_names: set[str] = set()

        for tname, tdef in self.tables.items():
            # PK columns exist
            for pk in tdef.primary_key:
                if pk not in tdef.columns:
                    raise ValueError(f"table '{tname}' primary_key column not found: {pk}")

            # index names are unique
            for c in tdef.columns.values():
                if c.index:
                    idx_name = f"idx_{tname}_{c.name}"
                    if idx_name in index_names:
                        raise ValueError(f"duplicate index name: {idx_name}")
                    index_names.add(idx_name)

            for idx in tdef.indexes:
                if idx.name in index_names:
                    raise ValueError(f"duplicate index name: {idx.name}")
                index_names.add(idx.name)

            # index columns exist
            for idx in tdef.indexes:
                for c in idx.columns:
                    if c not in tdef.columns:
                        raise ValueError(f"table '{tname}' index '{idx.name}' column not found: {c}")

            # foreign key references exist
            for fk in tdef.foreign_keys:
                if fk.ref_table not in self.tables:
                    raise ValueError(f"table '{tname}' foreign key ref_table not found: {fk.ref_table}")
                ref = self.tables[fk.ref_table]
                if len(fk.columns) != len(fk.ref_columns):
                    raise ValueError(
                        f"table '{tname}' foreign key column count mismatch: {fk.columns} -> {fk.ref_columns}"
                    )
                for c in fk.columns:
                    if c not in tdef.columns:
                        raise ValueError(f"table '{tname}' foreign key column not found: {c}")
                for rc in fk.ref_columns:
                    if rc not in ref.columns:
                        raise ValueError(
                            f"table '{tname}' foreign key ref_column not found in '{fk.ref_table}': {rc}"
                        )
