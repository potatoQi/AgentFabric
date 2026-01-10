# API 文档

### `def AgentFabric(config_path: str | Path) -> tuple[DBManager, StoreManager | None]`

- 功能：唯一对外入口，传入配置文件路径后，返回 db 管理器和 store 管理器
- 参数1：`config_path`：AgentFabric 使用的 YAML 配置文件路径
- 返回：
  - `DBManager`：数据库管理器
  - `StoreManager | None`：存储管理器，配置里没写 `artifact_base_url` 时为 `None`

- 最小示例：

  ```python
  from agentfabric import AgentFabric

  db, store = AgentFabric("examples/acebench_schema.yaml")

  # 初始化数据表
  db.init_schema()

  if store is not None:
    r = store.put("/path/to/local.json", "runs/001/")
    with store.open(r.url, "rb") as f:
      data = f.read()
  ```


## 1 DB（db 管理器）
说明：db 是 `AgentFabric()` 的第一个返回值

### `db.models["table_name"]`

- 功能：获取“某个表”对应的数据对象类型（写入一条记录前一般拿到对应表的数据类型对象类）
- 参数1：`table_name`：表名（配置里的 key）
返回：`type`，可用来创建数据对象

- 示例：

  ```python
  T = db.models["table_name"]
  row = T(id="k", n=1, extra={"tag": "x"})
  db.add(row)
  ```

### `def init_schema(self) -> None`
- 功能：在数据库里创建配置中写到的所有表, 若表已存在则忽略
- 返回：`None`

### `def add(self, obj: Any) -> None`
- 功能：新增一条数据到某个表
- 参数1：`obj`：要写入的一条数据对象，通常用 `db.models["表名"](...)` 创建
- 返回：`None`

### `def add_all(self, objs: list[Any]) -> None`
- 功能：一次新增多条数据到某个表
- 参数1：`objs`：要写入的数据对象列表
- 返回：`None`

### `def query(self, table: str, filter: dict, *, as_dict: bool = False) -> list[Any]`
- 功能：按筛选条件查询某个表的数据
- 参数1：`table`：表名（配置里的 key）
- 参数2：`filter`：查询条件与分页参数，结构如下
  - `where`：筛选条件（见本文“5 筛选条件 where 写法”）
  - `limit`：最多返回条数（默认 `1000`）
  - `offset`：跳过条数（默认 `0`）
  参数3：`as_dict`：是否将结果转换为字典
  - `False`：返回数据对象列表
  - `True`：返回 `dict` 列表
- 返回：`list[Any]`

- 示例：

  ```python
  rows = db.query(
      "table_name",
      {
          "where": {
            "id": {"eq": "k"},
            "extra.tag": {"like": "x%"}
          },
          "limit": 100,
          "offset": 0,
      },
  )
  ```

### `def update(self, table: str, where: dict, patch: dict) -> int`
- 功能：对满足 where 的行执行更新
- 参数1：`table`：表名  
- 参数2：`where`：筛选条件（不能为空）  
- 参数3：`patch`：要更新的列值（键为列名）
- 返回：`int`，影响行数（rowcount）

### `def upsert(self, table: str, obj: Any, *, conflict_cols: list[str] | None = None) -> Any`
- 功能：写入一条数据，如果已存在就更新，不存在就新增
- 参数1：`table`：表名
- 参数2：`obj`：要写入的一条数据对象
- 参数3：`conflict_cols`：用哪些列判断“已存在”
  - `None`：默认使用该表配置的 `primary_key`
- 返回：`Any`，返回写入后的那条数据对象

- 常见异常：
  - `ValueError("no primary key defined; provide conflict_cols")`：表无主键且未提供 conflict_cols
  - `IntegrityError`：写入的数据不符合数据库的约束，比如必填没填、重复、外键不匹配

### `def delete_where(self, table: str, where: dict) -> int`
- 功能：删除满足 where 的行（安全约束：where 不能为空）
- 参数1：`table`：表名
- 参数2：`where`：筛选条件（不能为空）
- 返回：`int`，删除行数

