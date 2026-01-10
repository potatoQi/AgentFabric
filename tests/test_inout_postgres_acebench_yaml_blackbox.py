from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import yaml
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from agentfabric import AgentFabric
from agentfabric.fabric import DBManager


def _db_url() -> str | None:
    return os.getenv("AGENTFABRIC_TEST_DB_URL") or os.getenv("DATABASE_URL")


@pytest.fixture(scope="session")
def db_url() -> str:
    url = _db_url()
    if not url:
        pytest.skip("Set AGENTFABRIC_TEST_DB_URL to enable Postgres in-out tests")
    return url


@pytest.fixture(scope="module")
def schema_name() -> str:
    return f"af_acebench_{uuid.uuid4().hex[:10]}"


@pytest.fixture(scope="module")
def cfg_path(tmp_path_factory: pytest.TempPathFactory, schema_name: str, db_url: str) -> Path:
    # Use the repo's ACE-Bench example YAML, but override postgres_schema to a random test schema.
    src = Path(__file__).resolve().parents[1] / "examples" / "acebench_schema.yaml"
    data = yaml.safe_load(src.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    data["postgres_schema"] = schema_name
    data["db_url"] = db_url

    dst = tmp_path_factory.mktemp("acebench_cfg") / "acebench_schema_test.yaml"
    dst.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return dst


@pytest.fixture(scope="module")
def db(cfg_path: Path, schema_name: str) -> DBManager:
    dbm, _store = AgentFabric(str(cfg_path))

    with dbm.engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))

    dbm.init_schema()

    yield dbm

    with dbm.engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))


def test_acebench_yaml_minimal_insert_and_defaults(db: DBManager) -> None:
    Instance = db.models["ace_instance"]

    # create_time is non-null with default: now; we rely on SDK default fill.
    row = Instance(
        instance_id="ins_001",
        gold_patch_cov=0.42,
        extra={"tag": "debug"},
    )
    db.add(row)

    got = db.query(
        "ace_instance",
        {"where": {"instance_id": {"eq": "ins_001"}, "gold_patch_cov": {"eq": 0.42}}, "limit": 1},
    )
    assert len(got) == 1
    assert got[0].create_time is not None


def test_acebench_yaml_list_columns_roundtrip(db: DBManager) -> None:
    Instance = db.models["ace_instance"]

    row = Instance(
        instance_id="ins_002",
        gold_patch_cov=0.11,
        f2p=["a", "b"],
        p2p=["c"],
        extra={},
    )
    db.add(row)

    got = db.query(
        "ace_instance",
        {"where": {"instance_id": {"eq": "ins_002"}, "gold_patch_cov": {"eq": 0.11}}, "limit": 1},
    )
    assert len(got) == 1
    assert got[0].f2p == ["a", "b"]
    assert got[0].p2p == ["c"]


def test_acebench_yaml_fk_violation_is_enforced(db: DBManager) -> None:
    Traj = db.models["ace_traj"]

    # FK references a non-existent instance.
    t = Traj(
        instance_id="missing",
        gold_patch_cov=0.99,
        agent="agent",
        model="model",
        attempt=0,
        extra={},
    )

    with pytest.raises(IntegrityError):
        db.upsert("ace_traj", t)


def test_acebench_yaml_on_delete_restrict_blocks_parent_delete(db: DBManager) -> None:
    Instance = db.models["ace_instance"]
    Traj = db.models["ace_traj"]

    ins = Instance(instance_id="ins_003", gold_patch_cov=0.33, extra={})
    db.add(ins)

    t = Traj(
        instance_id="ins_003",
        gold_patch_cov=0.33,
        agent="agent",
        model="model",
        attempt=0,
        extra={},
    )
    db.upsert("ace_traj", t)

    # Raw delete should fail because FK is RESTRICT.
    with pytest.raises(IntegrityError):
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    f'DELETE FROM "{db.registry.postgres_schema}".ace_instance '
                    'WHERE instance_id=:iid AND gold_patch_cov=:gpc'
                ),
                {"iid": "ins_003", "gpc": 0.33},
            )
