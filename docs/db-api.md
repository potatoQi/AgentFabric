# DB API

核心入口：`agentfabric.DB`

## 初始化

```python
from agentfabric import DB

db = DB(
  url="postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME",
  config_path="path/to/schema.yaml",
)
```

参数：
- `url`：SQLAlchemy 数据库 URL（Postgres）
- `config_path`：YAML schema 路径
- `config`：也可以直接传 `ConfigSpec`（与 `config_path` 二选一）

## 建表

```python
db.init_schema()
```

## 动态 ORM 模型

```python
Model = db.models["table_name"]
obj = Model(col1=..., col2=..., extra={...})
```

说明：
- `db.tables[...]` 是 SQLAlchemy Core `Table`
- `db.models[...]` 是动态生成的 ORM class

## 写入

### add / add_all

```python
db.add(obj)
# 或
db.add_all([obj1, obj2])
```

语义：
- `add/add_all` 是“普通插入”的语义：会尝试把这行写进表里。
- 如果该行已经存在（通常指主键/唯一约束冲突），Postgres 会报错，SQLAlchemy 会抛出 `IntegrityError`（在 `commit()` 时触发）。
- 如果你需要“存在则更新，不存在则插入”的幂等写入，请用 `upsert`。

SDK 默认值：
- 只要列在 YAML 里配置了 `default`，当你写入时该列为 `None`/未提供，SDK 会在写入前自动补齐（`add/add_all/upsert` 都会补）。
  - `default: uuid4` → `uuid.uuid4()`
  - `default: now` → `datetime.now(timezone.utc)`（UTC）
  - `default: 0` / `default: ""` / `default: "Hello"` / `default: true` 等字面量 → 直接填入对应值

default 支持的数据类型（MVP 现状）：

- 特殊值（字符串）：
  - `"uuid4"`
  - `"now"`

- 字面量值（会原样写入；SDK 用 deepcopy 复制一份避免共享引用）：
  - `int`：例如 `0`、`123`
  - `float`：例如 `0.0`、`3.14`
  - `bool`：`true/false`
  - `str`：例如 `""`、`"Hello"`
  - `list`：例如 `["a", "b"]`（常用于 `type: list` 的列；元素类型应与 `item_type` 匹配）
  - `dict`：例如 `{k: v}`（常用于 `type: json` 的列）

注意：
- `default` 的类型需要与该列的 `type` 兼容；否则写入时可能在驱动层/数据库层报错。
- 对 `type: datetime`，推荐用 `default: now`；虽然理论上也能给一个 Python `datetime` 字面量，但 YAML/JSON 里不够直观。

### upsert

```python
out = db.upsert("table_name", obj)
```

- 默认冲突键：该表的 `primary_key`
- 返回值：重新构造的 ORM 对象（非 session-managed；可当作只读返回值使用）

### update

```python
n = db.update(
  "table_name",
  where={"col": {"eq": 1}},
  patch={"other": 2},
)
```

语义：
- `update(table, where, patch) -> int`：对满足 `where` 条件的行做批量更新，返回更新行数。
- `patch` 是“直接赋值”语义（相当于 SQL 的 `SET col = value`）。

限制与注意：
- `where` 必须非空：避免误更新全表。
- `where` 里只能使用该表声明为 `filterable: true` 的列；`extra.*` 例外（允许，但算子有限，见 [Filter DSL](filter-dsl.md)）。
- `patch` 不会触发 `default` 自动补齐（默认补齐是写入 `add/add_all/upsert` 的语义）。
- 更新 `extra` 会整体覆盖 JSONB（MVP 不提供 JSONB 局部 merge API）。

可直接照抄的例子：

1) 按主键/复合主键更新某条记录（最常见）

```python
n = db.update(
  "ace_instance",
  where={"instance_id": {"eq": "ins_001"}, "gold_patch_cov": {"eq": 0.42}},
  patch={"end_time_data": None},
)
assert n in (0, 1)
```

2) 批量更新：给一批满足条件的行写入完成时间

```python
from datetime import datetime, timezone

n = db.update(
  "ace_traj",
  where={"agent": {"eq": "my_agent"}, "model": {"eq": "gpt-5.2"}},
  patch={"end_time_harness": datetime.now(timezone.utc)},
)
print("updated", n)
```

3) 用 `extra.*` 做筛选（仅支持文本安全算子）

```python
n = db.update(
  "ace_instance",
  where={"extra.tag": {"eq": "debug"}},
  patch={"repo": "org/repo"},
)
```

## 查询

```python
items = db.query(
  "table_name",
  {"where": {"col": {"eq": 1}}, "limit": 100, "offset": 0},
)
```

语义：
- `query(table, filter, as_dict=False) -> list[...]`
  - `as_dict=False`（默认）：返回 ORM 对象列表（元素类型是 `db.models[table]` 对应的 class）
  - `as_dict=True`：返回 `dict` 列表（每个 dict 是一行：`{column: value, ...}`，包含 `extra`）

什么时候用 `as_dict`：
- 你想把结果直接 `json.dumps(...)`、写入文件、或者传给不依赖 ORM 的下游：用 `as_dict=True`
- 你想继续用属性访问（如 `row.instance_id`）或把对象再 `upsert`：用默认的 ORM 对象

filter 结构（MVP）：

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

注意：
- `where` 里只能用该表 `filterable: true` 的列；`extra.*` 例外（允许，但算子有限）。
- where 支持的算子与边界行为见 [Filter DSL](filter-dsl.md)。

可直接照抄的例子：

1) 返回 ORM 对象（默认）

```python
items = db.query(
  "ace_instance",
  {"where": {"repo": {"eq": "org/repo"}}, "limit": 10, "offset": 0},
)
print(items[0].instance_id)
```

2) 返回字典（`as_dict=True`）

```python
rows = db.query(
  "ace_instance",
  {"where": {"repo": {"eq": "org/repo"}}, "limit": 10, "offset": 0},
  as_dict=True,
)
print(rows[0]["instance_id"], rows[0].get("extra"))
```

3) 用 `extra.*` 做筛选（文本安全算子）

```python
rows = db.query(
  "ace_instance",
  {"where": {"extra.tag": {"eq": "debug"}}, "limit": 100, "offset": 0},
  as_dict=True,
)
```