### 写法：`def delete_by_pk(self, table: str, rows: list[dict[str, Any]]) -> int`
- 功能：按主键值批量删除（面向 UI/工具的更安全删除入口）
- 参数1：`table`：表名
- 参数2：`rows`：主键值列表，每个元素是包含主键列的 dict
- 返回：`int`，删除行数
- 特殊行为：
  - `rows` 为空：直接返回 `0`
- 常见异常：
  - `ValueError("no primary key defined")`：表未定义主键
  - `ValueError("no complete primary key values provided")`：所有行都缺失主键值


## 2 Store（store 管理器）
说明：store 是 `AgentFabric()` 的第二个返回值，配置里没写 `artifact_base_url` 时为 `None`

### `def put(self, x: str | os.PathLike[str], y: str, z: str | None = None) -> PutResult`
- 功能：把本地文件写入目标位置并返回 `PutResult(url, sha256, size_bytes)`
- 参数1：`x`：要写入的本地文件路径（必须存在且是文件）
- 参数2：`y`：目标位置（相对或绝对均可，可以指向目录或文件）
  - 相对路径：会与 `base_url` 拼接
  - 以 `/` 结尾：一定当作目录
- 参数3：`z`：当 `y` 指向目录时用作目标文件名，否则通常可省略
- 返回：`PutResult`
- 常见异常：
  - `FileNotFoundError`：`x` 不存在或不是文件
  - `ValueError("directory traversal detected...")`：相对写入且目标发生目录穿越
  - `ValueError("File extension mismatch...")`：当 `y` 明确指向文件且与 `x` 后缀不一致

### `def open(self, url: str, mode: str = "rb") -> BinaryIO`

- 功能：打开一个 URL 对应的文件并返回文件对象
- 参数1：`url`：要读取的对象 URL（通常来自 `PutResult.url` 或 DB 中存储的 URL）
- 参数2：`mode`：打开模式，常用 `"rb"`
- 返回：`BinaryIO`


## 3 配置表写法

见 [schema-yaml.md](schema-yaml.md)


## 4 CLI

### 写法：`agentfabric` 命令行

- 功能：启动网页界面（用于查看和操作数据）
- 参数：
  - `agentfabric ui --config <path>`：指定 AgentFabric 使用的 YAML 配置文件路径（可选）
  - `--host <host>`：默认 `127.0.0.1`
  - `--port <port>`：默认 `8501`
- 示例：

  ```bash
  agentfabric ui --config examples/acebench_schema.yaml
  ```

---

## 5 筛选条件 where 写法

### 总览

- `where` 必须是一个 `dict`，用于描述“哪些条件要同时满足”。
- `where` 的 key 有三类：
  - 字段名（普通列）：比如 `"id"`、`"created_at"`
  - 字段名（扩展字段）：形如 `"extra.xxx"`（见下文 “`extra.*`（扩展字段）”）
  - 布尔组合关键字：`"and"` / `"or"`
- 字段映射与布尔组合可以混用；布尔组合里也可以继续嵌套 `and/or`。

### 写法 1：字段映射

- 功能：同一字段里写多个条件时，表示都要满足

  ```python
  where = {
      "col": {"eq": 1, "lt": 3},
      "extra.tag": {"like": "d%"},
  }
  ```

### 写法 2：布尔组合（可嵌套）

- 功能：允许把多个条件用 `and/or` 组合起来，也可以和字段映射写法混用；其中 `or` 表示“分支满足任意一个即可”，`and` 表示“子条件必须全部满足”

  ```python
  # 典型用法（DNF）：多个分支“任选其一”，每个分支内部“都要满足”
  where = {
    "or": [
      {
        "and": [
          {"status": {"eq": "ok"}},
          {"n": {"gte": 0}},
        ]
      },
      {
        "and": [
          {"status": {"eq": "warn"}},
          {"extra.tag": {"like": "x%"}},
        ]
      },
    ]
  }
  ```

### 示例：覆盖所有支持的数据类型与 op

说明：下列示例假设你的 schema 中分别存在这些列类型。

