"""
Critical Bug Discovery Tests

This test file contains targeted tests designed to expose logical vulnerabilities
in the AgentFabric codebase. Each test is designed to find a specific type of bug.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from agentfabric import DB, ArtifactStore
from agentfabric.config.spec import ColumnSpec, ConfigSpec, TableSpec
from agentfabric.db.query import build_where


# ============================================================================
# BUG CATEGORY 1: Upsert Logic - Missing Conflict Column Validation
# ============================================================================


def test_bug_upsert_missing_conflict_column_value():
    """
    BUG: Upsert with missing conflict column value causes database error.
    
    When conflict_cols is specified but the object doesn't contain values for
    those columns, the operation will fail at the database level instead of
    being caught early with a clear error message.
    
    Expected: Should raise ValueError with clear message
    Actual: Database-level error or undefined behavior
    """
    cfg = ConfigSpec(
        tables={
            "users": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),
                    "email": ColumnSpec(type="text", nullable=False),
                    "name": ColumnSpec(type="text", nullable=True),
                },
            )
        }
    )
    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)

    User = db.models["users"]
    
    # Create object without 'email' which is specified in conflict_cols
    user = User(id="1", name="Test User")
    
    # This should validate that 'email' is present before attempting upsert
    # Currently it will fail at DB level
    with pytest.raises(Exception):  # Should be ValueError with clear message
        db.upsert("users", user, conflict_cols=["email"])


# ============================================================================
# BUG CATEGORY 2: Query Filter - eq: None vs is_null Ambiguity
# ============================================================================


def test_bug_query_filter_eq_none_silently_ignored():
    """
    BUG FIXED: Using eq: None in query filter now raises clear error.
    
    Previously: {"field": {"eq": None}} was silently ignored
    Now: Raises ValueError directing user to use is_null instead
    
    Expected: Should raise ValueError with clear message
    Actual: Raises ValueError (FIXED!)
    """
    from sqlalchemy import Column, Integer, MetaData, Table
    from sqlalchemy.dialects.postgresql import JSONB

    md = MetaData()
    t = Table(
        "test",
        md,
        Column("id", Integer, nullable=True),
        Column("extra", JSONB, nullable=False),
    )

    # eq: None should now raise an error
    with pytest.raises(ValueError, match="Use 'is_null: True/False' instead"):
        build_where(t, {"id": {"eq": None}}, allowed_fields={"id"})
    
    # is_null: True - this is the correct way
    clauses2 = build_where(t, {"id": {"is_null": True}}, allowed_fields={"id"})
    assert len(clauses2) == 1, "is_null: True works correctly"


# ============================================================================
# BUG CATEGORY 3: Default Value Application - Explicit None Ambiguity
# ============================================================================


def test_bug_explicit_none_treated_as_missing():
    """
    BUG FIXED: Explicit None now respected as NULL intent in dict-based rows.
    
    Previously: Explicit None was treated same as missing value
    Now: Explicit None in dict keeps None (respects NULL intent)
    
    Note: For ORM objects, this distinction is harder because Python
    object attributes initialized to None look the same as unset.
    """
    cfg = ConfigSpec(
        tables={
            "items": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="uuid", nullable=False, default="uuid4"),
                    "name": ColumnSpec(type="text", nullable=True, default="DefaultName"),
                    "status": ColumnSpec(type="text", nullable=True, default="active"),
                },
            )
        }
    )
    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)

    # Case 1: Missing fields - defaults should apply
    row1 = db._apply_sdk_defaults_row("items", {})
    assert row1["name"] == "DefaultName"
    assert row1["status"] == "active"
    
    # Case 2: Explicit None - should now respect NULL (FIXED!)
    row2 = db._apply_sdk_defaults_row("items", {"name": None, "status": None})
    
    # FIXED: Explicit None is now preserved
    assert row2["name"] is None, "Explicit None should be preserved"
    assert row2["status"] is None, "Explicit None should be preserved"


# ============================================================================
# BUG CATEGORY 4: Update Operation - Empty Patch Allowed
# ============================================================================


def test_bug_update_with_empty_patch_allowed():
    """
    BUG: Update with empty patch dictionary is allowed.
    
    An update operation with an empty patch will execute but do nothing.
    This could indicate a logic error in calling code that should be caught.
    
    Expected: Should raise ValueError for empty patch
    Actual: Executes successfully (no-op)
    """
    cfg = ConfigSpec(
        tables={
            "items": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                    "name": ColumnSpec(type="text", nullable=False),
                },
            )
        }
    )
    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)

    # Empty patch - should this be allowed?
    # It's not necessarily wrong, but could indicate a bug in calling code
    # The operation would succeed but do nothing
    
    # This test documents the behavior - it's allowed but questionable
    # Consider if this should raise ValueError("update requires non-empty patch")


# ============================================================================
# BUG CATEGORY 5: Query Filter - Negative Limit/Offset Not Validated
# ============================================================================


def test_bug_negative_limit_offset_not_validated():
    """
    BUG: Negative limit and offset values are not validated.
    
    The query method converts limit/offset to int but doesn't validate
    that they are non-negative. This could cause unexpected behavior.
    
    Expected: Should raise ValueError for negative values
    Actual: Values are passed to SQLAlchemy (behavior undefined)
    """
    cfg = ConfigSpec(
        tables={
            "items": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                },
            )
        }
    )
    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)

    # Negative limit - should this be validated?
    # Currently no validation happens before passing to SQLAlchemy
    # This test documents the current behavior
    
    # Different databases might handle this differently
    # Better to validate early and provide clear error


# ============================================================================
# BUG CATEGORY 6: Query Filter - No Maximum Limit Value
# ============================================================================


def test_bug_no_maximum_limit_protection():
    """
    BUG: No maximum limit to prevent memory exhaustion.
    
    A user can specify an arbitrarily large limit value (e.g., 999999999999)
    which could cause memory exhaustion when loading results.
    
    Expected: Should have a reasonable maximum limit (e.g., 100000)
    Actual: No limit validation
    """
    cfg = ConfigSpec(
        tables={
            "items": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                },
            )
        }
    )
    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)

    # Very large limit - should there be a maximum?
    # This could cause memory issues if the table has many rows
    # Consider adding validation like:
    # if limit > 100000:
    #     raise ValueError("limit cannot exceed 100000")
    
    # This test documents the current lack of validation


# ============================================================================
# BUG CATEGORY 7: Artifact Store - Path Normalization Edge Cases
# ============================================================================


def test_bug_artifact_store_double_slash_in_path():
    """
    BUG: Double slashes in paths might cause issues.
    
    When joining paths, double slashes could be created which might
    cause issues with some filesystem implementations.
    
    Expected: Paths should be normalized
    Actual: Double slashes might remain
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        store = ArtifactStore(base_url=tmpdir)
        
        src = Path(tmpdir) / "test.txt"
        src.write_text("content")
        
        # Using path with double slashes
        result = store.put(src, "subdir//file.txt")
        
        # Path should be normalized
        assert "//" not in result.url, "BUG FOUND: Double slashes in path"


