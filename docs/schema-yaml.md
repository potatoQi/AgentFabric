# Schema YAML 规范

`agentfabric` 的核心是“配置驱动注册 schema”：所有表/字段都由 YAML 定义，然后在建库前创建。

## 1 顶层字段

```yaml
version: 1
postgres_schema: acebench     # 可选：Postgres schema 隔离

tables: { ... }
```

> `postgres_schema` 不是数据库名。`url` 里的 `.../DBNAME` 是 **数据库名**。 `postgres_schema` 是该数据库内部的 **schema**（命名空间），用来隔离/组织表。

## 2 表定义

```yaml
tables:
  some_table:
    description: "..."         # 表格描述
    primary_key: [col_a, col_b] # 主键, 必填
    columns: { ... }  # 字段
    indexes: []       # 索引列
    foreign_keys: []  # 外键,可选
```

### 2.1 primary_key

- 复合主键支持：`primary_key: [a, b, c]`
- 主键顺序会影响底层索引的“左前缀”命中（性能），建议按你最常用的过滤维度排序。

### 2.2 columns

```yaml
columns:
  col_name:
    type: text
    nullable: false
    default: now
    index: true
    filterable: true
```

#### 2.2.1 type

- `type` 支持：
  - 标量：`str | text | int | float | bool | datetime | json | uuid`
  - 数组：`list`（需要 `item_type`）

#### 2.2.2 filterable

- `filterable: true/false` 控制这列**能不能出现在 `DB.query(..., {"where": ...})` / `DB.update(..., where=...)` 的 where 里**：

  > 注意：`extra` 字段的过滤不走 `filterable`，只支持固定算子 `eq/ne/in_/nin/is_null/like`。

#### 2.2.3 default

- `default: now`：DB 侧生成（`now()`）
- `default: uuid4`：SDK 侧生成（写入时自动补齐）
- `default: "Hello"`：字面量默认值（如 `0`、`""`、`"Hello"`、`true`）会按原样写入。

#### 2.2.4 index

- true/false
- 用途：声明单列索引。
- 当前实现：会自动创建一个名字形如 `idx_<table>_<col>` 的索引。

#### 2.2.5 固定字段 `extra`

- 每张表都会自动增加 `extra` 字段，用于存放动态信息，type 为 json，默认值为 `{}`

### 2.3 foreign_keys

支持复合外键：

```yaml
foreign_keys:
  - columns: [instance_id, gold_patch_cov]
    ref_table: ace_instance
    ref_columns: [instance_id, gold_patch_cov]
    on_delete: restrict
```

### 2.4 indexes

- `indexes: [{name, columns}]`
- 用途：声明联合索引（多列）或你想自己控制索引名字**的情况。
- 示例：

  ```yaml
  indexes:
    - name: idx_repo_commit
      columns: [repo, commit]
  ```
