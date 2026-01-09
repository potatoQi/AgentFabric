# DB API（`agentfabric.DB`）

`DB` 是面向“动态 Schema（YAML/Pydantic）+ PostgreSQL + SQLAlchemy”的轻量 Facade。

- 负责：
  - 解析配置（`config` / `config_path`）
  - 生成 SQLAlchemy `MetaData`/`Table`
  - 动态生成 ORM model（`db.models[table_name]`）
  - 提供 `add/add_all/query/update/upsert` 这些高频数据库操作
- 不负责：
  - 复杂 join/聚合/排序（当前 `query` 没有 `order_by`）
  - 自动迁移（没有 Alembic 集成）

## 构造函数

```python
from agentfabric import DB
from agentfabric.config.spec import ConfigSpec

db = DB(
    url: str,
    *,
    config: ConfigSpec | None = None,
    config_path: str | None = None,
)
```

参数语义：

- `url`：SQLAlchemy engine URL。必须非空。
- `config` 与 `config_path`：必须“二选一”（恰好提供一个）。
  - `config`：已经解析好的 `ConfigSpec`
  - `config_path`：YAML 文件路径（内部会调用 `agentfabric.load_config()`）

常见错误：

- `url` 为空：抛 `ValueError("provide url")`
- `config` 与 `config_path` 同时提供/同时缺失：抛 `ValueError("provide exactly one of config or config_path")`

## 属性

构造完成后，你通常会用到：

- `db.config`：`ConfigSpec`
- `db.registry`：内部的 `SchemaRegistry`（通常不需要直接用）
- `db.engine`：SQLAlchemy Engine
- `db.Session`：SQLAlchemy Session factory
- `db.metadata`：SQLAlchemy MetaData（schema=postgres_schema）
- `db.tables`：`dict[str, Table]`，key 为表名
- `db.models`：`dict[str, type]`，key 为表名，value 为动态生成的 ORM 类

### 动态 ORM model 的使用

```python
T = db.models["t"]
row = T(id="k", n=1, extra={"tag": "x"})
```

注意：这些 model class 是运行时生成的；不要把它们当作“稳定的 import 路径”。

## 建表

```python
db.init_schema() -> None
```

- 作用：对配置中所有表执行 `CREATE TABLE`（等价于 SQLAlchemy `metadata.create_all(engine)`）。
- 建议用法：每次测试或新 schema 初始化时调用。

## 写入

### `add(obj)`

```python
db.add(obj: Any) -> None
```

- `obj` 必须是 `db.models[table]` 生成的 ORM 实例。
- 行为：单条插入并 `commit()`。
- 默认值：若某列在配置里声明了 `default`，且你传入缺失/None，SDK 会在插入前自动补齐（详见本页“默认值规则”）。

### `add_all(objs)`

```python
db.add_all(objs: list[Any]) -> None
```

- 行为：批量插入并 `commit()`。

## 查询

```python
db.query(table: str, filter: dict, *, as_dict: bool = False) -> list[Any]
```

- `table`：表名（配置中的 key），例如 `"ace_instance"`。
- `filter`：查询条件 dict，结构见下。
- `as_dict`：
  - `False`（默认）：返回 ORM 实例列表
  - `True`：返回 `dict` 列表（会包含 `extra` 字段）

### filter dict 结构

```python
{
  "where": {
    "col_a": {"eq": 1},
    "col_b": {"gte": 0, "lt": 10},
    "extra.tag": {"like": "x%"},
  },
  "limit": 100,
  "offset": 0,
}
```

字段含义：

- `where`：Filter DSL（详见 [docs/api/filter-dsl.md](filter-dsl.md)）
- `limit`：最多返回多少条记录。
  - 默认：`1000`
  - `limit=0`：返回空列表。
- `offset`：跳过前面多少条记录。
  - 默认：`0`

重要注意：

- 当前没有 `order_by`，因此分页结果在“无排序”时不保证稳定顺序；若你需要严格分页一致性，应在 schema 中引入排序字段，并扩展 API 加 `order_by`。

### filterable 白名单约束

普通列必须在配置中声明 `filterable: true` 才允许出现在 `where` 中，否则 `db.query` 会抛 `ValueError("field is not filterable: ...")`。

`extra.*` 键不受 `filterable` 限制，但算子集合更严格（见 Filter DSL 文档）。

## 更新

```python
db.update(table: str, where: dict, patch: dict) -> int
```

- `where`：Filter DSL 的 where dict（不是完整 filter dict）。
- `patch`：要更新的字段值。
- 返回：影响行数（rowcount）。

安全约束：

- `where` 不能为空，否则抛 `ValueError("update requires non-empty where")`（避免误操作全表更新）。

## Upsert

```python
db.upsert(table: str, obj: Any, *, conflict_cols: list[str] | None = None) -> Any
```

- 行为：PostgreSQL `INSERT ... ON CONFLICT DO UPDATE ... RETURNING`。
- `conflict_cols`：冲突列集合。
  - 默认：使用该表的 primary key（来自配置）。
  - 若表没有 primary key 且不提供 `conflict_cols`：抛错。
- 返回：一个新的 ORM 实例（用 RETURNING 的结果重建）。

注意：

- 若表存在外键约束，`upsert` 同样会触发约束校验；缺少父表记录会抛 `IntegrityError`。

## 默认值规则（SDK default fill）

`DB` 在写入前会根据配置对缺失/None 的字段做“SDK 侧补齐”，规则：

- `default: "uuid4"`：补 `uuid.uuid4()`
- `default: "now"`：补 `datetime.now(timezone.utc)`
- `default: <literal>`：补该字面量的深拷贝（dict/list 用 `deepcopy`，避免共享可变对象）
- 若用户显式提供了非 None 值：不会覆盖。

提示：DB 层也可能有 server_default（例如 `now()`）作为兜底，但推荐依赖 SDK 补齐以保证一致性。
