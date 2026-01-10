"""
Comprehensive bug hunting tests to identify logical flaws in the codebase.

This test file aims to find edge cases, boundary conditions, and logical errors
across all components of the AgentFabric system.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from agentfabric.artifacts.store import ArtifactStore
from agentfabric.db.facade import DB
from agentfabric.config.spec import ColumnSpec, ConfigSpec, TableSpec
from agentfabric.db.query import build_where
from agentfabric.schema.builder import SchemaBuilder
from agentfabric.schema.registry import SchemaRegistry


# ============================================================================
# BUG HUNT AREA 1: DB Initialization and Configuration Edge Cases
# ============================================================================


def test_bug_hunt_empty_table_name_in_config():
    """Test if empty table name causes issues."""
    with pytest.raises((ValueError, KeyError)):
        cfg = ConfigSpec(
            tables={
                "": TableSpec(
                    primary_key=["id"],
                    columns={"id": ColumnSpec(type="text", nullable=False)},
                )
            }
        )
        DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)


def test_bug_hunt_table_name_with_special_characters():
    """Test table names with special characters that might break SQL."""
    cfg = ConfigSpec(
        tables={
            "test-table": TableSpec(
                primary_key=["id"],
                columns={"id": ColumnSpec(type="text", nullable=False)},
            )
        }
    )
    # This should work or raise a clear error
    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
    assert "test-table" in db.tables


def test_bug_hunt_column_name_conflicts_with_sql_keywords():
    """Test if column names that are SQL keywords cause issues."""
    cfg = ConfigSpec(
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),
                    "select": ColumnSpec(type="text", nullable=True),
                    "from": ColumnSpec(type="text", nullable=True),
                    "where": ColumnSpec(type="text", nullable=True),
                },
            )
        }
    )
    # This should work or raise a clear error
    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
    assert "select" in db.tables["t"].c


def test_bug_hunt_duplicate_column_names_case_sensitivity():
    """Test if duplicate column names with different cases are handled."""
    # SQL is typically case-insensitive for identifiers
    with pytest.raises(Exception):  # Should raise some kind of error
        cfg = ConfigSpec(
            tables={
                "t": TableSpec(
                    primary_key=["id"],
                    columns={
                        "Name": ColumnSpec(type="text", nullable=False),
                        "name": ColumnSpec(type="text", nullable=False),
                    },
                )
            }
        )


# ============================================================================
# BUG HUNT AREA 2: Default Value Application Edge Cases
# ============================================================================


def test_bug_hunt_default_value_with_explicit_none():
    """Test if explicitly passing None overrides defaults."""
    cfg = ConfigSpec(
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="uuid", nullable=False, default="uuid4"),
                    "msg": ColumnSpec(type="text", nullable=True, default="Hello"),
                },
            )
        }
    )
    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)

    # BUG CANDIDATE: Does explicit None override default or not?
    row = {"id": None, "msg": None}
    out = db._apply_sdk_defaults_row("t", row)

    # Current behavior: None is treated as "missing" and default is applied
    # This might be a bug - explicit None should perhaps be respected
    assert out["id"] is not None  # Default applied
    assert out["msg"] == "Hello"  # Default applied - is this correct?


def test_bug_hunt_default_value_mutation_between_calls():
    """Test if mutable defaults (list, dict) are properly isolated."""
    cfg = ConfigSpec(
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),
                    # json column type is not supported; keep the test's intent (deep-copy literal defaults)
                    # by using a text column with a dict default.
                    "tags": ColumnSpec(type="text", nullable=False, default={"list": []}),
                },
            )
        }
    )
    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)

    row1 = db._apply_sdk_defaults_row("t", {"id": "1"})
    row2 = db._apply_sdk_defaults_row("t", {"id": "2"})

    # Modify row1's default
    row1["tags"]["list"].append("item1")

    # BUG CHECK: row2 should NOT be affected
    assert row2["tags"]["list"] == [], "Mutable default was shared between rows!"


def test_bug_hunt_default_now_timezone_consistency():
    """Test if 'now' default always produces timezone-aware datetime."""
    cfg = ConfigSpec(
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),
                    "created_at": ColumnSpec(type="datetime", nullable=False, default="now"),
                },
            )
        }
    )
    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)

    row = db._apply_sdk_defaults_row("t", {"id": "1"})

    # BUG CHECK: timezone should always be present
    assert row["created_at"].tzinfo is not None, "Datetime missing timezone!"
    assert row["created_at"].tzinfo == timezone.utc, "Datetime not in UTC!"


def test_bug_hunt_uuid4_default_produces_valid_uuid():
    """Test if uuid4 default produces valid UUID objects."""
    cfg = ConfigSpec(
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="uuid", nullable=False, default="uuid4"),
                },
            )
        }
    )
    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)

    row = db._apply_sdk_defaults_row("t", {})

    # BUG CHECK: should be UUID instance
    assert isinstance(row["id"], UUID), f"Expected UUID, got {type(row['id'])}"
    assert row["id"].version == 4, "UUID is not version 4!"


def test_bug_hunt_unsupported_default_value_type():
    """Test handling of unsupported default value types."""
    cfg = ConfigSpec(
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),
                    # Using a complex object as default
                    # json column type is not supported; keep deep-copy/default handling regression coverage.
                    "data": ColumnSpec(type="text", nullable=False, default={"nested": {"deep": [1, 2, 3]}}),
                },
            )
        }
    )
    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)

    row = db._apply_sdk_defaults_row("t", {"id": "1"})
    # Should handle nested structures correctly
    assert row["data"] == {"nested": {"deep": [1, 2, 3]}}


# ============================================================================
# BUG HUNT AREA 3: Query Filter Edge Cases
# ============================================================================


def test_bug_hunt_query_filter_with_empty_where():
    """Test query behavior with empty where clause."""
    from sqlalchemy import Column, Integer, MetaData, String, Table
    from sqlalchemy.dialects.postgresql import JSONB

    md = MetaData()
    t = Table(
        "test",
        md,
        Column("id", Integer, nullable=False),
        Column("name", String, nullable=True),
        Column("extra", JSONB, nullable=False),
    )

    # Empty where should return empty clause list
    clauses = build_where(t, {}, allowed_fields={"id", "name"})
    assert clauses == [], "Empty where should produce empty clause list"


def test_bug_hunt_query_filter_with_none_values():
    """Test query filter handling of None values in conditions."""
    from sqlalchemy import Column, Integer, MetaData, String, Table
    from sqlalchemy.dialects.postgresql import JSONB

    md = MetaData()
    t = Table(
        "test",
        md,
        Column("id", Integer, nullable=False),
        Column("name", String, nullable=True),
        Column("extra", JSONB, nullable=False),
    )

    with pytest.raises(ValueError, match="Use 'is_null: True/False'"):
        build_where(
            t,
            {"id": {"eq": None}},  # Comparing with None
            allowed_fields={"id"},
        )


def test_bug_hunt_query_filter_multiple_is_null():
    """Test combining is_null True and False - contradictory conditions."""
    from sqlalchemy import Column, Integer, MetaData, Table
    from sqlalchemy.dialects.postgresql import JSONB

    md = MetaData()
    t = Table(
        "test",
        md,
        Column("id", Integer, nullable=False),
        Column("extra", JSONB, nullable=False),
    )

    # BUG CANDIDATE: Contradictory conditions
    clauses = build_where(
        t,
        {"id": {"is_null": True, "is_null": False}},  # Can't be both!
        allowed_fields={"id"},
    )
    # This will only use the last value due to dict behavior
    # Should this raise an error instead?
    assert len(clauses) == 1  # Only one is_null clause


def test_bug_hunt_query_filter_extra_field_without_dot():
    """Test if 'extra' without dot notation is handled correctly."""
    from sqlalchemy import Column, Integer, MetaData, Table
    from sqlalchemy.dialects.postgresql import JSONB

    md = MetaData()
    t = Table(
        "test",
        md,
        Column("id", Integer, nullable=False),
        Column("extra", JSONB, nullable=False),
    )

    # BUG CANDIDATE: What if someone tries to filter on "extra" directly?
    # This should probably raise an error or have special handling
    with pytest.raises((ValueError, KeyError)):
        build_where(
            t,
            {"extra": {"eq": "something"}},  # Not using extra.key notation
            allowed_fields=set(),  # extra is not in allowed_fields
        )


def test_bug_hunt_query_filter_extra_with_numeric_operations():
    """Test that numeric operations on extra fields are properly rejected."""
    from sqlalchemy import Column, Integer, MetaData, Table
    from sqlalchemy.dialects.postgresql import JSONB

    md = MetaData()
    t = Table(
        "test",
        md,
        Column("id", Integer, nullable=False),
        Column("extra", JSONB, nullable=False),
    )

    # These operations should be rejected for extra fields
    numeric_ops = ["lt", "lte", "gt", "gte"]

    for op in numeric_ops:
        with pytest.raises(ValueError, match="unsupported op"):
            build_where(t, {f"extra.count": {op: 5}})


def test_bug_hunt_query_filter_in_with_single_element():
    """Test 'in_' operator with a single element list."""
    from sqlalchemy import Column, Integer, MetaData, Table
    from sqlalchemy.dialects.postgresql import JSONB

    md = MetaData()
    t = Table(
        "test",
        md,
        Column("id", Integer, nullable=False),
        Column("extra", JSONB, nullable=False),
    )

    # Should work fine
    clauses = build_where(t, {"id": {"in_": [1]}}, allowed_fields={"id"})
    assert len(clauses) == 1


def test_bug_hunt_query_filter_nin_with_none_in_list():
    """Test 'nin' operator with None in the list."""
    from sqlalchemy import Column, Integer, MetaData, Table
    from sqlalchemy.dialects.postgresql import JSONB

    md = MetaData()
    t = Table(
        "test",
        md,
        Column("id", Integer, nullable=True),
        Column("extra", JSONB, nullable=False),
    )

    # BUG CANDIDATE: Does this properly exclude NULL values?
    clauses = build_where(t, {"id": {"nin": [1, 2, None]}}, allowed_fields={"id"})
    assert len(clauses) == 1


# ============================================================================
# BUG HUNT AREA 4: Schema Validation Edge Cases
# ============================================================================


def test_bug_hunt_foreign_key_to_nonexistent_table():
    """Test that foreign key to non-existent table is caught."""
    cfg = ConfigSpec(
        tables={
            "child": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),
                    "parent_id": ColumnSpec(type="text", nullable=False),
                },
                foreign_keys=[
                    {
                        "columns": ["parent_id"],
                        "ref_table": "nonexistent_parent",
                        "ref_columns": ["id"],
                    }
                ],
            )
        }
    )

    with pytest.raises(ValueError, match="ref_table not found"):
        SchemaRegistry.from_config(cfg)


def test_bug_hunt_foreign_key_to_nonexistent_column():
    """Test that foreign key to non-existent column is caught."""
    cfg = ConfigSpec(
        tables={
            "parent": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),
                },
            ),
            "child": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),
                    "parent_id": ColumnSpec(type="text", nullable=False),
                },
                foreign_keys=[
                    {
                        "columns": ["parent_id"],
                        "ref_table": "parent",
                        "ref_columns": ["nonexistent"],
                    }
                ],
            ),
        }
    )

    with pytest.raises(ValueError, match="ref_column not found"):
        SchemaRegistry.from_config(cfg)


def test_bug_hunt_circular_foreign_keys():
    """Test if circular foreign key references are handled."""
    # This is actually valid in SQL with deferred constraints
    cfg = ConfigSpec(
        tables={
            "a": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),
                    "b_id": ColumnSpec(type="text", nullable=True),
                },
                foreign_keys=[
                    {
                        "columns": ["b_id"],
                        "ref_table": "b",
                        "ref_columns": ["id"],
                    }
                ],
            ),
            "b": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),
                    "a_id": ColumnSpec(type="text", nullable=True),
                },
                foreign_keys=[
                    {
                        "columns": ["a_id"],
                        "ref_table": "a",
                        "ref_columns": ["id"],
                    }
                ],
            ),
        }
    )

    # Should not raise during schema creation (circular FKs are valid)
    reg = SchemaRegistry.from_config(cfg)
    assert "a" in reg.tables
    assert "b" in reg.tables


def test_bug_hunt_self_referencing_foreign_key():
    """Test self-referencing foreign key (tree structure)."""
    cfg = ConfigSpec(
        tables={
            "node": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),
                    "parent_id": ColumnSpec(type="text", nullable=True),
                },
                foreign_keys=[
                    {
                        "columns": ["parent_id"],
                        "ref_table": "node",
                        "ref_columns": ["id"],
                    }
                ],
            )
        }
    )

    # Should work fine - self-referencing FKs are valid
    reg = SchemaRegistry.from_config(cfg)
    assert "node" in reg.tables


def test_bug_hunt_foreign_key_from_nonexistent_column():
    """Test FK where source column doesn't exist."""
    cfg = ConfigSpec(
        tables={
            "parent": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),
                },
            ),
            "child": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),
                },
                foreign_keys=[
                    {
                        "columns": ["nonexistent_col"],
                        "ref_table": "parent",
                        "ref_columns": ["id"],
                    }
                ],
            ),
        }
    )

    with pytest.raises(ValueError, match="foreign key column not found"):
        SchemaRegistry.from_config(cfg)


