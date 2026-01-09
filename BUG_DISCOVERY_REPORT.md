# AgentFabric Bug Discovery Report

**Date:** 2026-01-09  
**Tester:** Professional Testing Expert  
**Repository:** potatoQi/AgentFabric  
**Scope:** Complete codebase logical vulnerability analysis

---

## Executive Summary

This report documents a comprehensive bug hunting exercise performed on the AgentFabric codebase. Through systematic analysis and targeted unit testing, **4 confirmed bugs** and **6 design issues** were discovered and **all 4 bugs have been fixed**.

### Test Coverage Summary
- **Total test files created:** 1 new file (`test_critical_bug_discovery.py`)
- **Total tests written:** 14 focused bug discovery tests
- **All tests passing:** 132 tests (14 new + 118 existing updated)
- **Bugs confirmed:** 4
- **Bugs fixed:** 4 ✅
- **Design issues identified:** 6

### Bugs Fixed
1. ✅ **Path double slashes not normalized** in ArtifactStore (HIGH severity)
2. ✅ **Query filter `eq: None` silently ignored** (MEDIUM severity)
3. ✅ **Explicit None treated as missing value** in defaults (MEDIUM severity)
4. ✅ **Duplicate index names allowed** (LOW severity)

---

## Critical Bugs (Priority: HIGH)

### BUG #1: Double Slashes in Artifact Store Paths ⚠️ SECURITY/RELIABILITY

**Severity:** HIGH  
**Component:** `src/agentfabric/artifacts/store.py`  
**Status:** ✅ **FIXED**

**Description:**
When using paths with double slashes in the ArtifactStore, the path is not normalized, resulting in URLs/paths containing `//`. This can cause issues with various filesystem implementations and URL parsers.

**Reproduction:**
```python
store = ArtifactStore(base_url="/tmp/artifacts")
src = Path("/tmp/test.txt")
result = store.put(src, "subdir//file.txt")
# Result: /tmp/artifacts/subdir//file.txt (contains //)
```

**Root Cause:**
The `_join` method in `ArtifactStore` strips leading/trailing slashes from path parts but doesn't normalize internal double slashes.

**Fix Applied:**
Updated `_join` method to normalize paths while preserving URL schemes:
```python
def _join(self, *parts: str) -> str:
    path = "/".join([self.base_url, *[p.strip("/") for p in parts]])
    from urllib.parse import urlparse
    parsed = urlparse(path)
    if parsed.scheme:
        # For URLs with schemes, normalize the path part only
        normalized_path = os.path.normpath(parsed.path).replace(os.sep, "/")
        return f"{parsed.scheme}://{normalized_path}"
    else:
        # For local paths, use full normpath
        normalized = os.path.normpath(path).replace(os.sep, "/")
        return normalized
```

**Test Case:** `test_bug_artifact_store_double_slash_in_path` (NOW PASSING)

---

### BUG #2: Query Filter `eq: None` Silently Ignored

**Severity:** MEDIUM  
**Component:** `src/agentfabric/db/query.py`  
**Status:** ✅ **FIXED**

**Description:**
When using `{"field": {"eq": None}}` in query filters, the condition was silently ignored instead of being treated as an SQL `IS NULL` check or raising an error.

**Reproduction:**
```python
clauses = build_where(table, {"id": {"eq": None}}, allowed_fields={"id"})
# Returns: [] (empty list - condition ignored!)
```

**Root Cause:**
In `db/query.py`, line 51 skipped operations when value was None:
```python
if op in cond and cond[op] is not None:  # <-- This skips when value is None
```

**Fix Applied:**
Added explicit check to raise clear error when `eq: None` or `ne: None` is used:
```python
for op, fn in OPS.items():
    if op in cond:
        v = cond[op]
        # Check for explicit None in eq/ne operations - this is likely a mistake
        if v is None and op in ("eq", "ne"):
            raise ValueError(
                f"Use 'is_null: True/False' instead of '{op}: None' for NULL checks on field '{field}'"
            )
        if v is not None:
            # ... process operation
```

**Test Case:** `test_bug_query_filter_eq_none_silently_ignored` (NOW PASSING)

---

### BUG #3: Explicit None Treated as Missing Value for Defaults

**Severity:** MEDIUM  
**Component:** `src/agentfabric/db/facade.py`  
**Status:** ✅ **FIXED**

**Description:**
When applying SDK defaults, an explicitly provided `None` value was treated the same as a missing value. This made it impossible to explicitly set a field to NULL when a default exists.

**Reproduction:**
```python
# Column has default="DefaultName"
row = db._apply_sdk_defaults_row("items", {"name": None})
# Result: {"name": "DefaultName"} 
# Expected: {"name": None}
```

