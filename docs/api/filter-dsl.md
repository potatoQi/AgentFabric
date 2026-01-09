# Filter DSL（`where` 结构与算子）

Filter DSL 是 `DB.query()` / `DB.update()` 的过滤条件表达方式。

- `DB.query(table, filter)`：filter dict 里包含 `where`/`limit`/`offset`
- `DB.update(table, where, patch)`：直接传 `where` dict

底层由 `agentfabric.db.query.build_where()` 把 where dict 编译成 SQLAlchemy clauses。

## where 的总体结构

```python
where = {
  "col": {
    "eq": 1,
    "gte": 0,
    "lt": 10,
  },
  "extra.tag": {
    "like": "x%",
  },
}
```

规则：

- `where[field]` 必须是 dict，否则抛 `TypeError`
- 同一字段可写多个算子，语义是 AND（全部条件都要满足）

补充：`where[field]` 是一个 dict，因此同一个算子（同一个 key）在语法上无法出现两次。
例如你不能表达“同时写两次 is_null 并让系统检测矛盾”，因为 `{"is_null": True, "is_null": False}` 在 Python/YAML 里只会保留最后一个值。

## 支持的算子（普通列）

普通列支持的算子集合：

- `eq`：等于
- `ne`：不等于
- `lt` / `lte`：小于 / 小于等于
- `gt` / `gte`：大于 / 大于等于
- `in_`：在集合内（SQL IN）
- `nin`：不在集合内（SQL NOT IN）
- `like`：SQL LIKE（字符串模式匹配）
- `is_null`：是否为 NULL（布尔）

示例：

```python
# n in [0, 200) and n != 5
{
  "n": {"gte": 0, "lt": 200, "ne": 5}
}
```

## `extra.*` 键（JSONB 文本视图）

`extra.xxx` 表示在 JSONB 的 `extra` 字段里取 key `xxx`，并把它按“文本”处理。

支持嵌套路径：`extra.a.b.c` 会被解释为 JSON 路径 `extra['a']['b']['c']`。

如果你的 JSON key 本身包含 `.`，可以用反斜杠转义：

- `extra.a\.b.c` 等价于 `extra['a.b']['c']`

例如：

```python
{"extra.tag": {"eq": "debug"}}
```

### `extra.*` 的算子限制

为了避免类型/性能陷阱，`extra.*` 只允许“文本安全”的算子：

- `eq` / `ne`
- `in_` / `nin`
- `like`
- `is_null`

如果对 `extra.*` 使用 `gt/gte/lt/lte` 等算子，会抛 `ValueError`。

## 空列表边界（`in_` / `nin`）

- `in_: []`：必须返回空结果集（实现上追加一个恒 false 条件）
- `nin: []`：no-op（不产生过滤条件）

示例：

```python
# 一定返回 []
{"id": {"in_": []}}

# 等价于不写 where
{"id": {"nin": []}}
```

## filterable 白名单（普通列）

当 `DB.query()` 调用 `build_where(..., allowed_fields=filterable_cols)` 时：

- 普通列如果没有在配置里 `filterable: true`，会抛 `ValueError("field is not filterable: ...")`
- `extra.*` 不受这个限制，但受算子限制

## 常见组合示例（query filter）

```python
filter = {
  "where": {
    "n": {"gte": 10, "lt": 13, "ne": 12},
    "extra.tag": {"like": "x%"},
    "id": {"in_": ["a", "b", "c"]},
  },
  "limit": 100,
  "offset": 0,
}

rows = db.query("t", filter)
```

`is_null` 用法示例：

```python
# 取 attempt 为 NULL 的行
{
  "attempt": {"is_null": True}
}

# 取 attempt 非 NULL 的行
{
  "attempt": {"is_null": False}
}

# extra.* 也支持 is_null（注意 extra.* 走文本视图）
{
  "extra.tag": {"is_null": True}
}
```
