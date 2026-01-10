"""
Additional bug tests focused on specific edge cases and potential security issues.
"""
from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

import pytest

from agentfabric.artifacts.store import ArtifactStore
from agentfabric.db.facade import DB
from agentfabric.config.spec import ColumnSpec, ConfigSpec, TableSpec


# ============================================================================
# CONFIRMED BUG 1: Empty table names are accepted
# ============================================================================


def test_bug_empty_table_name_should_be_rejected():
    """BUG: Empty string as table name is accepted but creates unusable table."""
    with pytest.raises(Exception, match="table name cannot be empty"):
        ConfigSpec(
            tables={
                "": TableSpec(
                    primary_key=["id"],
                    columns={"id": ColumnSpec(type="text", nullable=False)},
                )
            }
        )


# ============================================================================
# CONFIRMED BUG 2: Duplicate column names with different cases
# ============================================================================


def test_bug_duplicate_column_names_different_case():
    """BUG: Duplicate column names with different cases are accepted.

    In PostgreSQL, identifiers are case-insensitive by default, so 'Name' and
    'name' would refer to the same column. This should be caught during validation.
    """
    with pytest.raises(Exception, match="duplicate column name"):
        ConfigSpec(
            tables={
                "t": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="text", nullable=False),
                        "Name": ColumnSpec(type="text", nullable=False),
                        "name": ColumnSpec(type="text", nullable=False),  # Duplicate!
                    },
                )
            }
        )


# ============================================================================
# CONFIRMED BUG 3: Table names starting with numbers create invalid Python classes
# ============================================================================


def test_bug_table_name_starting_with_number_creates_invalid_class():
    """BUG: Table name starting with number creates Python class with invalid name.

    Python class names cannot start with a digit, but the ORM factory doesn't
    handle this case.
    """
    cfg = ConfigSpec(
        tables={
            "123table": TableSpec(
                primary_key=["id"],
                columns={"id": ColumnSpec(type="text", nullable=False)},
            )
        }
    )

    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)

    class_name = db.models["123table"].__name__
    assert class_name != "123table"
    assert class_name.isidentifier()


# ============================================================================
# CONFIRMED BUG 4: SQLAlchemy ORM requires at least one primary key column
# ============================================================================


def test_bug_empty_primary_key_causes_sqlalchemy_error():
    """BUG: Empty primary key list causes SQLAlchemy error during model creation.

    While PostgreSQL allows tables without primary keys, SQLAlchemy's ORM
    requires at least one primary key column for mapped classes.
    """
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


# ============================================================================
# CONFIRMED BUG 5: Primary key on nullable column is not validated
# ============================================================================


def test_bug_primary_key_on_nullable_column_not_validated():
    """BUG: Primary key can be defined on nullable column - validation missing.

    PostgreSQL will reject this, but our validation doesn't catch it early.
    This would cause runtime errors when trying to create the schema.
    """
    with pytest.raises(Exception, match="primary_key column must be non-nullable"):
        ConfigSpec(
            tables={
                "t": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="text", nullable=True),  # PK but nullable!
                    },
                )
            }
        )


# ============================================================================
# POTENTIAL BUG 6: Artifact store directory traversal
# ============================================================================


def test_potential_bug_artifact_store_directory_traversal(tmp_path: Path):
    """SECURITY: Test if artifact store properly handles directory traversal attempts.

    Using '../' in paths could potentially write files outside the base_url.
    This needs to be tested to ensure it's properly handled.
    """
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()

    store = ArtifactStore(base_url=str(artifacts_dir))

    src = tmp_path / "test.txt"
    src.write_text("secret data")

    with pytest.raises(ValueError, match="directory traversal"):
        store.put(src, "../outside/escaped.txt")


# ============================================================================
# POTENTIAL BUG 7: Default value None handling ambiguity
# ============================================================================


