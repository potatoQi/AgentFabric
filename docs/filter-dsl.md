# Filter DSL

`DB.query()` 接收的 `filter` 是一个字典：

```python
{
  "where": {
    "field": {"op": value, ...},
    "extra.some_key": {"op": value, ...},
  },
  "limit": 1000,
  "offset": 0,
}
```

## 支持的算子

对普通列（非 `extra.*`）：
- `eq`, `ne`
- `lt`, `lte`, `gt`, `gte`
- `in_`, `nin`
- `like`
- `is_null: true/false`

边界行为：
- `in_: []` → 返回空结果集
- `nin: []` → 不产生过滤条件

### 算子语义（逐个解释）

下面假设你在查询表 `T`，并且 `field` 是一个普通列（不是 `extra.*`）。

#### `eq`

等于。

```python
{"field": {"eq": 123}}
{"field": {"eq": "abc"}}
```

注意：对普通列，`eq: None` 通常等价于“是否为 NULL”，但为了避免歧义，推荐用 `is_null` 显式表达。

#### `ne`

不等于。

```python
{"field": {"ne": 123}}
```

注意：SQL 里 `NULL` 的比较语义比较特殊，`field != 123` 不会匹配 `field IS NULL` 的行；如果你要包含/排除 NULL，请用 `is_null`。

#### `lt` / `lte` / `gt` / `gte`

数值或可比较类型的大小比较：

- `lt`: 小于
- `lte`: 小于等于
- `gt`: 大于
- `gte`: 大于等于

```python
{"score": {"gt": 0.9}}
{"attempt": {"lte": 3}}
```

提示：如果列是 `timestamptz`（datetime），value 需要传可比较的时间值；建议统一用 UTC。

#### `in_`

属于集合（`field IN (...)`）。value 必须是列表。

```python
{"repo": {"in_": ["org/a", "org/b"]}}
{"attempt": {"in_": [0, 1, 2]}}
```

边界行为：
- `in_: []` → 返回空结果集（等价于“永远为假”），用于你上层逻辑已经得到“没有可选值”的情况

#### `nin`

不属于集合（`field NOT IN (...)`）。value 必须是列表。

```python
{"repo": {"nin": ["org/bad", "org/tmp"]}}
```

边界行为：
- `nin: []` → 不产生过滤条件（等价于“不过滤”），因为 `NOT IN ()` 在 SQL 中不可用

#### `like`

字符串模式匹配（SQL `LIKE`）。

```python
{"repo": {"like": "org/%"}}      # 前缀匹配
{"message": {"like": "%error%"}} # 子串匹配
```

说明：
- `%` 匹配任意长度字符
- `_` 匹配任意单个字符
- 是否区分大小写取决于数据库/排序规则；Postgres 的 `LIKE` 默认大小写敏感，如需不敏感通常用 `ILIKE`（MVP 目前不提供）

#### `is_null`

显式判断是否为 NULL。

```python
{"finished_at": {"is_null": True}}   # finished_at IS NULL
{"finished_at": {"is_null": False}}  # finished_at IS NOT NULL
```

这是表达 NULL 语义最清晰、最推荐的方式。

### 同一个字段写多个算子（AND 组合）

一个字段的条件 dict 里可以同时包含多个算子；语义是把这些条件用 AND 连接起来。

示例：范围查询 + 排除某个值

```python
items = db.query(
  "ace_traj",
  {
    "where": {
      "attempt": {"gte": 0, "lt": 5, "ne": 3},
    }
  },
)
```

示例：`extra.*` 也可以多算子（但只能用允许的那些算子）

```python
items = db.query(
  "ace_instance",
  {
    "where": {
      "extra.tag": {"is_null": False, "like": "debug%"},
    }
  },
)
```

## `extra.*` 的限制（MVP）

对 `extra.key`：
- 会把 `extra.key` 先 cast 成文本再比较
- 只允许“文本语义安全”的算子：`eq/ne/in_/nin/is_null/like`
- 不支持 `gt/gte/lt/lte`（避免数值语义不明确）

示例：

```python
items = db.query(
  "ace_instance",
  {
    "where": {
      "repo": {"eq": "org/repo"},
      "extra.tag": {"eq": "debug"},
      "extra.group": {"in_": ["A", "B"]},
    }
  },
)
```
