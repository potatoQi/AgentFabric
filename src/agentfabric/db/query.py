from __future__ import annotations

from typing import Any

from sqlalchemy import String, and_, cast, or_


OPS = {
    "eq": lambda col, v: col == v,
    "ne": lambda col, v: col != v,
    "lt": lambda col, v: col < v,
    "lte": lambda col, v: col <= v,
    "gt": lambda col, v: col > v,
    "gte": lambda col, v: col >= v,
    "in_": lambda col, v: col.in_(v),
    "nin": lambda col, v: ~col.in_(v),
    "like": lambda col, v: col.like(v),
}


_EXTRA_ALLOWED_OPS = {"eq", "ne", "in_", "nin", "is_null", "like"}


def _split_extra_path(path: str) -> list[str]:
    """Split an extra.* path into JSON key parts.

    Supports escaping dots with backslash, e.g. "a\\.b.c" -> ["a.b", "c"].
    """

    parts: list[str] = []
    buf: list[str] = []
    escape = False
    for ch in path:
        if escape:
            buf.append(ch)
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == ".":
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)

    if escape:
        # trailing backslash is likely a user mistake
        raise ValueError(f"invalid extra path (trailing escape): {path!r}")

    parts.append("".join(buf))
    if any(p == "" for p in parts):
        raise ValueError(f"invalid extra path (empty segment): {path!r}")
    return parts


def _build_field_clauses(table, where: dict[str, Any], *, allowed_fields: set[str] | None = None) -> list:
    clauses: list[Any] = []
    for field, cond in where.items():
        if field in {"and", "or"}:
            raise ValueError("'and'/'or' are not valid field names")
        if not isinstance(cond, dict):
            raise TypeError(f"where['{field}'] must be a dict of ops")

        # Avoid silent no-ops: users sometimes write {"eq": None} expecting
        # an IS NULL check. Require explicit is_null: true/false.
        for op in ("eq", "ne"):
            if op in cond and cond[op] is None:
                raise ValueError(
                    f"Use 'is_null: True/False' instead of '{op}: None' for NULL checks on field '{field}'"
                )

        if field.startswith("extra."):
            raw = field.split(".", 1)[1]
            path_parts = _split_extra_path(raw)
            expr = table.c.extra
            for p in path_parts:
                expr = expr[p]
            expr = cast(expr.astext, String)

            # MVP constraint: only text-safe ops for extra
            for op in cond.keys():
                if op not in _EXTRA_ALLOWED_OPS:
                    raise ValueError(
                        f"unsupported op for extra key '{field}': {op} (MVP only supports {_EXTRA_ALLOWED_OPS})"
                    )
        else:
            if allowed_fields is not None and field not in allowed_fields:
                raise ValueError(f"field is not filterable: {field}")
            expr = table.c[field]

        if cond.get("is_null") is True:
            clauses.append(expr.is_(None))
        if cond.get("is_null") is False:
            clauses.append(expr.is_not(None))

        for op, fn in OPS.items():
            if op in cond and cond[op] is not None:
                v = cond[op]
                if op in ("in_", "nin") and isinstance(v, list) and len(v) == 0:
                    # in_ [] => empty result set; nin [] => no-op
                    if op == "in_":
                        clauses.append(False)
                    continue
                clauses.append(fn(expr, v))

    return clauses


def build_where(table, where: dict[str, Any], *, allowed_fields: set[str] | None = None) -> list:
    """Build SQLAlchemy WHERE clauses from the AgentFabric filter DSL.

    Supports two shapes:

    1) Field map (legacy):
       {"col": {"eq": 1, "lt": 3}, "extra.tag": {"like": "d%"}}

    2) Boolean composition (new):
       {"and": [ {"col": {"eq": 1}}, {"col": {"gt": 0}}, {"other": {"ne": "x"}} ]}
       {"or":  [ {...}, {...} ]}

    The new form enables multiple independent constraints on the same field.
    """

    if not where:
        return []

    if "and" in where or "or" in where:
        clauses: list[Any] = []

        # Allow mixing a top-level field map with boolean groups.
        field_map = {k: v for k, v in where.items() if k not in {"and", "or"}}
        if field_map:
            clauses.extend(_build_field_clauses(table, field_map, allowed_fields=allowed_fields))

        if "and" in where:
            items = where.get("and")
            if not isinstance(items, list):
                raise TypeError("where['and'] must be a list")
            for item in items:
                if not isinstance(item, dict):
                    raise TypeError("where['and'] items must be dicts")
                clauses.extend(build_where(table, item, allowed_fields=allowed_fields))

        if "or" in where:
            items = where.get("or")
            if not isinstance(items, list):
                raise TypeError("where['or'] must be a list")
            or_parts: list[Any] = []
            for item in items:
                if not isinstance(item, dict):
                    raise TypeError("where['or'] items must be dicts")
                part = build_where(table, item, allowed_fields=allowed_fields)
                if part:
                    or_parts.append(and_(*part))
            if or_parts:
                clauses.append(or_(*or_parts))

        return clauses

    return _build_field_clauses(table, where, allowed_fields=allowed_fields)