def test_potential_bug_explicit_none_vs_missing_value():
    """AMBIGUITY: Is explicit None the same as missing value for defaults?

    Current behavior: explicit None is treated same as missing value.
    Question: Should explicit None mean "set to NULL" instead?
    """
    cfg = ConfigSpec(
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="uuid", nullable=False, default="uuid4"),
                    "name": ColumnSpec(type="text", nullable=True, default="DefaultName"),
                    "count": ColumnSpec(type="int", nullable=True, default=0),
                },
            )
        }
    )
    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)

    # Case 1: Missing values - defaults should be applied
    row1 = db._apply_sdk_defaults_row("t", {})
    assert isinstance(row1["id"], UUID)
    assert row1["name"] == "DefaultName"
    assert row1["count"] == 0

    # Case 2: Explicit None - what should happen?
    row2 = db._apply_sdk_defaults_row("t", {"id": None, "name": None, "count": None})

    # Current behavior: defaults are applied even for explicit None
    assert isinstance(row2["id"], UUID)  # Default applied
    assert row2["name"] == "DefaultName"  # Default applied
    assert row2["count"] == 0  # Default applied

    # Question: Should explicit None set the value to NULL instead?
    # This is potentially a design issue - the behavior is unclear


# ============================================================================
# POTENTIAL BUG 8: Query filter None value handling
# ============================================================================


def test_potential_bug_query_filter_eq_none():
    """Test how query filter handles eq: None vs is_null: True."""
    from sqlalchemy import Column, Integer, MetaData, Table
    from sqlalchemy.dialects.postgresql import JSONB

    from agentfabric.db.query import build_where

    md = MetaData()
    t = Table(
        "test",
        md,
        Column("id", Integer, nullable=True),
        Column("extra", JSONB, nullable=False),
    )

    with pytest.raises(ValueError, match="Use 'is_null: True/False'"):
        build_where(t, {"id": {"eq": None}}, allowed_fields={"id"})

    # Using is_null: True - explicit NULL check
    clauses2 = build_where(t, {"id": {"is_null": True}}, allowed_fields={"id"})
    assert len(clauses2) == 1


# ============================================================================
# POTENTIAL BUG 9: Update with non-filterable columns
# ============================================================================


def test_potential_bug_update_non_filterable_column_in_where():
    """Test if update allows filtering on non-filterable columns."""
    cfg = ConfigSpec(
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                    "name": ColumnSpec(type="text", nullable=False, filterable=False),
                    "status": ColumnSpec(type="text", nullable=False, filterable=False),
                },
            )
        }
    )
    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)

    # Try to update using non-filterable column in where
    with pytest.raises(ValueError, match="not filterable"):
        db.update("t", where={"name": {"eq": "test"}}, patch={"status": "active"})


# ============================================================================
# POTENTIAL BUG 10: Query with negative limit or offset
# ============================================================================


def test_potential_bug_query_negative_limit_offset():
    """Test query behavior with negative limit or offset values."""
    cfg = ConfigSpec(
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                },
            )
        }
    )
    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)

    # Negative limit - should this raise an error?
    # SQLAlchemy might handle this, but our code could validate it
    try:
        # This might work or fail depending on SQLAlchemy's handling
        result = db.query("t", {"limit": -1})
        print(f"Negative limit accepted, returned: {result}")
    except Exception as e:
        print(f"Negative limit rejected: {e}")

    # Negative offset - similar issue
    try:
        result = db.query("t", {"offset": -1})
        print(f"Negative offset accepted, returned: {result}")
    except Exception as e:
        print(f"Negative offset rejected: {e}")


# ============================================================================
# POTENTIAL BUG 11: Very large limit value
# ============================================================================


def test_potential_bug_query_very_large_limit():
    """Test query with extremely large limit value.

    Large limit values could cause memory issues or performance problems.
    Should there be a maximum limit?
    """
    cfg = ConfigSpec(
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False, filterable=True),
                },
            )
        }
    )
    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)

    # Very large limit
    try:
        result = db.query("t", {"limit": 999999999999})
        print(f"Very large limit accepted")
    except Exception as e:
        print(f"Very large limit rejected: {e}")