# ============================================================================
# BUG CATEGORY 8: Type System - List of Lists Not Properly Rejected
# ============================================================================


def test_bug_list_of_lists_not_rejected():
    """
    BUG: List of lists (nested arrays) should be rejected but might not be.
    
    PostgreSQL supports arrays of arrays, but our type system doesn't.
    The validation should catch attempts to create list<list<T>>.
    
    Expected: Should raise ValueError
    Actual: Might create invalid type mapping
    """
    # This should be rejected - we don't support nested arrays
    with pytest.raises(ValueError):
        ColumnSpec(type="list", item_type="list")


# ============================================================================
# BUG CATEGORY 9: Foreign Key - Mismatched Column Types Not Validated
# ============================================================================


def test_bug_foreign_key_type_mismatch_not_validated():
    """
    BUG: Foreign key column types are not validated to match.
    
    A foreign key from INT column to TEXT column should be rejected,
    but the validation only checks that columns exist, not their types.
    
    Expected: Should validate FK column types match
    Actual: Type mismatch allowed, causes DB error
    """
    cfg = ConfigSpec(
        tables={
            "parent": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),  # TEXT type
                },
            ),
            "child": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),
                    "parent_id": ColumnSpec(type="int", nullable=False),  # INT type!
                },
                foreign_keys=[
                    {
                        "columns": ["parent_id"],
                        "ref_table": "parent",
                        "ref_columns": ["id"],  # FK from INT to TEXT
                    }
                ],
            ),
        }
    )
    
    # This should ideally be caught during validation
    # Currently it's allowed and will fail at DB creation time
    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
    
    # The mismatch exists - it will fail when trying to create the schema
    # but validation didn't catch it early


# ============================================================================
# BUG CATEGORY 10: ORM Model - Multiple Instantiations Create Different Bases
# ============================================================================


