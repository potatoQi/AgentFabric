from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


ScalarTypeName = Literal["str", "text", "int", "float", "bool", "datetime", "json", "uuid"]
TypeName = Literal["list", "str", "text", "int", "float", "bool", "datetime", "json", "uuid"]


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


class ConfigSpec(BaseModel):
    version: int = 1
    postgres_schema: str | None = None
    tables: dict[str, TableSpec]
