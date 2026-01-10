from __future__ import annotations

import os
from typing import Any

import streamlit as st

from agentfabric.artifacts.store import ArtifactStore


def looks_like_url(v: Any) -> bool:
    if not isinstance(v, str):
        return False
    s = v.strip().lower()
    return s.startswith(("file://", "http://", "https://", "s3://", "gs://", "hf://"))


def candidate_url_fields(row: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for k, v in row.items():
        if k.endswith("_url") and isinstance(v, str) and v.strip():
            out.append(k)
        elif looks_like_url(v):
            out.append(k)
    return sorted(set(out))


def pick_default_url_field(fields: list[str]) -> str:
    priority = [
        "traj_url",
        "patch_url",
        "prd_url",
        "gold_patch_url",
        "test_patch_url",
    ]
    for p in priority:
        if p in fields:
            return p
    return fields[0]


def _preview_max_bytes() -> int | None:
    raw = os.getenv("AGENTFABRIC_UI_PREVIEW_MAX_BYTES")
    if raw is None:
        return 50 * 1024 * 1024
    raw = raw.strip()
    if raw == "" or raw.lower() in {"none", "null"}:
        return 50 * 1024 * 1024
    if raw in {"0", "-1"}:
        return None
    try:
        v = int(raw)
        return None if v <= 0 else v
    except Exception:
        return 50 * 1024 * 1024


@st.cache_data(show_spinner=False)
def open_preview_cached(url: str, artifact_base_url: str | None) -> bytes:
    if artifact_base_url:
        store = ArtifactStore(base_url=artifact_base_url)
        f = store.open(url, "rb")
    else:
        store = ArtifactStore(base_url="")
        f = store.open(url, "rb")

    cap = _preview_max_bytes()
    chunks: list[bytes] = []
    total = 0
    with f:
        while True:
            buf = f.read(1024 * 1024)
            if not buf:
                break
            chunks.append(buf)
            total += len(buf)
            if cap is not None and total >= cap:
                break
    return b"".join(chunks)
