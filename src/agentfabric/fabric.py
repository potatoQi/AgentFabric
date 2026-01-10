from __future__ import annotations

from dataclasses import dataclass
from typing import Any, BinaryIO
from pathlib import Path

from agentfabric.artifacts.store import ArtifactStore
from agentfabric.config.loader import load_config
from agentfabric.db.facade import DB


@dataclass(frozen=True)
class DBManager:
    __db: DB

    @property
    def config(self):
        return self.__db.config

    @property
    def engine(self):
        return self.__db.engine

    @property
    def Session(self):
        return self.__db.Session

    @property
    def registry(self):
        return self.__db.registry

    @property
    def metadata(self):
        return self.__db.metadata

    @property
    def tables(self):
        return self.__db.tables

    @property
    def models(self):
        return self.__db.models

    @property
    def filterable_cols(self) -> dict[str, set[str]]:
        v = getattr(self.__db, "_filterable_cols", None)
        return v if isinstance(v, dict) else {}

    def obj_to_dict(self, table: str, obj: Any) -> dict[str, Any]:
        return self.__db._obj_to_dict(table, obj)

    def init_schema(self) -> None:
        self.__db.init_schema()

    def add(self, obj: Any) -> None:
        self.__db.add(obj)

    def add_all(self, objs: list[Any]) -> None:
        self.__db.add_all(objs)

    def query(self, table: str, filter: dict[str, Any], *, as_dict: bool = False) -> list[Any]:
        return self.__db.query(table, filter, as_dict=as_dict)

    def update(self, table: str, where: dict, patch: dict) -> int:
        return self.__db.update(table, where, patch)

    def delete_where(self, table: str, where: dict) -> int:
        return self.__db.delete_where(table, where)

    def upsert(self, table: str, obj: Any, *, conflict_cols: list[str] | None = None) -> Any:
        return self.__db.upsert(table, obj, conflict_cols=conflict_cols)

    def delete_by_pk(self, table: str, rows: list[dict[str, Any]]) -> int:
        return self.__db.delete_by_pk(table, rows)


@dataclass(frozen=True)
class StoreManager:
    __store: ArtifactStore

    def put(self, x: str | Any, y: str, z: str | None = None):
        return self.__store.put(x, y, z)

    def open(self, url: str, mode: str = "rb") -> BinaryIO:
        return self.__store.open(url, mode=mode)


def AgentFabric(config_path: str | Path) -> tuple[DBManager, StoreManager | None]:
    """Create the only user-facing entrypoint.

    Returns:
      - db: DBManager
      - store: StoreManager | None (None if artifact_base_url is missing in config)
    
    Notes:
      - DB URL is taken from YAML (db_url)
      - Store is only created when artifact_base_url is provided
    """

    cfg = load_config(config_path)
    db = DB(config=cfg)

    store: StoreManager | None = None
    base = (cfg.artifact_base_url or "").strip()
    if base:
        store = StoreManager(ArtifactStore(base_url=base))

    return DBManager(db), store
