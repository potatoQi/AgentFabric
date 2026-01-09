from __future__ import annotations

from pathlib import Path

import pytest

from agentfabric.config.loader import load_config
from agentfabric.config.spec import ColumnSpec, ConfigSpec, TableSpec
from agentfabric.schema.builder import SchemaBuilder
from agentfabric.schema.orm import ORMModelFactory
from agentfabric.schema.registry import SchemaRegistry
from agentfabric.schema.types import map_type


def test_columnspec_list_requires_item_type() -> None:
    with pytest.raises(ValueError, match="requires item_type"):
        ColumnSpec(type="list")


def test_columnspec_item_type_only_for_list() -> None:
    with pytest.raises(ValueError, match="only allowed"):
        ColumnSpec(type="text", item_type="text")


def test_load_config_parses_yaml(tmp_path: Path) -> None:
    p = tmp_path / "cfg.yaml"
    p.write_text(
        """
version: 1
postgres_schema: s

tables:
  t:
    primary_key: [id]
    columns:
      id: {type: text, nullable: false, filterable: true}
      tags: {type: list, item_type: text, nullable: true}
""".lstrip(),
        encoding="utf-8",
    )

    cfg = load_config(p)
    assert isinstance(cfg, ConfigSpec)
    assert cfg.postgres_schema == "s"
    assert "t" in cfg.tables
    assert cfg.tables["t"].columns["tags"].type == "list"
    assert cfg.tables["t"].columns["tags"].item_type == "text"


def test_config_rejects_whitespace_only_table_name() -> None:
    with pytest.raises(ValueError, match="table name cannot be empty"):
        ConfigSpec(
            tables={
                "   ": TableSpec(
                    primary_key=["id"],
                    columns={"id": ColumnSpec(type="text", nullable=False)},
                )
            }
        )


def test_config_rejects_reserved_extra_column_name() -> None:
    with pytest.raises(ValueError, match="reserved column name"):
        ConfigSpec(
            tables={
                "t": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="text", nullable=False),
                        "extra": ColumnSpec(type="text", nullable=False),
                    },
                )
            }
        )


def test_config_rejects_index_with_empty_columns_list() -> None:
    with pytest.raises(ValueError, match="must have at least one column"):
        ConfigSpec(
            tables={
                "t": TableSpec(
                    primary_key=["id"],
                    columns={"id": ColumnSpec(type="text", nullable=False)},
                    indexes=[{"name": "idx_empty", "columns": []}],
                )
            }
        )


def test_registry_validates_pk_columns_exist() -> None:
    with pytest.raises(Exception, match="primary_key column not found"):
        ConfigSpec(
            postgres_schema=None,
            tables={
                "t": TableSpec(
                    primary_key=["missing"],
                    columns={"id": ColumnSpec(type="text", nullable=False)},
                )
            },
        )


def test_registry_validates_fk_references_exist() -> None:
    cfg = ConfigSpec(
        tables={
            "a": TableSpec(
                primary_key=["id"],
                columns={"id": ColumnSpec(type="text", nullable=False)},
                foreign_keys=[],
            ),
            "b": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),
                    "a_id": ColumnSpec(type="text", nullable=False),
                },
                foreign_keys=[
                    {
                        "columns": ["a_id"],
                        "ref_table": "a",
                        "ref_columns": ["id"],
                        "on_delete": "cascade",
                    }
                ],
            ),
        }
    )

    # ForeignKeySpec is a pydantic model; allowing dicts here is fine.
    reg = SchemaRegistry.from_config(cfg)
    assert "b" in reg.tables


def test_registry_validates_index_columns_exist() -> None:
    cfg = ConfigSpec(
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={"id": ColumnSpec(type="text", nullable=False)},
                indexes=[{"name": "idx_bad", "columns": ["missing"]}],
            )
        }
    )
    with pytest.raises(ValueError, match="index 'idx_bad' column not found"):
        SchemaRegistry.from_config(cfg)


def test_registry_rejects_duplicate_index_names() -> None:
    # Column-level index will be named idx_t_repo; explicit index must not reuse it.
    cfg = ConfigSpec(
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),
                    "repo": ColumnSpec(type="text", nullable=False, index=True),
                },
                indexes=[{"name": "idx_t_repo", "columns": ["repo"]}],
            )
        }
    )

    with pytest.raises(ValueError, match="duplicate index name"):
        SchemaRegistry.from_config(cfg)


def test_registry_validates_fk_column_count_mismatch() -> None:
    cfg = ConfigSpec(
        tables={
            "a": TableSpec(
                primary_key=["id"],
                columns={"id": ColumnSpec(type="text", nullable=False)},
            ),
            "b": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),
                    "a_id": ColumnSpec(type="text", nullable=False),
                    "a_id2": ColumnSpec(type="text", nullable=False),
                },
                foreign_keys=[
                    {
                        "columns": ["a_id", "a_id2"],
                        "ref_table": "a",
                        "ref_columns": ["id"],
                    }
                ],
            ),
        }
    )
    with pytest.raises(ValueError, match="column count mismatch"):
        SchemaRegistry.from_config(cfg)


def test_schema_builder_primary_key_order_and_extra_column() -> None:
    cfg = ConfigSpec(
        postgres_schema="s",
        tables={
            "t": TableSpec(
                primary_key=["b", "a"],
                columns={
                    "a": ColumnSpec(type="text", nullable=False),
                    "b": ColumnSpec(type="text", nullable=False),
                },
            )
        },
    )

    reg = SchemaRegistry.from_config(cfg)
    md, tables = SchemaBuilder(reg).build()
    assert md.schema == "s"

    t = tables["t"]
    assert "extra" in t.c

    pk_cols = [c.name for c in list(t.primary_key.columns)]
    assert pk_cols == ["b", "a"]


def test_schema_builder_creates_indexes_and_now_server_default() -> None:
    cfg = ConfigSpec(
        postgres_schema=None,
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),
                    "repo": ColumnSpec(type="text", nullable=False, index=True),
                    "created_at": ColumnSpec(type="datetime", nullable=False, default="now"),
                },
                indexes=[{"name": "idx_t_repo_created", "columns": ["repo", "created_at"]}],
            )
        },
    )

    reg = SchemaRegistry.from_config(cfg)
    _, tables = SchemaBuilder(reg).build()
    t = tables["t"]

    idx_names = {idx.name for idx in t.indexes}
    assert "idx_t_repo" in idx_names
    assert "idx_t_repo_created" in idx_names

    # DB-side now() is set as server_default for datetime columns with default: now
    assert t.c.created_at.server_default is not None


def test_map_type_list_creates_array_type() -> None:
    ty = map_type("list", item_type="text")
    assert ty.__class__.__name__ == "ARRAY"


def test_orm_model_factory_generates_camel_case_class_names() -> None:
    cfg = ConfigSpec(
        tables={
            "ace_traj": TableSpec(
                primary_key=["id"],
                columns={"id": ColumnSpec(type="text", nullable=False)},
            )
        }
    )
    reg = SchemaRegistry.from_config(cfg)
    _, tables = SchemaBuilder(reg).build()
    models = ORMModelFactory(tables).build_models()
    assert models["ace_traj"].__name__ == "AceTraj"