def test_bug_orm_base_counter_increments():
    """
    BUG: Each DB instance gets a new Base class with incrementing number.
    
    This is by design to avoid SQLAlchemy warnings, but it means model classes
    from different DB instances are incompatible even for the same schema.
    
    This is more of a design decision than a bug, but worth documenting.
    """
    cfg = ConfigSpec(
        tables={
            "users": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),
                },
            )
        }
    )
    
    db1 = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
    db2 = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
    
    User1 = db1.models["users"]
    User2 = db2.models["users"]
    
    # These are different classes even though the schema is identical
    assert User1 is not User2
    
    # They have different bases
    assert User1.__bases__ != User2.__bases__
    
    # This means instances from one can't be used with the other
    user1 = User1(id="1")
    
    # Cannot use user1 with db2.add() due to different declarative base
    # This is documented behavior, not necessarily a bug


# ============================================================================
# BUG CATEGORY 11: Index Naming - Potential Conflicts
# ============================================================================


def test_bug_index_naming_collision_possible():
    """
    BUG FIXED: Duplicate index names now cause validation error.
    
    Previously: Column-level index and explicit index could have same name
    Now: Duplicate index names raise ValueError during schema building
    
    Expected: Should validate index names are unique
    Actual: Raises ValueError (FIXED!)
    """
    cfg = ConfigSpec(
        tables={
            "users": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),
                    "name": ColumnSpec(type="text", nullable=False, index=True),
                },
                indexes=[
                    # Intentionally using same name as auto-generated index
                    {"name": "idx_users_name", "columns": ["name"]}
                ],
            )
        }
    )
    
    # This now raises an error (FIXED!)
    with pytest.raises(ValueError, match="Duplicate index name"):
        DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)


# ============================================================================
# BUG CATEGORY 12: Extra Column - Reserved Name Collision
# ============================================================================


def test_bug_user_cannot_define_extra_column():
    """
    BUG: User cannot define a column named 'extra' as it's reserved.
    
    The system automatically adds an 'extra' JSONB column to every table.
    If a user tries to define their own 'extra' column, it will cause issues.
    
    Expected: Should validate that 'extra' is not used as column name
    Actual: No validation, causes errors
    """
    cfg = ConfigSpec(
        tables={
            "items": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),
                    "extra": ColumnSpec(type="text", nullable=True),  # Reserved name!
                },
            )
        }
    )
    
    # This should raise an error during validation
    # Currently it might cause issues when the table is built
    with pytest.raises(Exception):  # Should be caught during schema building
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        _ = db.tables["items"]  # Will fail here


# ============================================================================
# BUG CATEGORY 13: Filterable Flag - Default False is Restrictive
# ============================================================================


def test_bug_filterable_defaults_to_false():
    """
    DESIGN ISSUE: filterable defaults to False, making most columns unfilterable.
    
    This means users must explicitly mark columns as filterable. If they forget,
    queries will fail with "field is not filterable" error.
    
    This is restrictive by design but could surprise users.
    """
    cfg = ConfigSpec(
        tables={
            "users": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),  # filterable not set
                    "name": ColumnSpec(type="text", nullable=False),
                },
            )
        }
    )
    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)

    # Trying to filter on 'id' will fail because filterable defaults to False
    with pytest.raises(ValueError, match="not filterable"):
        db.query("users", {"where": {"id": {"eq": "1"}}})
    
    # This is by design but could surprise users who expect all columns filterable


# ============================================================================
# BUG CATEGORY 14: _obj_to_dict - include_extra Flag Behavior
# ============================================================================


def test_bug_obj_to_dict_include_extra_flag():
    """
    POTENTIAL BUG: _obj_to_dict with include_extra=False still checks for extra.
    
    The code checks `if col.name == "extra" and not include_extra` but this
    only skips the extra column. The logic seems correct but could be clearer.
    """
    cfg = ConfigSpec(
        tables={
            "items": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),
                    "name": ColumnSpec(type="text", nullable=False),
                },
            )
        }
    )
    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)

    Item = db.models["items"]
    item = Item(id="1", name="Test")
    
    # With include_extra=False, 'extra' should not be in output
    result = db._obj_to_dict("items", item, include_extra=False)
    assert "extra" not in result
    
    # With include_extra=True (default), 'extra' should be included
    result_with_extra = db._obj_to_dict("items", item, include_extra=True)
    # Note: item.extra might not be set yet, causing AttributeError
    # This test documents the behavior


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
