from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from agentfabric import AgentFabric
from agentfabric.artifacts.store import ArtifactStore
from agentfabric.db.facade import DB
from agentfabric.config.spec import ColumnSpec, ConfigSpec, TableSpec


def _db_url() -> str | None:
    return os.getenv("AGENTFABRIC_TEST_DB_URL") or os.getenv("DATABASE_URL")


@pytest.fixture(scope="session")
def db_url() -> str:
    url = _db_url()
    if not url:
        pytest.skip("Set AGENTFABRIC_TEST_DB_URL to enable Postgres in-out tests")
    return url


@pytest.fixture
def schema_name() -> str:
    return f"af_test_{uuid.uuid4().hex[:10]}"


@pytest.fixture
def config(schema_name: str) -> ConfigSpec:
    # Minimal but representative schema covering:
    # - composite PK
    # - composite FK
    # - list[text] (ARRAY)
    # - defaults (now / literal)
    # - filterable enforcement
    return ConfigSpec(
        postgres_schema=schema_name,
        tables={
            "ace_instance": TableSpec(
                primary_key=["instance_id", "gold_patch_cov"],
                columns={
                    "instance_id": ColumnSpec(type="text", nullable=False, filterable=True),
                    "gold_patch_cov": ColumnSpec(type="float", nullable=False, filterable=True),
                    "repo": ColumnSpec(type="text", nullable=False, filterable=True),
                    "created_at": ColumnSpec(type="datetime", nullable=False, default="now", filterable=True),
                    "status": ColumnSpec(type="text", nullable=False, default="new", filterable=False),
                    "f2p": ColumnSpec(type="list", item_type="text", nullable=True),
                    "traj_url": ColumnSpec(type="text", nullable=True),
                },
            ),
            "ace_traj": TableSpec(
                primary_key=["agent", "model", "instance_id", "attempt", "gold_patch_cov"],
                columns={
                    "agent": ColumnSpec(type="text", nullable=False, filterable=True),
                    "model": ColumnSpec(type="text", nullable=False, filterable=True),
                    "instance_id": ColumnSpec(type="text", nullable=False, filterable=True),
                    "attempt": ColumnSpec(type="int", nullable=False, filterable=True),
                    "gold_patch_cov": ColumnSpec(type="float", nullable=False, filterable=True),
                    "patch_url": ColumnSpec(type="text", nullable=True),
                    "traj_url": ColumnSpec(type="text", nullable=True),
                },
                foreign_keys=[
                    {
                        "columns": ["instance_id", "gold_patch_cov"],
                        "ref_table": "ace_instance",
                        "ref_columns": ["instance_id", "gold_patch_cov"],
                        "on_delete": "cascade",
                    }
                ],
            ),
        },
    )


@pytest.fixture
def db(db_url: str, config: ConfigSpec, schema_name: str) -> DB:
    db = DB(url=db_url, config=config)

    with db.engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))

    db.init_schema()

    yield db

    with db.engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))


def test_inout_init_add_query_roundtrip(db: DB) -> None:
    Instance = db.models["ace_instance"]

    row = Instance(
        instance_id="ins_001",
        gold_patch_cov=0.42,
        repo="org/repo",
        f2p=["a", "b"],
        extra={"tag": "debug"},
    )

    db.add(row)

    items = db.query(
        "ace_instance",
        {
            "where": {
                "instance_id": {"eq": "ins_001"},
                "gold_patch_cov": {"eq": 0.42},
            }
        },
    )

    assert len(items) == 1
    got = items[0]
    assert got.repo == "org/repo"
    assert got.status == "new"  # literal default applied by SDK
    assert got.created_at is not None
    assert got.f2p == ["a", "b"]


def test_inout_filterable_enforced_blackbox(db: DB) -> None:
    # status is not filterable by config
    with pytest.raises(ValueError, match="not filterable"):
        db.query("ace_instance", {"where": {"status": {"eq": "new"}}})