# ============================================================================
# EDGE CASE: Foreign key cascade with missing on_delete
# ============================================================================


def test_edge_case_foreign_key_default_on_delete():
    """Test default behavior when on_delete is not specified in foreign key."""
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
                        "ref_columns": ["id"],
                        # on_delete not specified
                    }
                ],
            ),
        }
    )

    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)

    # Should work - default on_delete behavior will be used
    assert "child" in db.tables


# ============================================================================
# EDGE CASE: Index with single column vs column-level index
# ============================================================================


def test_edge_case_index_redundancy():
    """Test if redundant indexes (column-level + explicit) are handled."""
    cfg = ConfigSpec(
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),
                    "name": ColumnSpec(type="text", nullable=False, index=True),  # Column-level
                },
                indexes=[
                    {"name": "idx_name", "columns": ["name"]}  # Explicit index on same column
                ],
            )
        }
    )

    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)

    # Both indexes will be created - might be redundant but not an error
    t = db.tables["t"]
    idx_names = {idx.name for idx in t.indexes}
    assert "idx_t_name" in idx_names  # Column-level index
    assert "idx_name" in idx_names  # Explicit index


# ============================================================================
# EDGE CASE: Special characters in column names
# ============================================================================


def test_edge_case_column_names_with_special_chars():
    """Test column names with special characters that need quoting."""
    cfg = ConfigSpec(
        tables={
            "t": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),
                    "user-name": ColumnSpec(type="text", nullable=False),  # Hyphen
                    "user.email": ColumnSpec(type="text", nullable=False),  # Dot
                },
            )
        }
    )

    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)

    # These should work - SQLAlchemy will quote them
    assert "user-name" in db.tables["t"].c
    assert "user.email" in db.tables["t"].c


# ============================================================================
# EDGE CASE: Unicode in table/column names
# ============================================================================


def test_edge_case_unicode_in_names():
    """Test Unicode characters in table and column names."""
    cfg = ConfigSpec(
        tables={
            "用户表": TableSpec(  # Chinese for "user table"
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),
                    "名字": ColumnSpec(type="text", nullable=False),  # Chinese for "name"
                },
            )
        }
    )

    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)

    # Should work - PostgreSQL supports Unicode identifiers
    assert "用户表" in db.tables


# ============================================================================
# EDGE CASE: Very long identifier names
# ============================================================================


def test_edge_case_very_long_identifier_names():
    """Test very long table and column names.

    PostgreSQL has a limit of 63 bytes for identifiers.
    """
    long_table_name = "a" * 100
    long_column_name = "b" * 100

    cfg = ConfigSpec(
        tables={
            long_table_name: TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="text", nullable=False),
                    long_column_name: ColumnSpec(type="text", nullable=False),
                },
            )
        }
    )

    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)

    # Schema is created, but PostgreSQL will truncate these to 63 bytes
    # This might cause unexpected behavior if the first 63 chars are identical
    assert long_table_name in db.tables


# ============================================================================
# EDGE CASE: Composite primary key order
# ============================================================================


def test_edge_case_composite_pk_order_matters():
    """Test that composite primary key order is preserved."""
    cfg = ConfigSpec(
        tables={
            "t": TableSpec(
                primary_key=["b", "a", "c"],  # Specific order
                columns={
                    "a": ColumnSpec(type="text", nullable=False),
                    "b": ColumnSpec(type="text", nullable=False),
                    "c": ColumnSpec(type="text", nullable=False),
                },
            )
        }
    )

    db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)

    # Check that PK order is preserved
    t = db.tables["t"]
    pk_cols = [c.name for c in list(t.primary_key.columns)]
    assert pk_cols == ["b", "a", "c"], f"Expected ['b', 'a', 'c'], got {pk_cols}"
