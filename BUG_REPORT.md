# AgentFabric - Bug Testing Report

**Date**: 2026-01-09  
**Tester**: Professional Testing Expert  
**Repository**: potatoQi/AgentFabric  
**Testing Methodology**: Black-box and White-box Testing  

## Executive Summary

This report documents the results of comprehensive bug hunting and testing performed on the AgentFabric codebase. A total of **57 targeted tests** were created to identify logical flaws, edge cases, and security vulnerabilities.

**Key Findings**:
- **6 Confirmed Bugs** discovered
- **1 Critical Security Vulnerability** (P0)
- **3 High Priority Issues** (P1) 
- **2 Medium Priority Issues** (P2)
- **Several Design Ambiguities** requiring clarification

All discovered bugs are reproducible with included test cases.

---

## Confirmed Bugs

### BUG-001: Directory Traversal Security Vulnerability (P0 - CRITICAL)

**Severity**: Critical  
**Component**: ArtifactStore  
**Security Impact**: HIGH - Can write files outside intended directory  

**Description**:
The ArtifactStore allows directory traversal using `../` in target paths, potentially allowing writes outside the `base_url` directory. This is a security vulnerability that could lead to unauthorized file access or modification.

**Reproduction**:
```python
store = ArtifactStore(base_url="/safe/artifacts/")
src = Path("secret.txt")
src.write_text("confidential data")

# This succeeds and writes outside the base directory
result = store.put(src, "../../../etc/passwd.txt")
# File is written to absolute path instead of being blocked
```

**Test Location**: `tests/test_additional_bugs.py::test_potential_bug_artifact_store_directory_traversal`

**Expected Behavior**: Directory traversal attempts should be blocked or sanitized

**Actual Behavior**: Files can be written to arbitrary locations outside `base_url`

**Recommendation**: 
- Implement path traversal protection by resolving and validating final paths
- Ensure final resolved path is within `base_url` directory
- Consider using `pathlib.Path.resolve()` and checking if the result is relative to base

**Risk**: Attackers could potentially:
- Overwrite system files
- Write files to unintended locations
- Access sensitive directories

---

### BUG-002: Empty Table Names Accepted (P1 - HIGH)

**Severity**: High  
**Component**: Schema Validation  
**Impact**: Data corruption, unusable tables  

**Description**:
The schema validation accepts empty strings as table names, creating tables that are difficult or impossible to query properly.

**Reproduction**:
```python
cfg = ConfigSpec(
    tables={
        "": TableSpec(  # Empty table name
            primary_key=["id"],
            columns={"id": ColumnSpec(type="text", nullable=False)},
        )
    }
)
db = DB(url="postgresql://...", config=cfg)
# Succeeds! Table with empty name is created
```

**Test Location**: `tests/test_additional_bugs.py::test_bug_empty_table_name_should_be_rejected`

**Expected Behavior**: Empty table names should be rejected during configuration validation

**Actual Behavior**: Empty table names are accepted and tables are created

**Recommendation**:
Add validation in `SchemaRegistry._validate()` or `ConfigSpec`:
```python
if not tname or not tname.strip():
    raise ValueError(f"Table name cannot be empty")
```

---

### BUG-003: Table Names Starting with Numbers Create Invalid Python Classes (P1 - HIGH)

**Severity**: High  
**Component**: ORM Model Factory  
**Impact**: Invalid Python code generated  

**Description**:
When a table name starts with a digit (e.g., "123table"), the ORM factory creates a Python class with the same name. However, Python class names cannot start with digits, creating technically invalid code.

**Reproduction**:
```python
cfg = ConfigSpec(
    tables={
        "123table": TableSpec(
            primary_key=["id"],
            columns={"id": ColumnSpec(type="text", nullable=False)},
        )
    }
)
db = DB(url="postgresql://...", config=cfg)
print(db.models["123table"].__name__)  # "123table" - invalid Python identifier!
```

**Test Location**: `tests/test_additional_bugs.py::test_bug_table_name_starting_with_number_creates_invalid_class`

