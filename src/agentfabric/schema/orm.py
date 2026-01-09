from __future__ import annotations

import itertools
import re
from typing import Any

from sqlalchemy.orm import DeclarativeBase


def _camel(name: str) -> str:
    parts = re.split(r"[_\-\s]+", name)
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


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
            cls = type(cls_name, (self.Base,), {"__table__": table, "__module__": __name__})
            models[table_name] = cls
        return models