**Root Cause:**
In `db/facade.py`, `_apply_sdk_defaults_row` method:
```python
for col, spec in defaults.items():
    if col in row and row[col] is not None:  # <-- Only skips if non-None
        continue
    # Apply default even when col in row but row[col] is None
```

**Fix Applied:**
Changed logic to only apply defaults when key is missing entirely:
```python
for col, spec in defaults.items():
    # Only apply default if the key is completely missing
    # Explicit None should be respected (user wants NULL)
    if col in row:
        continue
    # Apply default only when key is missing
    if spec == "uuid4":
        row[col] = uuid.uuid4()
    # ... etc
```

**Test Case:** `test_bug_explicit_none_treated_as_missing` (NOW PASSING)

---

### BUG #4: Duplicate Index Names Allowed

**Severity:** LOW  
**Component:** `src/agentfabric/schema/builder.py`  
**Status:** ✅ **FIXED**

**Description:**
When a user defines a column with `index=True` and also creates an explicit index on the same column with the same auto-generated name pattern, duplicate indexes were created.

**Reproduction:**
```python
TableSpec(
    columns={
        "name": ColumnSpec(type="text", index=True),  # Creates idx_users_name
    },
    indexes=[
        {"name": "idx_users_name", "columns": ["name"]}  # Same name!
    ]
)
# Result: Two indexes with the same name
```

**Root Cause:**
In `schema/builder.py`, no validation checked for duplicate index names between column-level and explicit indexes.

**Fix Applied:**
Added validation to detect and prevent duplicate index names:
```python
# 3) indexes: column-level + explicit
for tname, tdef in self.registry.tables.items():
    table = self.tables[tname]
    index_names: set[str] = set()
    
    # Column-level indexes
    for c in tdef.columns.values():
        if c.index:
            idx_name = f"idx_{tname}_{c.name}"
            if idx_name in index_names:
                raise ValueError(f"Duplicate index name in table '{tname}': {idx_name}")
            index_names.add(idx_name)
            Index(idx_name, table.c[c.name])
    
    # Explicit indexes
    for idx in tdef.indexes:
        if idx.name in index_names:
            raise ValueError(f"Duplicate index name in table '{tname}': {idx.name}")
        index_names.add(idx.name)
        Index(idx.name, *[table.c[c] for c in idx.columns])
```

**Test Case:** `test_bug_index_naming_collision_possible` (NOW PASSING)

---

## Design Issues (Priority: MEDIUM)

### ISSUE #1: No Validation for Reserved Column Name "extra"

**Severity:** MEDIUM  
**Component:** `src/agentfabric/schema/builder.py`

**Description:**
The system automatically adds an `extra` JSONB column to every table. If a user tries to define their own column named `extra`, it causes a conflict. There's no validation to prevent this.

**Impact:**
- Column definition conflict
- Confusing error messages
- Schema creation fails

**Recommendation:**
Add validation in `ConfigSpec` or `SchemaRegistry`:
```python
if "extra" in ts.columns:
    raise ValueError("Column name 'extra' is reserved by the system")
```

**Test Case:** `test_bug_user_cannot_define_extra_column`

---

### ISSUE #2: No Maximum Limit Protection

**Severity:** MEDIUM  
**Component:** `src/agentfabric/db/facade.py`

**Description:**
The `query()` method accepts arbitrarily large `limit` values (e.g., 999999999999), which could cause memory exhaustion when loading results.

**Impact:**
- Denial of Service risk
- Out of memory errors
- Poor performance

**Recommendation:**
Add a maximum limit:
```python
MAX_LIMIT = 100000
limit = int(filter.get("limit", 1000))
if limit > MAX_LIMIT:
    raise ValueError(f"limit cannot exceed {MAX_LIMIT}")
```

**Test Case:** `test_bug_no_maximum_limit_protection`

---

### ISSUE #3: No Validation for Negative Limit/Offset

**Severity:** LOW  
**Component:** `src/agentfabric/db/facade.py`

**Description:**
Negative values for `limit` and `offset` are not validated, leading to undefined behavior.

**Impact:**
- Unpredictable query results
- Database-dependent behavior
- Confusing errors

**Recommendation:**
```python
limit = int(filter.get("limit", 1000))
offset = int(filter.get("offset", 0))
if limit < 0:
    raise ValueError("limit must be non-negative")
if offset < 0:
    raise ValueError("offset must be non-negative")
```

**Test Case:** `test_bug_negative_limit_offset_not_validated`

---

### ISSUE #4: Foreign Key Type Mismatch Not Validated

**Severity:** MEDIUM  
**Component:** `src/agentfabric/schema/registry.py`

**Description:**
When defining a foreign key, the system validates that columns exist but doesn't validate that their types match (e.g., FK from INT to TEXT).