**Expected Behavior**: Class names should be transformed to valid Python identifiers

**Actual Behavior**: Class names mirror table names exactly, even when invalid

**Recommendation**:
Update `_camel()` function in `schema/orm.py`:
```python
def _camel(name: str) -> str:
    parts = re.split(r"[_\-\s]+", name)
    result = "".join(p[:1].upper() + p[1:] for p in parts if p)
    
    # Ensure valid Python identifier
    if result and result[0].isdigit():
        result = "_" + result
    
    return result or "Table"
```

**Note**: While the code technically "works" (Python allows this at runtime via `type()`), it's a code smell and could cause issues with code generation tools, linters, and type checkers.

---

### BUG-004: Duplicate Column Names with Different Cases Accepted (P1 - HIGH)

**Severity**: High  
**Component**: Schema Validation  
**Impact**: Ambiguous column references, potential data corruption  

**Description**:
PostgreSQL treats identifiers as case-insensitive by default (unless quoted). However, the schema validation accepts columns like "Name" and "name" in the same table, which would both refer to the same column in PostgreSQL.

**Reproduction**:
```python
cfg = ConfigSpec(
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
db = DB(url="postgresql://...", config=cfg)
# Succeeds but creates ambiguous schema
```

**Test Location**: `tests/test_additional_bugs.py::test_bug_duplicate_column_names_different_case`

**Expected Behavior**: Case-insensitive duplicate detection should reject such configs

**Actual Behavior**: Multiple columns differing only in case are accepted

**Recommendation**:
Add case-insensitive duplicate detection in `SchemaRegistry._validate()`:
```python
# Check for case-insensitive duplicates
seen_lower = set()
for col_name in tdef.columns.keys():
    lower = col_name.lower()
    if lower in seen_lower:
        raise ValueError(
            f"table '{tname}' has case-insensitive duplicate column: {col_name}"
        )
    seen_lower.add(lower)
```

---

### BUG-005: Empty Primary Key List Causes Late SQLAlchemy Error (P2 - MEDIUM)

**Severity**: Medium  
**Component**: Schema Validation, ORM  
**Impact**: Confusing error messages  

**Description**:
Tables can be defined with empty primary key lists in the configuration. This validation passes, but later fails when SQLAlchemy tries to create ORM models, resulting in a confusing error message.

**Reproduction**:
```python
cfg = ConfigSpec(
    tables={
        "t": TableSpec(
            primary_key=[],  # Empty PK
            columns={"id": ColumnSpec(type="text", nullable=False)},
        )
    }
)
# Fails during DB() initialization with SQLAlchemy error
db = DB(url="postgresql://...", config=cfg)
# sqlalchemy.exc.ArgumentError: Mapper could not assemble any primary key columns
```

**Test Location**: `tests/test_additional_bugs.py::test_bug_empty_primary_key_causes_sqlalchemy_error`

**Expected Behavior**: Either:
1. Early validation error during config parsing, OR
2. Support for tables without PKs (using mapper flag)

**Actual Behavior**: Late error during ORM model creation

**Recommendation**:
Option 1 - Validate early (simpler):
```python
# In SchemaRegistry._validate()
if not tdef.primary_key:
    raise ValueError(f"table '{tname}' must have at least one primary key column")
```

Option 2 - Support PK-less tables (more flexible):
```python
# In ORMModelFactory.build_models()
mapper_args = {}
if not has_pk:
    mapper_args = {"primary_key": [table.c[next(iter(table.c.keys()))]]}
```

**Note**: While PostgreSQL allows tables without primary keys, SQLAlchemy's ORM requires them. The behavior should be clearly documented.

---

### BUG-006: Primary Key on Nullable Column Not Validated (P2 - MEDIUM)

**Severity**: Medium  
**Component**: Schema Validation  
**Impact**: Schema creation fails at database level  

**Description**:
The configuration allows defining primary key columns as nullable, which PostgreSQL will reject when creating the schema. This should be caught during validation.

