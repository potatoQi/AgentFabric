from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

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


@pytest.fixture(scope="module")
def schema_name() -> str:
    return f"af_combo_{uuid.uuid4().hex[:10]}"


@pytest.fixture(scope="module")
def artifact_base_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("combo_artifacts")


@pytest.fixture(scope="module")
def db(db_url: str, schema_name: str) -> DB:
    cfg = ConfigSpec(
        postgres_schema=schema_name,
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                    "n": ColumnSpec(type="int", nullable=False, filterable=True),
                    "patch_url": ColumnSpec(type="text", nullable=True, filterable=True),
                    "tags": ColumnSpec(type="list", item_type="text", nullable=True, filterable=True),
                    "created_at": ColumnSpec(type="datetime", nullable=False, default="now", filterable=True),
                    "msg": ColumnSpec(type="text", nullable=False, default="Hello", filterable=False),
                },
            )
        },
    )

    db = DB(url=db_url, config=cfg)
    with db.engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))
    db.init_schema()

    yield db

    with db.engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))


def test_combo_put_suffix_mismatch_raises(artifact_base_dir: Path, tmp_path: Path) -> None:
    store = ArtifactStore(base_url=f"file://{artifact_base_dir}")

    local_patch = tmp_path / "patch.diff"
    local_patch.write_text("diff --git a/a.py b/a.py\n...\n", encoding="utf-8")

    with pytest.raises(ValueError, match="suffix"):
        store.put(str(local_patch), "runs/001/patch.txt")


def test_combo_end_to_end_store_put_db_upsert_open(db: DB, artifact_base_dir: Path, tmp_path: Path) -> None:
    store = ArtifactStore(base_url=f"file://{artifact_base_dir}")

    local_patch = tmp_path / "patch.diff"
    payload = "diff --git a/a.py b/a.py\n+print('hello')\n"
    local_patch.write_text(payload, encoding="utf-8")

    put_res = store.put(str(local_patch), "runs/001/patch.diff")

    T = db.models["t"]
    row = T(id="r1", n=1, patch_url=put_res.url, tags=["a", "b"], extra={"kind": "e2e"})
    db.upsert("t", row)

    got = db.query("t", {"where": {"id": {"eq": "r1"}}, "limit": 1})
    assert len(got) == 1
    assert got[0].msg == "Hello"
    assert got[0].created_at is not None
    assert got[0].tags == ["a", "b"]

    with store.open(got[0].patch_url, "rb") as f:
        out = f.read()
    assert out.decode("utf-8") == payload


def test_combo_query_limit_offset_edges(db: DB) -> None:
    T = db.models["t"]

    db.add_all([T(id=f"lim{i}", n=i, extra={"kind": "limit"}) for i in range(5)])

    zero = db.query("t", {"where": {"extra.kind": {"eq": "limit"}}, "limit": 0})
    assert zero == []

    too_far = db.query("t", {"where": {"extra.kind": {"eq": "limit"}}, "offset": 999, "limit": 10})
    assert too_far == []

    two = db.query("t", {"where": {"extra.kind": {"eq": "limit"}}, "limit": 2, "offset": 0})
    assert len(two) == 2


def test_combo_filters_and_parameter_combinations(db: DB, artifact_base_dir: Path, tmp_path: Path) -> None:
    store = ArtifactStore(base_url=f"file://{artifact_base_dir}")
    T = db.models["t"]

    # Prepare two artifacts and rows with varying numeric values and extra tags.
    p1 = tmp_path / "a.diff"
    p2 = tmp_path / "b.diff"
    p1.write_text("diff --git a/x b/x\n", encoding="utf-8")
    p2.write_text("diff --git a/y b/y\n", encoding="utf-8")

    u1 = store.put(str(p1), "runs/c/one.diff").url
    u2 = store.put(str(p2), "runs/c/two.diff").url

    db.add_all(
        [
            T(id="c1", n=10, patch_url=u1, tags=["x"], extra={"tag": "x-ray"}),
            T(id="c2", n=11, patch_url=u2, tags=["x", "y"], extra={"tag": "xenon"}),
            T(id="c3", n=12, patch_url=None, tags=None, extra={"tag": "other"}),
        ]
    )

    out = db.query(
        "t",
        {
            "where": {
                "n": {"gte": 10, "lt": 13, "ne": 12},
                "patch_url": {"like": "file://%"},
                "extra.tag": {"like": "x%"},
                "id": {"in_": ["c1", "c2", "c3"]},
            },
            "limit": 100,
        },
    )

    assert {r.id for r in out} == {"c1", "c2"}

    # list[text] roundtrip + equality filtering on ARRAY
    out2 = db.query("t", {"where": {"tags": {"eq": ["x", "y"]}}, "limit": 10})
    assert len(out2) == 1
    assert out2[0].id == "c2"

    # in_: [] should produce empty result, nin: [] should be a no-op
    empty = db.query("t", {"where": {"id": {"in_": []}}})
    assert empty == []

    all_rows = db.query("t", {"where": {"id": {"nin": []}}, "limit": 1000})
    assert len(all_rows) >= 3


def test_combo_stress_bulk_files_and_rows(db: DB, artifact_base_dir: Path, tmp_path: Path) -> None:
    store = ArtifactStore(base_url=f"file://{artifact_base_dir}")
    T = db.models["t"]

    rows = []
    for i in range(200):
        local = tmp_path / f"bulk_{i}.diff"
        local.write_bytes((b"diff --git a/a b/a\n" + str(i).encode("utf-8") + b"\n") * 5)

        url = store.put(str(local), "runs/bulk/").url
        rows.append(T(id=f"b{i}", n=i, patch_url=url, tags=["bulk"], extra={"kind": "bulk", "i": i}))

    db.add_all(rows)

    out = db.query("t", {"where": {"extra.kind": {"eq": "bulk"}}, "limit": 1000})
    assert len(out) == 200

    # Sample-read a few artifacts back.
    for r in out[:5]:
        with store.open(r.patch_url, "rb") as f:
            b = f.read()
        assert b.startswith(b"diff --git")