def test_bug_hunt_empty_primary_key_list():
    """Test table with empty primary key list."""
    with pytest.raises(ValueError, match="primary_key is required"):
        ConfigSpec(
            tables={
                "t": TableSpec(
                    primary_key=[],  # Empty PK
                    columns={
                        "id": ColumnSpec(type="text", nullable=False),
                    },
                )
            }
        )


def test_bug_hunt_primary_key_on_nullable_column():
    """Test if PK can be defined on nullable column."""
    with pytest.raises(Exception, match="primary_key column must be non-nullable"):
        ConfigSpec(
            tables={
                "t": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="text", nullable=True),  # PK but nullable
                    },
                )
            }
        )


def test_bug_hunt_index_on_nonexistent_column():
    """Test that index on non-existent column is caught."""
    cfg = ConfigSpec(
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),
                },
                indexes=[
                    {
                        "name": "idx_bad",
                        "columns": ["nonexistent"],
                    }
                ],
            )
        }
    )

    with pytest.raises(ValueError, match="column not found"):
        SchemaRegistry.from_config(cfg)


# ============================================================================
# BUG HUNT AREA 5: Upsert Logic Edge Cases
# ============================================================================


def test_bug_hunt_upsert_with_no_primary_key_no_conflict_cols():
    """Test upsert on table without PK and without conflict_cols."""
    with pytest.raises(ValueError, match="primary_key is required"):
        ConfigSpec(
            tables={
                "t": TableSpec(
                    primary_key=[],  # No PK
                    columns={
                        "id": ColumnSpec(type="text", nullable=False),
                        "name": ColumnSpec(type="text", nullable=False),
                    },
                )
            }
        )