- 支持的列类型：`str | text | int | float | bool | datetime | uuid | list[]`

#### 1) text / str（支持：eq/ne/like/in_/nin/is_null）

```python
where = {
  "name": {"eq": "alice"},
  "repo": {"like": "repo/%"},
  "status": {"in_": ["ok", "warn"]},
  "tag": {"nin": ["x", "y"]},
  "note": {"is_null": False},
}
```

#### 2) int（支持：eq/ne/lt/lte/gt/gte/in_/nin/is_null）

```python
where = {
  "n": {"gte": 0, "lt": 10},
  "k": {"in_": [1, 2, 3]},
  "m": {"is_null": True},
}
```

#### 3) float（支持同 int）

```python
where = {
  "score": {"gt": 0.9},
  "loss": {"lte": 0.1},
  "p": {"nin": [0.0, 1.0]},
}
```

#### 4) bool（支持：eq/ne/is_null）

```python
where = {
  "passed": {"eq": True},
  "flag": {"ne": False},
  "maybe": {"is_null": True},
}
```

#### 5) datetime（支持同 int；建议传 timezone-aware datetime）

```python
from datetime import datetime, timezone

where = {
  "created_at": {"gte": datetime(2025, 1, 1, tzinfo=timezone.utc)},
  "finished_at": {"is_null": False},
}
```

#### 6) uuid（支持：eq/ne/in_/nin/is_null；建议传 uuid.UUID）

```python
from uuid import UUID

where = {
  "id": {"eq": UUID("550e8400-e29b-41d4-a716-446655440000")},
  "owner_id": {"in_": [
    UUID("00000000-0000-0000-0000-000000000001"),
    UUID("00000000-0000-0000-0000-000000000002"),
  ]},
}
```

#### 7) list[]（ARRAY；支持：eq/ne/is_null）

```python
where = {
  "tags": {"eq": ["a", "b"]},
  "nums": {"ne": [1, 2, 3]},
  "opt": {"is_null": True},
}
```

### extra 扩展字段

- 写法：`{"extra.a.b": {...}}`
- 功能：用 `extra` 这个扩展字段里的某个 key 来做筛选
- 路径规则：
  - `extra.a.b.c` 等价于 `extra['a']['b']['c']`
  - JSON key 内含 `.`：可用反斜杠转义，比如 `extra.a\\.b.c` 表示 key `a.b` 再取 `c`
- 比较方式限制：`eq/ne/in_/nin/is_null/like`，其他会抛 `ValueError`

### 示例：extra 的各种写法

说明：`extra.*` 会从 JSONB 中取值并按“文本”进行比较（等价于取出 `extra[...]` 后转成字符串再比较）。

#### 1) `eq` / `ne`

```python
where = {
  "extra.tag": {"eq": "ui"},
  "extra.kind": {"ne": "debug"},
}
```

#### 2) `like`（前缀/通配）

```python
where = {
  "extra.owner": {"like": "team-%"},
}
```

#### 3) `in_` / `nin`（value 必须是 list）

```python
where = {
  "extra.env": {"in_": ["dev", "staging"]},
  "extra.region": {"nin": ["cn", "ru"]},
}
```

#### 4) `is_null`（存在性/空值判断）

```python
where = {
  # extra.foo 不存在或为 null
  "extra.foo": {"is_null": True},

  # extra.bar 存在且不为 null
  "extra.bar": {"is_null": False},
}
```

#### 5) 多层路径

```python
where = {
  "extra.a.b.c": {"eq": "x"},
}
```

#### 6) key 里包含 `.` 的转义

```python
where = {
  # 表示 extra["a.b"]["c"] == "x"
  "extra.a\\.b.c": {"eq": "x"},
}
```

#### 7) 与 and/or 组合

```python
where = {
  "and": [
    {"extra.kind": {"eq": "toy"}},
    {"or": [
      {"extra.tag": {"in_": ["a", "b"]}},
      {"extra.owner": {"like": "team-%"}},
    ]},
  ]
}
```
