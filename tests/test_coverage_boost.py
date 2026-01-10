from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import uuid

import fsspec
import pytest

from agentfabric import AgentFabric
from agentfabric.artifacts.store import ArtifactStore
from agentfabric.config.spec import ColumnSpec, ConfigSpec, TableSpec
from agentfabric.db.facade import DB
from agentfabric.db.query import _split_extra_path
from agentfabric.schema.orm import ORMModelFactory, _camel
from agentfabric.schema.registry import SchemaRegistry
from agentfabric.schema.types import map_server_default, map_type


def test_split_extra_path_trailing_escape_is_rejected() -> None:
    with pytest.raises(ValueError, match="trailing escape"):
        _split_extra_path("a\\")


def test_split_extra_path_basic_and_escape_behavior() -> None:
    assert _split_extra_path("a.b.c") == ["a", "b", "c"]
    assert _split_extra_path("a\\.b.c") == ["a.b", "c"]


def test_artifact_store_put_to_memory_filesystem(tmp_path: Path) -> None:
    store = ArtifactStore(base_url="memory:///af")

    src = tmp_path / "hello.txt"
    src.write_text("hi\n", encoding="utf-8")

    res = store.put(src, "runs/001/hello.txt")
    assert res.url.startswith("memory://")

    with fsspec.open(res.url, "rb") as f:
        assert f.read() == b"hi\n"


def test_artifact_store_put_bytes_local_and_remote(tmp_path: Path) -> None:
    store = ArtifactStore(base_url=str(tmp_path))

    out = tmp_path / "out.bin"
    r1 = store._put_bytes_to_url(str(out), b"abc")
    assert out.exists()
    assert out.read_bytes() == b"abc"
    assert r1.size_bytes == 3

    r2 = store._put_bytes_to_url("memory:///af/raw.bin", b"xyz")
    with fsspec.open(r2.url, "rb") as f:
        assert f.read() == b"xyz"


def test_artifact_store_file_scheme_absolute_dir_without_slash(tmp_path: Path) -> None:
    base_dir = tmp_path / "base"
    base_dir.mkdir()

    abs_dir = tmp_path / "absdir"
    abs_dir.mkdir()

    store = ArtifactStore(base_url=f"file://{base_dir}")

    src = tmp_path / "x.txt"
    src.write_text("x", encoding="utf-8")

    res = store.put(src, f"file://{abs_dir}", "b.txt")
    assert res.url == f"file://{abs_dir}/b.txt"
    assert (abs_dir / "b.txt").read_text(encoding="utf-8") == "x"


def test_artifact_store_helper_path_classification(tmp_path: Path) -> None:
    store = ArtifactStore(base_url=str(tmp_path))

    assert store._is_absolute_target("/abs/path") is True
    assert store._is_absolute_target("file:///abs/path") is True
    assert store._looks_like_file_target("runs/001/") is False
    assert store._looks_like_file_target("runs/001/.") is False
    assert store._looks_like_file_target("runs/001/..") is False
    assert store._looks_like_file_target("runs/001/a.txt") is True


def test_artifact_store_absolute_path_resolve_url_nonexistent(tmp_path: Path) -> None:
    store = ArtifactStore(base_url=str(tmp_path / "base"))

    src = tmp_path / "x.txt"
    src.write_text("x", encoding="utf-8")

    abs_dir_like = tmp_path / "no_such_dir"
    url = store._resolve_url(str(abs_dir_like), "b.txt", source=str(src))
    assert url.endswith("/no_such_dir/b.txt")


def test_db_init_argument_validation() -> None:
    cfg = ConfigSpec(
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={"id": ColumnSpec(type="text", nullable=False)},
            )
        }
    )

    with pytest.raises(ValueError, match="provide url"):
        DB(config=cfg, url="")

    with pytest.raises(TypeError):
        DB(url="postgresql+psycopg://u:p@localhost:5432/db")  # type: ignore[call-arg]


def test_agentfabric_init_with_config_path(tmp_path: Path) -> None:
    p = tmp_path / "cfg.yaml"
    p.write_text(
        """
version: 1
db_url: postgresql+psycopg://u:p@localhost:5432/db

tables:
  t:
    primary_key: [id]
    columns:
      id: {type: text, nullable: false, filterable: true}
      n: {type: int, nullable: false}
""".lstrip(),
        encoding="utf-8",
    )

    dbm, _store = AgentFabric(str(p))
    assert "t" in dbm.tables
    assert dbm.filterable_cols["t"] == {"id"}