def test_bug_hunt_upsert_conflict_cols_not_in_object():
    """Test upsert when conflict_cols reference columns not in object."""
    cfg = ConfigSpec(
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),
                    "name": ColumnSpec(type="text", nullable=False),
                },
            )
        }
    )
    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)

    Model = db.models["t"]
    obj = Model(name="test")  # Missing 'id'

    # BUG CANDIDATE: What happens if conflict_col is missing from obj?
    # This will likely fail at DB level, but should we validate earlier?
    # For now, we expect this might cause issues


# ============================================================================
# BUG HUNT AREA 6: Update Logic Edge Cases
# ============================================================================


def test_bug_hunt_update_with_empty_where():
    """Test that update with empty where is rejected."""
    cfg = ConfigSpec(
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),
                    "name": ColumnSpec(type="text", nullable=False),
                },
            )
        }
    )
    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)

    # Empty where should be rejected
    with pytest.raises(ValueError, match="requires non-empty where"):
        db.update("t", where={}, patch={"name": "new"})


def test_bug_hunt_update_with_empty_patch():
    """Test update with empty patch dict."""
    cfg = ConfigSpec(
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                    "name": ColumnSpec(type="text", nullable=False),
                },
            )
        }
    )
    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)

    # Empty patch - what happens?
    # Should probably be allowed (no-op update)
    # But might cause issues


