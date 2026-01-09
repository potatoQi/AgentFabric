from __future__ import annotations

import itertools
import re
from typing import Any

from sqlalchemy.orm import DeclarativeBase


def _camel(name: str) -> str:
    parts = re.split(r"[_\-\s]+", name)
    raw = "".join(p[:1].upper() + p[1:] for p in parts if p)
    # Make it a valid identifier: replace invalid chars, avoid leading digits.
    cleaned = re.sub(r"[^0-9A-Za-z_]", "_", raw)
    if cleaned == "":
        cleaned = "T"
    if cleaned[0].isdigit():
        cleaned = "T" + cleaned
    if not cleaned.isidentifier():
        cleaned = re.sub(r"\W", "_", cleaned)
        if cleaned and cleaned[0].isdigit():
            cleaned = "T" + cleaned
    return cleaned


_base_counter = itertools.count(1)


def _new_base() -> type[DeclarativeBase]:
    # A dedicated DeclarativeBase per DB instance prevents SQLAlchemy warnings about
    # re-declaring same-named classes in a shared registry.
    n = next(_base_counter)
    return type(f"AFBase{n}", (DeclarativeBase,), {})


class ORMModelFactory:
    def __init__(self, tables: dict[str, Any]):
        self.tables = tables
        self.Base = _new_base()

    def build_models(self) -> dict[str, type[Any]]:
        models: dict[str, type[Any]] = {}
        for table_name, table in self.tables.items():
            cls_name = _camel(table_name)
            attrs: dict[str, Any] = {"__table__": table, "__module__": __name__}

            # SQLAlchemy ORM requires a primary key for mapped classes.
            # If the DB table has no primary key constraint, provide a best-effort
            # mapper primary key so users can still construct objects and use
            # add/add_all. This does NOT change the DB schema.
            if len(getattr(table, "primary_key", []) or []) == 0:
                fallback_cols = [c for c in table.c if c.name != "extra"]
                if fallback_cols:
                    attrs["__mapper_args__"] = {"primary_key": [fallback_cols[0]]}

            cls = type(cls_name, (self.Base,), attrs)
            models[table_name] = cls
        return models
