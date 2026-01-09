from __future__ import annotations

from typing import Any

from sqlalchemy import String, cast


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


def build_where(table, where: dict[str, Any], *, allowed_fields: set[str] | None = None) -> list:
    clauses = []
    for field, cond in where.items():
        if not isinstance(cond, dict):
            raise TypeError(f"where['{field}'] must be a dict of ops")

        if field.startswith("extra."):
            key = field.split(".", 1)[1]
            expr = cast(table.c.extra[key].astext, String)

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
