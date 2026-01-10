from __future__ import annotations

from datetime import datetime, timezone
import copy
from uuid import UUID

import pytest

from agentfabric import AgentFabric
from agentfabric.db.facade import DB
from agentfabric.config.spec import ColumnSpec, ConfigSpec, TableSpec


def _cfg() -> ConfigSpec:
    return ConfigSpec(
        db_url="postgresql+psycopg://u:p@localhost:5432/db",
        postgres_schema="s",
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="uuid", nullable=False, default="uuid4", filterable=True),
                    "created_at": ColumnSpec(
                        type="datetime",
                        nullable=False,
                        default="now",
                        filterable=True,
                    ),
                    "msg": ColumnSpec(type="text", nullable=False, default="Hello", filterable=False),
                },
            )
        },
    )


@pytest.fixture(scope="module")
def db() -> DB:
    # Create once to avoid repeated dynamic ORM class registration warnings.
    return DB(config=_cfg())


def test_db_infers_url_from_config_path(tmp_path):
    p = tmp_path / "cfg.yaml"
    p.write_text(
        """
version: 1
db_url: postgresql+psycopg://u:p@localhost:5432/db
postgres_schema: s

tables:
  t:
    primary_key: [id]
    columns:
      id: {type: text, nullable: false, filterable: true}
""".lstrip(),
        encoding="utf-8",
    )

    dbm, _store = AgentFabric(str(p))
    assert dbm.engine.url.drivername.startswith("postgresql")


def test_db_init_argument_validation() -> None:
    cfg_no_url = _cfg().model_copy(update={"db_url": None})

    with pytest.raises(ValueError, match="provide url"):
        DB(config=cfg_no_url, url="")

    with pytest.raises(ValueError, match="provide url"):
        DB(config=cfg_no_url, url=None)


def test_db_precomputes_defaults_and_filterable_cols_without_connecting(db: DB) -> None:

    assert db._defaults["t"].keys() == {"id", "created_at", "msg"}
    assert db._filterable_cols["t"] == {"id", "created_at"}


def test_apply_sdk_defaults_row_fills_uuid_now_and_literal(db: DB) -> None:

    row = {"id": None}  # missing created_at/msg
    out = db._apply_sdk_defaults_row("t", row)

    assert isinstance(out["id"], UUID)
    assert isinstance(out["created_at"], datetime)
    assert out["created_at"].tzinfo == timezone.utc
    assert out["msg"] == "Hello"


def test_apply_sdk_defaults_row_does_not_override_non_null_values(db: DB) -> None:
    fixed_id = UUID("00000000-0000-0000-0000-000000000001")
    fixed_dt = datetime(2020, 1, 1, tzinfo=timezone.utc)
    row = {"id": fixed_id, "created_at": fixed_dt, "msg": "X"}
    out = db._apply_sdk_defaults_row("t", copy.deepcopy(row))
    assert out == row


def test_apply_sdk_defaults_obj_sets_attributes_on_orm_instance(db: DB) -> None:

    Model = db.models["t"]
    obj = Model()

    assert getattr(obj, "id", None) is None
    db._apply_sdk_defaults_obj(obj)

    assert isinstance(obj.id, UUID)
    assert isinstance(obj.created_at, datetime)
    assert obj.created_at.tzinfo == timezone.utc
    assert obj.msg == "Hello"


def test_literal_default_is_deep_copied_between_rows() -> None:
    cfg = ConfigSpec(
        tables={
            "t2": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, default="X"),
                    # json column type is not supported; keep the test's intent (deep-copy literal defaults)
                    # by using a text column with a dict default.
                    "meta": ColumnSpec(type="text", nullable=False, default={"tags": []}),
                },
            )
        }
    )
    db2 = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)

    r1 = db2._apply_sdk_defaults_row("t2", {})
    r2 = db2._apply_sdk_defaults_row("t2", {})

    r1["meta"]["tags"].append("A")
    assert r2["meta"]["tags"] == []


def test_obj_to_dict_includes_uuid_values(db: DB) -> None:

    Model = db.models["t"]
    obj = Model()
    db._apply_sdk_defaults_obj(obj)

    d = db._obj_to_dict("t", obj)
    assert isinstance(d["id"], UUID)
    assert "extra" in d  # fixed column exists in tables
