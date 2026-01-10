from __future__ import annotations

from pathlib import Path

import pytest

from agentfabric.artifacts.store import ArtifactStore


def test_put_requires_existing_local_file(tmp_path: Path) -> None:
    store = ArtifactStore(base_url=str(tmp_path / "artifacts"))

    missing = tmp_path / "missing.json"
    with pytest.raises(FileNotFoundError):
        store.put(str(missing), "runs/001/")


def test_put_relative_dir_uses_source_filename(tmp_path: Path) -> None:
    base = tmp_path / "artifacts"
    store = ArtifactStore(base_url=str(base))

    src = tmp_path / "traj.json"
    src.write_text('{"steps": []}\n', encoding="utf-8")

    r = store.put(str(src), "runs/001/")
    assert r.url.endswith("/runs/001/traj.json")

    dst = base / "runs" / "001" / "traj.json"
    assert dst.exists()
    assert dst.read_text(encoding="utf-8").strip() == '{"steps": []}'
    assert isinstance(r.sha256, str) and len(r.sha256) == 64
    assert r.size_bytes is not None and r.size_bytes > 0


def test_put_relative_file_enforces_suffix_match(tmp_path: Path) -> None:
    base = tmp_path / "artifacts"
    store = ArtifactStore(base_url=str(base))

    src = tmp_path / "metric.json"
    src.write_text('{"pass": true}\n', encoding="utf-8")

    ok = store.put(str(src), "runs/001/metric.json")
    assert ok.url.endswith("/runs/001/metric.json")

    with pytest.raises(ValueError, match="extension mismatch"):
        store.put(str(src), "runs/001/metric.txt")


def test_put_dir_with_z_overrides_filename(tmp_path: Path) -> None:
    base = tmp_path / "artifacts"
    store = ArtifactStore(base_url=str(base))

    src = tmp_path / "a.json"
    src.write_text('{"a": 1}\n', encoding="utf-8")

    r = store.put(str(src), "runs/001/", "renamed.json")
    assert r.url.endswith("/runs/001/renamed.json")

    dst = base / "runs" / "001" / "renamed.json"
    assert dst.exists()


def test_put_absolute_file_ignores_z_and_enforces_suffix(tmp_path: Path) -> None:
    store = ArtifactStore(base_url=str(tmp_path / "artifacts"))

    src = tmp_path / "x.json"
    src.write_text('{"x": 1}\n', encoding="utf-8")

    abs_target = tmp_path / "out.json"
    r = store.put(str(src), str(abs_target), "ignored.json")
    assert r.url == str(abs_target)
    assert abs_target.exists()

    with pytest.raises(ValueError, match="extension mismatch"):
        store.put(str(src), str(tmp_path / "out.txt"))


def test_put_relative_file_ignores_z(tmp_path: Path) -> None:
    base = tmp_path / "artifacts"
    store = ArtifactStore(base_url=str(base))

    src = tmp_path / "x.json"
    src.write_text('{"x": 1}\n', encoding="utf-8")

    r = store.put(str(src), "runs/001/out.json", "ignored.json")
    assert r.url.endswith("/runs/001/out.json")
    assert (base / "runs" / "001" / "out.json").exists()


def test_put_dir_without_trailing_slash_is_treated_as_dir_when_no_suffix(tmp_path: Path) -> None:
    base = tmp_path / "artifacts"
    store = ArtifactStore(base_url=str(base))

    src = tmp_path / "a.json"
    src.write_text('{"a": 1}\n', encoding="utf-8")

    r = store.put(str(src), "runs/003")
    assert r.url.endswith("/runs/003/a.json")
    assert (base / "runs" / "003" / "a.json").exists()


def test_put_absolute_dir_without_trailing_slash_and_not_existing(tmp_path: Path) -> None:
    store = ArtifactStore(base_url=str(tmp_path / "artifacts"))

    src = tmp_path / "a.json"
    src.write_text('{"a": 1}\n', encoding="utf-8")

    abs_dir = tmp_path / "abs_dir_no_slash"
    r = store.put(str(src), str(abs_dir), "b.json")
    assert r.url == str(abs_dir / "b.json")
    assert (abs_dir / "b.json").exists()


def test_base_url_file_scheme_and_open_roundtrip(tmp_path: Path) -> None:
    base_dir = tmp_path / "af"
    store = ArtifactStore(base_url=f"file://{base_dir}")

    src = tmp_path / "note.txt"
    src.write_text("hello\n", encoding="utf-8")

    r = store.put(str(src), "runs/010/")
    assert r.url == f"file://{base_dir}/runs/010/note.txt"

    with store.open(r.url, "rb") as f:
        data = f.read()
    assert data == b"hello\n"