**Reproduction**:
```python
cfg = ConfigSpec(
    tables={
        "t": TableSpec(
            primary_key=["id"],
            columns={
                "id": ColumnSpec(type="text", nullable=True),  # PK but nullable!
            },
        )
    }
)
db = DB(url="postgresql://...", config=cfg)
# Config validation passes

db.init_schema()  
# PostgreSQL ERROR: primary key column "id" must be declared NOT NULL
```

**Test Location**: `tests/test_additional_bugs.py::test_bug_primary_key_on_nullable_column_not_validated`

**Expected Behavior**: Validation should enforce that PK columns are non-nullable

**Actual Behavior**: Invalid configuration is accepted, failing only at DB creation

**Recommendation**:
Add validation in `SchemaRegistry._validate()`:
```python
# Check that PK columns are non-nullable
for pk in tdef.primary_key:
    col = tdef.columns[pk]
    if col.nullable:
        raise ValueError(
            f"table '{tname}' primary key column '{pk}' must be non-nullable"
        )
```

---

## Design Ambiguities Requiring Clarification

### DA-001: Explicit None vs Missing Value for Defaults

**Component**: Default Value Handling  
**Complexity**: Design Decision  

**Issue**:
When applying SDK defaults, explicit `None` values are treated the same as missing values. It's unclear if this is intended behavior.

**Current Behavior**:
```python
row = {"id": None, "name": None}  # Explicit None
result = db._apply_sdk_defaults_row("t", row)
# Defaults are applied, None is ignored
assert result["name"] == "DefaultValue"
```

**Questions**:
1. Should explicit `None` mean "set to NULL" (skip default)?
2. Or should explicit `None` be treated as "missing" (apply default)?
3. How do users set a column to NULL if they don't want the default?

**Test Location**: `tests/test_additional_bugs.py::test_potential_bug_explicit_none_vs_missing_value`

**Recommendation**: Document the intended behavior clearly in API docs and consider adding a sentinel value for "use default" if needed.

---

### DA-002: Query Filter `eq: None` vs `is_null: True`

**Component**: Query Builder  
**Complexity**: API Design  

**Issue**:
The behavior of `{"column": {"eq": None}}` vs `{"column": {"is_null": True}}` might be confusing to users.

**Current Behavior**:
- `{"eq": None}` is silently skipped (because of `cond[op] is not None` check)
- `{"is_null": True}` creates IS NULL clause

**Questions**:
1. Should `eq: None` be equivalent to `is_null: True`?
2. Or should `eq: None` raise an error as invalid?
3. Should this be documented as a known behavior?

**Test Location**: `tests/test_additional_bugs.py::test_potential_bug_query_filter_eq_none`

**Recommendation**: Either make `eq: None` work as expected or raise a clear error.

---

## Test Coverage Summary

### Tests Created

| Test File | Tests | Purpose |
|-----------|-------|---------|
| `test_bug_hunting.py` | 40 | Comprehensive edge case and bug hunting |
| `test_additional_bugs.py` | 17 | Focused tests for discovered bugs |
| **Total** | **57** | **New test cases** |

### Test Results

| Status | Count | Details |
|--------|-------|---------|
| **Confirmed Bugs** | 6 | All with reproducible test cases |
| **Passed Tests** | 51 | Edge cases handled correctly |
| **Failed Tests** | 6 | Identified as bugs |

### Areas Tested

1. ✅ **Schema Validation**
   - Table name validation
   - Column name validation
   - Primary key validation
   - Foreign key validation
   - Index validation
   - Type validation

2. ✅ **Default Value Handling**
   - UUID generation
   - Timestamp generation
   - Literal defaults
   - Mutable default isolation
   - Explicit None handling

3. ✅ **Query Building**
   - Filter operations
   - Empty where clauses
   - Null value handling
   - Extra field filtering
   - Limit/offset validation

4. ✅ **ORM Model Factory**
   - Class name generation
   - Table name edge cases
   - Multiple instances

5. ✅ **Artifact Store**
   - Path handling
   - Extension validation
   - Directory traversal
   - URL resolution

