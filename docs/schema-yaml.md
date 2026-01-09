# Schema YAML 规范

`agentfabric` 的核心是“配置驱动注册 schema”：所有表/字段都由 YAML 定义，然后在建库前创建。

## 顶层字段

```yaml
version: 1
postgres_schema: acebench     # 可选：Postgres schema 隔离

tables: { ... }
```

## `postgres_schema` 不是数据库名

- `url` 里的 `.../DBNAME` 是 **数据库名**。
- `postgres_schema` 是该数据库内部的 **schema**（命名空间），用来隔离/组织表。

常见组合：
- 单库多项目隔离：所有项目共用一个数据库（同一个 `DBNAME`），每个项目用不同的 `postgres_schema`。
- 简单模式：只用默认 schema（`public`），不填 `postgres_schema`。

## 表定义

```yaml
tables:
  some_table:
    description: "..."         # 可选
    primary_key: [col_a, col_b] # 可选但强烈建议（upsert 需要）
    columns: { ... }            # 必填
    indexes: []                 # 可选
    foreign_keys: []            # 可选
```

### indexes vs 列里的 index

你会看到两个“索引相关”的入口：

- 列级：在 `columns.<col>.index: true`
  - 用途：**快速声明单列索引**。
  - 当前实现：会自动创建一个名字形如 `idx_<table>_<col>` 的索引。

- 表级：`indexes: [{name, columns}]`
  - 用途：声明**联合索引（多列）**或你想**自己控制索引名字**的情况。
  - 示例：

```yaml
indexes:
  - name: idx_repo_commit
    columns: [repo, commit]
```

建议：
- 只需要单列索引：用 `columns.<col>.index: true` 就够了。
- 需要联合索引/自定义名字：用 `indexes`。

### columns

```yaml
columns:
  col_name:
    type: text
    nullable: false
    default: now
    index: true
    filterable: true
```

- `type` 支持：
  - 标量：`str | text | int | float | bool | datetime | json | uuid`
  - 数组：`list`（需要 `item_type`）

#### filterable

`filterable: true/false` 控制这列**能不能出现在 `DB.query(..., {"where": ...})` / `DB.update(..., where=...)` 的 where 里**：

- `filterable: true`：允许在 where 里过滤（比如 `{"repo": {"eq": "..."}}`）
- `filterable: false`：不允许在 where 里出现（会直接报错），用于避免“任何人都能按敏感列/高基数列随意扫表”。

注意：
- `extra.*` 的过滤不走 `filterable`，只受其自身的 MVP 算子限制（见 [Filter DSL](filter-dsl.md)）。

#### list 类型

```yaml
f2p:
  type: list
  item_type: text
  nullable: true
```

当前映射：Postgres `ARRAY(<item_type>)`。

### 主键（primary_key）

- 复合主键支持：`primary_key: [a, b, c]`
- 主键顺序会影响底层索引的“左前缀”命中（性能），建议按你最常用的过滤维度排序。

### 外键（foreign_keys）

支持复合外键：

```yaml
foreign_keys:
  - columns: [instance_id, gold_patch_cov]
    ref_table: ace_instance
    ref_columns: [instance_id, gold_patch_cov]
    on_delete: restrict
```

### 默认值（default）

MVP 支持：
- `default: now`：DB 侧生成（`now()`）
- `default: uuid4`：SDK 侧生成（写入时自动补齐）

说明：
- 只要配置了 `default`，当写入时该列为 `None`/未提供，SDK 会在写入前自动补齐。
- `default: now` 会补齐为 `datetime.now(timezone.utc)`（UTC）；同时 DB 侧也仍会设置 `server_default now()` 作为兜底。
- 字面量默认值（如 `0`、`""`、`"Hello"`、`true`）会按原样写入。

不做：运行期 schema 迁移（改 YAML 需要你自行迁移/重建）。

## 固定列 `extra`

每张表都会自动增加：

- `extra JSONB NOT NULL DEFAULT '{}'::jsonb`

用于放动态信息。对 `extra.key` 的过滤能力见 [Filter DSL](filter-dsl.md)。
