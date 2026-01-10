from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


ScalarTypeName = Literal["str", "text", "int", "float", "bool", "datetime", "uuid"]
TypeName = Literal["list", "str", "text", "int", "float", "bool", "datetime", "uuid"]


class ColumnSpec(BaseModel):
    type: TypeName
    item_type: ScalarTypeName | None = None
    nullable: bool = True
    default: Any | None = None  # supports: "now", "uuid4", or literal values
    index: bool = False
    filterable: bool = False

    @model_validator(mode="after")
    def _validate_list_type(self):
        if self.type == "list" and self.item_type is None:
            raise ValueError("column type 'list' requires item_type")
        if self.type != "list" and self.item_type is not None:
            raise ValueError("item_type is only allowed when type is 'list'")
        return self


class IndexSpec(BaseModel):
    name: str
    columns: list[str]

    @model_validator(mode="after")
    def _validate_index(self):
        if not isinstance(self.name, str) or self.name.strip() == "":
            raise ValueError("index name cannot be empty")
        if not self.columns:
            raise ValueError(f"index '{self.name}' must have at least one column")
        for c in self.columns:
            if not isinstance(c, str) or c.strip() == "":
                raise ValueError(f"index '{self.name}' has empty column name")
        return self


class ForeignKeySpec(BaseModel):
    columns: list[str]
    ref_table: str
    ref_columns: list[str]
    on_delete: Optional[Literal["cascade", "restrict", "set_null", "no_action"]] = None


class TableSpec(BaseModel):
    description: str | None = None
    primary_key: list[str] = Field(default_factory=list)
    columns: dict[str, ColumnSpec]
    indexes: list[IndexSpec] = Field(default_factory=list)
    foreign_keys: list[ForeignKeySpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_columns_and_primary_key(self):
        if not self.primary_key:
            raise ValueError("primary_key is required for every table")

        # Reserved column: every table automatically gets an `extra` JSONB column.
        # Reject any user-defined column that would collide or confuse.
        for name in self.columns.keys():
            if isinstance(name, str) and name.lower() == "extra":
                raise ValueError("'extra' is a reserved column name used by AgentFabric")

        # Postgres treats unquoted identifiers as case-insensitive.
        # We reject case-insensitive duplicates to avoid ambiguous schemas.
        lowered: dict[str, str] = {}
        for name in self.columns.keys():
            key = name.lower()
            if key in lowered:
                raise ValueError(
                    f"duplicate column name (case-insensitive): {lowered[key]!r} vs {name!r}"
                )
            lowered[key] = name

        # If PK is specified, all PK columns must exist and be non-nullable.
        for pk in self.primary_key:
            if pk not in self.columns:
                raise ValueError(f"primary_key column not found: {pk}")
            if self.columns[pk].nullable:
                raise ValueError(f"primary_key column must be non-nullable: {pk}")

        return self


class ConfigSpec(BaseModel):
    version: int = 1
    db_url: str | None = None
    artifact_base_url: str | None = None
    postgres_schema: str | None = None
    tables: dict[str, TableSpec]

    @model_validator(mode="after")
    def _validate_table_names(self):
        if isinstance(self.db_url, str) and self.db_url.strip() == "":
            self.db_url = None
        if isinstance(self.artifact_base_url, str) and self.artifact_base_url.strip() == "":
            self.artifact_base_url = None
        for tname in self.tables.keys():
            if not isinstance(tname, str) or tname.strip() == "":
                raise ValueError("table name cannot be empty")
        return self
