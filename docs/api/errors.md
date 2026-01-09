# 错误与异常约定

本包没有统一的自定义异常层（例如 `AgentFabricError`），多数错误以 Python 内置异常或 SQLAlchemy/psycopg 异常形式暴露。

下面列出你在使用 API 时最常见的异常类型与触发条件。

## DB

### `DB.__init__`

- `ValueError("provide url")`：url 为空
- `ValueError("provide exactly one of config or config_path")`：config/config_path 传参不满足二选一

### `DB.query`

- `ValueError("field is not filterable: ...")`：where 使用了非 filterable 的普通列
- `TypeError("where['x'] must be a dict of ops")`：where[field] 不是 dict
- `KeyError`：table 不存在 / column 不存在（例如 where 中引用了未知列）

### `DB.update`

- `ValueError("update requires non-empty where")`：where 为空（防止全表更新）

### `DB.upsert`

- `ValueError("no primary key defined; provide conflict_cols")`：`upsert()` 未提供 conflict_cols 且表无主键（通常仅在绕过配置校验/手工构造 schema 时可能发生）
- `sqlalchemy.exc.IntegrityError`：违反 DB 约束（NOT NULL / UNIQUE / FK / CHECK 等）

## Filter DSL（build_where）

- `TypeError`：where[field] 不是 dict
- `ValueError`：
  - 普通列触发 filterable 白名单
  - `extra.*` 使用了不允许的算子

## ArtifactStore

- `FileNotFoundError`：`put(x, ...)` 的 `x` 不存在或不是文件
- `ValueError("File extension mismatch...")`：当 `y` 明确指向文件且与 `x` 后缀不一致
- `fsspec`/底层存储异常：open/put 到远端存储可能抛出具体 FS 实现的异常

## SQLAlchemy / psycopg

当你连接的是 Postgres 且使用 `postgresql+psycopg://...`：

- 连接错误、认证失败等：通常是 `sqlalchemy.exc.OperationalError`
- 约束失败：通常是 `sqlalchemy.exc.IntegrityError`，其底层 `orig` 是 psycopg 的具体错误类型

建议在黑盒/生产环境针对这些异常做统一封装或日志记录。
