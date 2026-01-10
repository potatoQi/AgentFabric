import pytest

from agentfabric.db.query import OPS as DB_OPS
from agentfabric.ui._filters import infer_ops, parse_value, value_placeholder


@pytest.mark.parametrize(
    "type_name",
    ["int", "float", "bool", "datetime", "text", "str", "list"],
)
def test_infer_ops_are_supported_by_backend(type_name: str) -> None:
    # UI should only offer ops that the backend understands.
    ui_ops = set(infer_ops(type_name))

    # Backend supports OPS keys plus explicit NULL checks.
    allowed = set(DB_OPS.keys()) | {"is_null", "not_null"}

    assert ui_ops.issubset(allowed), (type_name, sorted(ui_ops - allowed))


def test_uuid_ops_are_restricted() -> None:
    # UUID should not offer text-only ops like `like`.
    assert set(infer_ops("uuid")) == {"eq", "ne", "in_", "nin", "is_null", "not_null"}


def test_uuid_parse_strict() -> None:
    from uuid import UUID

    v = parse_value("eq", "550e8400-e29b-41d4-a716-446655440000", "uuid", None)
    assert isinstance(v, UUID)
    with pytest.raises(ValueError):
        parse_value("eq", "not-a-uuid", "uuid", None)


@pytest.mark.parametrize(
    "type_name,item_type",
    [
        ("int", None),
        ("float", None),
        ("bool", None),
        ("datetime", None),
        ("text", None),
        ("str", None),
        ("list", "int"),
        ("list", "float"),
        ("list", "bool"),
        ("list", "text"),
    ],
)
def test_placeholder_non_empty_for_value_ops(type_name: str, item_type: str | None) -> None:
    # For ops that require a value, placeholder should guide the user.
    for op in infer_ops(type_name):
        ph = value_placeholder(op, type_name, item_type)
        if op in {"is_null", "not_null"}:
            assert ph == ""
        else:
            assert isinstance(ph, str) and ph.strip(), (type_name, op, ph)


def test_datetime_parse_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_value("eq", "90", "datetime", None)


@pytest.mark.parametrize(
    "raw",
    [
        "2025-01-10",
        "2025-01-10/12-30-00",
        "2025-01-10T12:30:00",
        "2025-01-10T12:30:00Z",
        "2025-01-10T12:30:00+00:00",
    ],
)
def test_datetime_parse_accepts_common_formats(raw: str) -> None:
    v = parse_value("eq", raw, "datetime", None)
    # parse_value returns a datetime for datetime columns
    import datetime as _dt

    assert isinstance(v, _dt.datetime)


@pytest.mark.parametrize(
    "type_name,raw,expected",
    [
        ("int", " 123 ", 123),
        ("float", " 3.14 ", 3.14),
        ("bool", "true", True),
        ("bool", "0", False),
    ],
)
def test_scalar_parsing_and_strip(type_name: str, raw: str, expected) -> None:
    assert parse_value("eq", raw.strip(), type_name, None) == expected


def test_in_list_parsing_for_scalars() -> None:
    assert parse_value("in_", "1,2,3", "int", None) == [1, 2, 3]
    assert parse_value("nin", "true,false", "bool", None) == [True, False]


def test_list_type_parses_csv_items() -> None:
    # list columns are parsed as CSV of item_type
    assert parse_value("eq", "1,2,3", "list", "int") == [1, 2, 3]
    assert parse_value("ne", "true,false", "list", "bool") == [True, False]