def test_db_defaults_apply_to_obj_and_row_without_connecting() -> None:
    cfg = ConfigSpec(
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="uuid", nullable=False, default="uuid4"),
                    "created_at": ColumnSpec(type="datetime", nullable=False, default="now"),
                    "name": ColumnSpec(type="text", nullable=False, default="Default"),
                },
            )
        }
    )

    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
    Model = db.models["t"]

    obj = Model(id=None, created_at=None, name=None)
    obj2 = db._apply_sdk_defaults_obj(obj)
    assert isinstance(obj2.id, uuid.UUID)
    assert isinstance(obj2.created_at, datetime)
    assert obj2.name == "Default"

    row = db._apply_sdk_defaults_row("t", {})
    assert isinstance(row["id"], uuid.UUID)

    row2 = db._apply_sdk_defaults_row("t", {"name": "X"})
    assert row2["name"] == "X"


def test_db_defaults_do_not_override_zero_false_empty_string() -> None:
    cfg = ConfigSpec(
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),
                    "n": ColumnSpec(type="int", nullable=False, default=123),
                    "flag": ColumnSpec(type="bool", nullable=False, default=True),
                    "s": ColumnSpec(type="text", nullable=False, default="Default"),
                },
            )
        }
    )

    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
    Model = db.models["t"]

    obj = Model(id="1", n=0, flag=False, s="")
    obj2 = db._apply_sdk_defaults_obj(obj)
    assert obj2.n == 0
    assert obj2.flag is False
    assert obj2.s == ""

    row = db._apply_sdk_defaults_row("t", {"id": "1", "n": 0, "flag": False, "s": ""})
    assert row["n"] == 0
    assert row["flag"] is False
    assert row["s"] == ""


def test_schema_registry_freeze_blocks_registration() -> None:
    reg = SchemaRegistry()
    t1 = reg.register_table("t")
    t2 = reg.register_table("t")
    assert t1 is t2
    reg.freeze()
    with pytest.raises(RuntimeError, match="schema frozen"):
        reg.register_table("u")


def test_schema_registry_from_config_invalid_fk_shape_errors() -> None:
    # Bypass Pydantic by passing a duck-typed config object.
    bad_cfg = SimpleNamespace(
        postgres_schema=None,
        tables={
            "a": SimpleNamespace(
                primary_key=["id"],
                columns={
                    "id": SimpleNamespace(
                        type="text",
                        item_type=None,
                        nullable=False,
                        default=None,
                        index=False,
                        filterable=False,
                    )
                },
                indexes=[],
                foreign_keys=[],
            ),
            "b": SimpleNamespace(
                primary_key=["id"],
                columns={
                    "id": SimpleNamespace(
                        type="text",
                        item_type=None,
                        nullable=False,
                        default=None,
                        index=False,
                        filterable=False,
                    ),
                    "a_id": SimpleNamespace(
                        type="text",
                        item_type=None,
                        nullable=False,
                        default=None,
                        index=False,
                        filterable=False,
                    ),
                },
                indexes=[],
                foreign_keys=[{"ref_table": "a", "ref_columns": ["id"]}],  # missing columns
            ),
        },
    )

    with pytest.raises(TypeError, match="missing 'columns'"):
        SchemaRegistry.from_config(bad_cfg)  # type: ignore[arg-type]


def test_types_helpers_cover_more_branches() -> None:
    assert map_server_default("literal") is None
    assert map_server_default(None) is None
    assert "now" in str(map_server_default("now"))

    with pytest.raises(ValueError, match="unsupported type"):
        map_type("nope")

    with pytest.raises(ValueError, match="requires item_type"):
        map_type("list")

    assert map_type("uuid") is not None


def test_orm_camel_sanitization_and_no_pk_fallback_mapping() -> None:
    assert _camel("123table").isidentifier()
    assert _camel("") == "T"

    # Provide a Table without a PK and ensure ORM mapping still works via mapper_args.
    from sqlalchemy import Column, Integer, MetaData, Table
    from sqlalchemy.dialects.postgresql import JSONB

    md = MetaData()
    t = Table(
        "nopk",
        md,
        Column("id", Integer, nullable=True),
        Column("extra", JSONB, nullable=False),
    )

    models = ORMModelFactory({"nopk": t}).build_models()
    assert "nopk" in models
    _ = models["nopk"](id=1)