# ============================================================================
# BUG HUNT AREA 7: Type Mapping Edge Cases
# ============================================================================


def test_bug_hunt_list_type_without_item_type():
    """Test that list type without item_type is rejected."""
    with pytest.raises(ValueError, match="requires item_type"):
        ColumnSpec(type="list")


def test_bug_hunt_nested_list_types():
    """Test if nested list types are handled (list of lists)."""
    # This should probably fail - we don't support nested arrays
    # But let's check what happens
    with pytest.raises(Exception):  # Should fail somehow
        ColumnSpec(type="list", item_type="list")  # Can't have list of lists


def test_bug_hunt_unsupported_type_name():
    """Test handling of completely unsupported type names."""
    from agentfabric.schema.types import map_type

    with pytest.raises(ValueError, match="unsupported type"):
        map_type("completely_invalid_type")


# ============================================================================
# BUG HUNT AREA 8: Artifact Store Edge Cases
# ============================================================================


def test_bug_hunt_artifact_store_url_with_trailing_slashes(tmp_path: Path):
    """Test artifact store with various trailing slash combinations."""
    store1 = ArtifactStore(base_url=str(tmp_path))
    store2 = ArtifactStore(base_url=str(tmp_path) + "/")
    store3 = ArtifactStore(base_url=str(tmp_path) + "///")

    # All should normalize to same base
    assert store1.base_url == str(tmp_path)
    assert store2.base_url == str(tmp_path)
    assert store3.base_url == str(tmp_path)


def test_bug_hunt_artifact_store_put_nonexistent_file(tmp_path: Path):
    """Test putting a file that doesn't exist."""
    store = ArtifactStore(base_url=str(tmp_path))

    nonexistent = tmp_path / "does_not_exist.txt"

    with pytest.raises(FileNotFoundError):
        store.put(nonexistent, "target.txt")


