from __future__ import annotations

from sqlalchemy import Column, ForeignKeyConstraint, Index, MetaData, PrimaryKeyConstraint, Table
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import text

from .registry import SchemaRegistry
from .types import map_server_default, map_type


class SchemaBuilder:
    def __init__(self, registry: SchemaRegistry):
        self.registry = registry
        self.metadata = MetaData(schema=registry.postgres_schema)
        self.tables: dict[str, Table] = {}

    def build(self) -> tuple[MetaData, dict[str, Table]]:
        # 1) create Table objects with columns
        for tname, tdef in self.registry.tables.items():
            cols: list[Column] = []
            for c in tdef.columns.values():
                col = Column(
                    c.name,
                    map_type(c.type_name, item_type=c.item_type_name),
                    nullable=c.nullable,
                    server_default=map_server_default(c.default),
                )
                cols.append(col)

            # fixed extra
            cols.append(Column("extra", JSONB, nullable=False, server_default=text("'{}'::jsonb")))

            table = Table(tname, self.metadata, *cols)

            if tdef.primary_key:
                table.append_constraint(PrimaryKeyConstraint(*[table.c[c] for c in tdef.primary_key]))

            self.tables[tname] = table

        # 2) foreign keys
        for tname, tdef in self.registry.tables.items():
            if not tdef.foreign_keys:
                continue
            table = self.tables[tname]
            for fk in tdef.foreign_keys:
                ondelete = fk.on_delete
                if ondelete in (None, "no_action"):
                    ondelete = None
                table.append_constraint(
                    ForeignKeyConstraint(
                        fk.columns,
                        [f"{fk.ref_table}.{c}" for c in fk.ref_columns],
                        ondelete=ondelete,
                    )
                )

        # 3) indexes: column-level + explicit
        for tname, tdef in self.registry.tables.items():
            table = self.tables[tname]
            for c in tdef.columns.values():
                if c.index:
                    Index(f"idx_{tname}_{c.name}", table.c[c.name])
            for idx in tdef.indexes:
                Index(idx.name, *[table.c[c] for c in idx.columns])

        return self.metadata, self.tables
