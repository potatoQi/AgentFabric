# 配置与 YAML（`agentfabric.load_config` 与 `agentfabric.config.spec.*`）

本包的数据库 schema 通过 YAML 注册，加载后会被 Pydantic 模型校验。

## 入口：`load_config(path)`

```python
from agentfabric import load_config

cfg = load_config("examples/acebench_schema.yaml")
```

- 作用：读取 YAML 并返回 `ConfigSpec`。
- YAML 解析：使用 `yaml.safe_load`。

## 顶层：`ConfigSpec`

Python 结构（简化）：

```python
class ConfigSpec(BaseModel):
    version: int = 1
    postgres_schema: str | None = None
    tables: dict[str, TableSpec]
```

YAML 示例：

```yaml
version: 1
postgres_schema: my_schema

tables:
  t:
    primary_key: [id]
    columns:
      id: {type: text, nullable: false, filterable: true}
      n: {type: int, nullable: false, filterable: true}
```

字段说明：

- `postgres_schema`：所有表创建/查询所在的 PG schema。
  - 黑盒测试里通常用随机 schema，做到隔离与可清理。

## 表：`TableSpec`

```python
class TableSpec(BaseModel):
    description: str | None = None
    primary_key: list[str]
    columns: dict[str, ColumnSpec]
    indexes: list[IndexSpec] = []
    foreign_keys: list[ForeignKeySpec] = []
```

### primary_key

- 必填：每个表都必须定义至少 1 个主键列。
- 支持复合主键：按列表顺序生成 `PRIMARY KEY(col1, col2, ...)`。
- 注意：复合主键的顺序会影响 upsert 默认 conflict key。
- 约束：所有主键列必须存在于 `columns`，且必须 `nullable: false`。

### columns

key 是列名；value 是 `ColumnSpec`。

注意：`extra` 是保留列名。AgentFabric 会为每个表自动添加一个 `extra` JSONB 列，因此配置中禁止定义名为 `extra`（大小写不敏感）的列。

## 列：`ColumnSpec`

```python
class ColumnSpec(BaseModel):
    type: TypeName
    item_type: ScalarTypeName | None = None
    nullable: bool = True
    default: Any | None = None
    index: bool = False
    filterable: bool = False
```

### type / item_type

- `type` 支持：
  - 标量：`text/str/int/float/bool/datetime/json/uuid`
  - 列表：`list`（映射为 Postgres `ARRAY(...)`）
- `item_type`：仅当 `type: list` 时必须提供。

校验规则（Pydantic）：

- `type: list` 且缺少 `item_type`：校验失败
- `type != list` 但提供了 `item_type`：校验失败

### default

`default` 支持三类：

- 特殊值：
  - `"now"`：写入前由 SDK 填 `datetime.now(timezone.utc)`（并可能在 DB 侧设置 server_default 兜底）
  - `"uuid4"`：写入前由 SDK 填 `uuid.uuid4()`
- 字面量：任意可 JSON 表达的值（例如 `"Hello"` / `0` / `true` / `[]` / `{}`）

### filterable

- 控制 `DB.query()` 的 where 白名单：只有 `filterable: true` 的普通列才能出现在 where。
- `extra.*` 不走这个白名单（但算子更严格）。

## 索引：`IndexSpec`

```python
class IndexSpec(BaseModel):
    name: str
    columns: list[str]
```

校验规则：

- `name` 不能为空
- `columns` 必须至少包含 1 个列名

YAML：

```yaml
indexes:
  - name: idx_t_n
    columns: [n]
```

另外：列级别也可以写 `index: true`，会生成单列索引。

## 外键：`ForeignKeySpec`

```python
class ForeignKeySpec(BaseModel):
    columns: list[str]
    ref_table: str
    ref_columns: list[str]
    on_delete: Literal["cascade", "restrict", "set_null", "no_action"] | None = None
```

YAML：

```yaml
foreign_keys:
  - columns: [instance_id, gold_patch_cov]
    ref_table: ace_instance
    ref_columns: [instance_id, gold_patch_cov]
    on_delete: restrict
```

说明：

- 支持复合外键（columns/ref_columns 可以是多个列）。
- `on_delete`：
  - `cascade`：父删除级联删除子
  - `restrict`：父删除被阻止
  - `set_null`：父删除时把子列设为 NULL（要求子列可空）
  - `no_action`/None：不设置 ondelete

## 固定列：`extra`

所有表都会自动追加一列：

- `extra JSONB NOT NULL DEFAULT '{}'::jsonb`

用户无需在 YAML 里声明它。