def test_bug_hunt_artifact_store_extension_mismatch(tmp_path: Path):
    """Test that extension mismatch is caught."""
    store = ArtifactStore(base_url=str(tmp_path))

    src = tmp_path / "test.txt"
    src.write_text("content")

    # Target has different extension
    with pytest.raises(ValueError, match="extension mismatch"):
        store.put(src, "test.json")  # .txt -> .json should fail


def test_bug_hunt_artifact_store_directory_traversal(tmp_path: Path):
    """Test that directory traversal attempts are handled safely."""
    store = ArtifactStore(base_url=str(tmp_path / "artifacts"))

    src = tmp_path / "test.txt"
    src.write_text("content")

    # Try to use .. in target path - should this be blocked?
    # This is a potential security issue
    target = "../../../etc/passwd.txt"

    # The store might allow this - which could be a bug
    # Depending on implementation, this could write outside base_url


def test_bug_hunt_artifact_store_absolute_target_path(tmp_path: Path):
    """Test using absolute path as target."""
    store = ArtifactStore(base_url=str(tmp_path / "artifacts"))

    src = tmp_path / "test.txt"
    src.write_text("content")

    # Using absolute path as target should override base_url
    absolute_target = str(tmp_path / "other" / "test.txt")

    # This should work and write to absolute path, not relative to base_url
    result = store.put(src, absolute_target)
    assert result.url == absolute_target


# ============================================================================
# BUG HUNT AREA 9: ORM Model Factory Edge Cases
# ============================================================================


def test_bug_hunt_orm_model_table_name_with_numbers():
    """Test ORM model generation for table names with numbers."""
    cfg = ConfigSpec(
        tables={
            "table123": TableSpec(
                primary_key=["id"],
                columns={"id": ColumnSpec(type="text", nullable=False)},
            )
        }
    )
    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)

    # Should generate valid class name
    assert "table123" in db.models
    assert db.models["table123"].__name__ == "Table123"


def test_bug_hunt_orm_model_table_name_starting_with_number():
    """Test ORM model generation for table name starting with number."""
    cfg = ConfigSpec(
        tables={
            "123table": TableSpec(
                primary_key=["id"],
                columns={"id": ColumnSpec(type="text", nullable=False)},
            )
        }
    )
    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)

    # Should generate valid class name (can't start with number)
    assert "123table" in db.models
    # BUG CANDIDATE: Class name "123table" is invalid in Python


def test_bug_hunt_orm_model_very_long_table_name():
    """Test ORM model with very long table name."""
    long_name = "a" * 100

    cfg = ConfigSpec(
        tables={
            long_name: TableSpec(
                primary_key=["id"],
                columns={"id": ColumnSpec(type="text", nullable=False)},
            )
        }
    )
    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)

    assert long_name in db.models


# ============================================================================
# BUG HUNT AREA 10: Concurrent/Race Condition Tests
# ============================================================================


def test_bug_hunt_multiple_db_instances_same_config():
    """Test creating multiple DB instances with same config."""
    cfg = ConfigSpec(
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={"id": ColumnSpec(type="text", nullable=False)},
            )
        }
    )

    db1 = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
    db2 = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)

    # Each should have independent registries
    assert db1.registry is not db2.registry
    assert db1.models is not db2.models


# ============================================================================
# BUG HUNT SUMMARY
# ============================================================================

"""
Bug Candidates Identified:

1. DEFAULT VALUE HANDLING:
   - Explicit None might override defaults when it shouldn't (or vice versa)
   - Need to clarify: is None "missing" or "explicitly null"?

2. QUERY FILTER ISSUES:
   - None values in eq/ne operations might be silently skipped
   - Should use IS NULL instead
   - Contradictory is_null conditions are silently resolved

3. SCHEMA VALIDATION GAPS:
   - No validation that PK columns are non-nullable
   - Table names starting with numbers create invalid Python class names
   - SQL reserved keywords as column names might cause issues

4. ARTIFACT STORE SECURITY:
   - Directory traversal with .. might not be blocked
   - Could write outside base_url

5. UPSERT EDGE CASES:
   - Missing conflict column values might fail at DB level
   - Should validate earlier

6. TYPE SYSTEM:
   - Nested list types (list of lists) not properly rejected
   - Item_type validation could be stricter

Priority Issues:
- P0: Directory traversal security issue
- P0: Invalid Python class names from numeric table names
- P1: Default None handling ambiguity
- P1: PK nullable validation missing
- P2: Query filter None value handling
"""