6. ✅ **Database Operations**
   - Add/AddAll
   - Query
   - Update
   - Upsert

---

## Recommendations by Priority

### Immediate Actions (P0 - Critical)

1. **Fix Directory Traversal Vulnerability**
   - Implement path sanitization in ArtifactStore
   - Add security tests
   - Review other file operations for similar issues

### High Priority (P1)

2. **Add Schema Validation**
   - Reject empty table names
   - Validate Python identifier compatibility for table names
   - Add case-insensitive duplicate column detection

3. **Improve Error Messages**
   - Earlier validation for ORM-incompatible schemas
   - Clear error messages for common misconfigurations

### Medium Priority (P2)

4. **Add PK Validation**
   - Ensure PK columns are non-nullable
   - Document behavior for tables without PKs

5. **Clarify API Behavior**
   - Document None handling in defaults
   - Clarify query filter None behavior

### Long Term

6. **Additional Validations**
   - Add length checks for identifiers (PostgreSQL 63-byte limit)
   - Warn about reserved SQL keywords as identifiers
   - Validate type compatibility in foreign keys

7. **Security Enhancements**
   - Add input sanitization for all file operations
   - Consider adding path allowlist/blocklist
   - Audit all external input handling

---

## Testing Methodology

### Approach

1. **Code Review**: Analyzed source code for potential edge cases
2. **Black-box Testing**: Tested API behavior without implementation knowledge
3. **White-box Testing**: Examined internal functions for logic errors
4. **Edge Case Testing**: Tested boundary conditions and unusual inputs
5. **Security Testing**: Looked for common vulnerabilities (path traversal, injection, etc.)

### Test Categories

- **Input Validation**: Empty strings, special characters, Unicode, extreme values
- **Type Safety**: Type mismatches, None handling, type coercion
- **Schema Integrity**: Foreign keys, indexes, constraints
- **Security**: Path traversal, SQL injection (via identifiers)
- **Concurrency**: Multiple instances, shared state
- **Performance**: Large limits, deep nesting

---

## Conclusion

The AgentFabric codebase is generally well-structured with good separation of concerns. However, **6 confirmed bugs** were discovered, including **1 critical security vulnerability**.

**Key Strengths**:
- ✅ Good use of Pydantic for config validation
- ✅ Clean separation between schema, ORM, and DB facade
- ✅ Comprehensive existing test coverage for happy paths
- ✅ Good type annotations

**Areas for Improvement**:
- ❌ Missing validation for edge cases in schema definition
- ❌ Security vulnerability in file operations
- ❌ Some error messages occur too late in the process
- ⚠️ Some design decisions need documentation

**Overall Risk Assessment**: 
- **Security Risk**: HIGH (due to directory traversal)
- **Stability Risk**: MEDIUM (edge cases could cause runtime errors)
- **Data Integrity Risk**: MEDIUM (schema validation gaps)

**Recommended Actions**:
1. **Immediately** fix the directory traversal vulnerability (BUG-001)
2. **Soon** add schema validation improvements (BUG-002, BUG-003, BUG-004)
3. **As time permits** improve error messages and add missing validations

All bugs have been documented with:
- Clear reproduction steps
- Test cases for validation
- Recommended fixes
- Priority levels

---

## Appendix: Test Execution

### Running the Bug Tests

```bash
# Run all bug hunting tests
pytest tests/test_bug_hunting.py -v

# Run additional bug tests
pytest tests/test_additional_bugs.py -v

# Run all tests
pytest tests/ -v

# Run only failed tests (bugs)
pytest tests/test_bug_hunting.py::test_bug_hunt_empty_table_name_in_config -v
pytest tests/test_additional_bugs.py::test_potential_bug_artifact_store_directory_traversal -v
```

### Test Environment

- Python: 3.12.3
- pytest: 9.0.2
- SQLAlchemy: 2.0.45
- Pydantic: 2.12.5
- Platform: Linux

---

**Report Generated**: 2026-01-09  
**Next Review**: After bug fixes are implemented  