def test_inout_extra_text_filters_blackbox(db: DB) -> None:
    Instance = db.models["ace_instance"]

    db.add(
        Instance(
            instance_id="ins_extra_001",
            gold_patch_cov=0.01,
            repo="org/repo",
            extra={"tag": "debug"},
        )
    )

    items = db.query(
        "ace_instance",
        {"where": {"extra.tag": {"eq": "debug"}}},
    )
    assert len(items) >= 1


def test_inout_update_requires_nonempty_where(db: DB) -> None:
    with pytest.raises(ValueError, match="non-empty where"):
        db.update("ace_instance", where={}, patch={"repo": "x"})


def test_inout_upsert_updates_on_conflict(db: DB) -> None:
    Instance = db.models["ace_instance"]
    Traj = db.models["ace_traj"]

    # Satisfy composite FK.
    db.add(
        Instance(
            instance_id="ins_001",
            gold_patch_cov=0.42,
            repo="org/repo",
            extra={"tag": "debug"},
        )
    )

    t1 = Traj(
        instance_id="ins_001",
        gold_patch_cov=0.42,
        agent="agent",
        model="model",
        attempt=0,
        patch_url="file:///tmp/old.diff",
    )

    out1 = db.upsert("ace_traj", t1)
    assert out1.patch_url == "file:///tmp/old.diff"

    t2 = Traj(
        instance_id="ins_001",
        gold_patch_cov=0.42,
        agent="agent",
        model="model",
        attempt=0,
        patch_url="file:///tmp/new.diff",
    )

    out2 = db.upsert("ace_traj", t2)
    assert out2.patch_url == "file:///tmp/new.diff"

    items = db.query(
        "ace_traj",
        {
            "where": {
                "instance_id": {"eq": "ins_001"},
                "attempt": {"eq": 0},
                "agent": {"eq": "agent"},
            }
        },
    )
    assert len(items) == 1
    assert items[0].patch_url == "file:///tmp/new.diff"


def test_inout_artifact_url_flow_blackbox(db: DB, tmp_path: Path) -> None:
    base_dir = tmp_path / "artifacts"
    store = ArtifactStore(base_url=f"file://{base_dir}")

    # Write local file and put into artifact store
    local_patch = tmp_path / "patch.diff"
    local_patch.write_text("diff --git a/a.py b/a.py\n...\n", encoding="utf-8")
    patch_res = store.put(str(local_patch), "runs/001/patch.diff")

    # Save URL into DB and read back
    Instance = db.models["ace_instance"]
    Traj = db.models["ace_traj"]

    # Satisfy composite FK.
    db.add(
        Instance(
            instance_id="ins_001",
            gold_patch_cov=0.42,
            repo="org/repo",
            extra={"tag": "debug"},
        )
    )

    t = Traj(
        instance_id="ins_001",
        gold_patch_cov=0.42,
        agent="agent",
        model="model",
        attempt=1,
        patch_url=patch_res.url,
        extra={"kind": "patch"},
    )
    db.upsert("ace_traj", t)

    items = db.query(
        "ace_traj",
        {"where": {"attempt": {"eq": 1}, "instance_id": {"eq": "ins_001"}}, "limit": 1},
    )
    assert len(items) == 1

    url = items[0].patch_url
    with store.open(url, "rb") as f:
        content = f.read()
    assert content.startswith(b"diff --git")


def test_inout_db_from_config_path_blackbox(db_url: str, tmp_path: Path) -> None:
    schema = f"af_test_{uuid.uuid4().hex[:10]}"
    cfg_path = tmp_path / "cfg.yaml"

    cfg_path.write_text(
        f"""
version: 1
db_url: {db_url}
postgres_schema: {schema}

tables:
  t:
    primary_key: [id]
    columns:
      id: {{type: text, nullable: false, filterable: true}}
      msg: {{type: text, nullable: false, default: Hello}}
""".lstrip(),
        encoding="utf-8",
    )

    dbm, _store = AgentFabric(str(cfg_path))
    with dbm.engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
    dbm.init_schema()

    T = dbm.models["t"]
    dbm.add(T(id="k"))

    got = dbm.query("t", {"where": {"id": {"eq": "k"}}})
    assert len(got) == 1
    assert got[0].msg == "Hello"

    with dbm.engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
