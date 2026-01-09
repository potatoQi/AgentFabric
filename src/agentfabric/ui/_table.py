from __future__ import annotations

import inspect
from typing import Any, Iterable

import pandas as pd
import streamlit as st


def pk_key(pk_cols: Iterable[str], row: dict[str, Any]) -> str:
    parts = []
    for c in pk_cols:
        parts.append(f"{c}={row.get(c)!r}")
    return ", ".join(parts)


def dataframe_with_selection(
    rows: list[dict[str, Any]], *, key: str, selection_mode: str = "single-row"
) -> tuple[pd.DataFrame, list[int]]:
    df = pd.DataFrame(rows)

    kwargs: dict[str, Any] = {}
    try:
        params = inspect.signature(st.dataframe).parameters
        if "width" in params:
            kwargs["width"] = "stretch"
        elif "use_container_width" in params:
            kwargs["use_container_width"] = True
    except Exception:
        pass

    event = st.dataframe(
        df,
        hide_index=True,
        on_select="rerun",
        selection_mode=selection_mode,
        key=key,
        **kwargs,
    )

    indices: list[int] = []
    try:
        indices = list(getattr(getattr(event, "selection", None), "rows", []) or [])
    except Exception:
        indices = []

    return df, indices