**Impact:**
- Schema creation fails at database level
- Late error detection
- Poor error messages

**Recommendation:**
Add type validation in `SchemaRegistry._validate()`:
```python
for fk in tdef.foreign_keys:
    for i, col in enumerate(fk.columns):
        local_type = tdef.columns[col].type_name
        ref_type = ref.columns[fk.ref_columns[i]].type_name
        if local_type != ref_type:
            raise ValueError(
                f"Foreign key type mismatch: {tname}.{col} ({local_type}) "
                f"references {fk.ref_table}.{fk.ref_columns[i]} ({ref_type})"
            )
```

**Test Case:** `test_bug_foreign_key_type_mismatch_not_validated`

---

### ISSUE #5: Filterable Defaults to False

**Severity:** LOW  
**Component:** `src/agentfabric/config/spec.py`

**Description:**
The `filterable` flag defaults to `False`, making columns unfilterable by default. Users must explicitly set `filterable=True` for each column they want to query.

**Impact:**
- Restrictive default behavior
- Frequent "field is not filterable" errors
- Surprise for new users

**Recommendation:**
This is a design decision. Consider:
1. Defaulting `filterable=True` (more permissive)
2. Better documentation of the requirement
3. A global config option to set the default

**Test Case:** `test_bug_filterable_defaults_to_false`

---

### ISSUE #6: Update with Empty Patch Allowed

**Severity:** LOW  
**Component:** `src/agentfabric/db/facade.py`

**Description:**
The `update()` method allows an empty `patch` dictionary, which executes successfully but does nothing. This could indicate a logic error in calling code.

**Impact:**
- Silent no-op operations
- Potential logic errors in application code
- Wasted database round trips

**Recommendation:**
Consider validating:
```python
if not patch:
    raise ValueError("update requires non-empty patch")
```

**Test Case:** `test_bug_update_with_empty_patch_allowed`

---

## Testing Methodology

### Approach
1. **Code Analysis:** Manual review of all source files to identify potential edge cases
2. **Pattern Matching:** Looking for common bug patterns (input validation, error handling, edge cases)
3. **Targeted Testing:** Creating specific tests for each suspected vulnerability
4. **Reproduction:** Confirming bugs with minimal reproducible examples

### Bug Categories Tested
1. Input validation (limits, offsets, paths)
2. Type system edge cases (nested types, type mismatches)
3. Default value handling
4. Query filter semantics
5. Schema validation
6. Security issues (directory traversal, reserved names)
7. Naming conflicts
8. ORM edge cases

### Test Files
- `tests/test_critical_bug_discovery.py` - 14 focused bug discovery tests
- `tests/test_bug_hunting.py` - 27 comprehensive edge case tests (existing)
- `tests/test_additional_bugs.py` - 23 additional bug tests (existing)
- `tests/test_stress_and_edge_cases.py` - 22 stress tests (existing)

---

## Recommendations Summary

### Immediate Fixes Required (HIGH Priority)
1. **Fix double slash path normalization** in ArtifactStore
2. **Handle `eq: None` properly** - either support it or raise clear error
3. **Fix explicit None vs missing value** in default handling

### Should Fix (MEDIUM Priority)
4. **Validate duplicate index names**
5. **Validate reserved column name "extra"**
6. **Add maximum limit protection** (prevent DoS)
7. **Validate foreign key type matching**

### Consider (LOW Priority)
8. Validate negative limit/offset values
9. Validate empty patch in update operations
10. Reconsider default for `filterable` flag

---

## Conclusion

The AgentFabric codebase is well-structured with good test coverage. This bug hunting exercise successfully identified and **fixed all 4 critical logical vulnerabilities**:

- ✅ **1 security/reliability issue fixed** (path handling)
- ✅ **3 logic bugs fixed** (query filters, defaults, index names)
- 📋 **6 design issues documented** (for future consideration)

All bugs have been:
- ✅ Clearly reproduced with test cases
- ✅ Root cause analyzed and documented
- ✅ Fixed with minimal, targeted code changes
- ✅ Verified with automated tests
- ✅ Existing tests updated to match correct behavior

### Final Test Results
```
$ python3 -m pytest tests/ -q

132 passed, 19 skipped in 0.69s
```

**All tests passing!** The codebase is now more robust, with:
- Proper path normalization in ArtifactStore
- Clear error messages for query filter mistakes
- Correct handling of explicit None vs missing values
- Prevention of duplicate index names

The test suite has been enhanced with 14 new targeted tests that will help prevent regressions and serve as documentation for expected behavior.

---

**Report prepared by:** Professional Testing Expert  
**Last updated:** 2026-01-09 (FINAL - All bugs fixed)  
**Status:** ✅ **COMPLETE**
