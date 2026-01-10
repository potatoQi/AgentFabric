# API 文档

### 写法：`def AgentFabric(config_path: str | Path) -> tuple[DBManager, StoreManager | None]`
功能：唯一对外入口，传入配置文件路径后，返回 db 管理器和 store 管理器
参数1：`config_path`：AgentFabric 使用的 YAML 配置文件路径
返回：
- `DBManager`：数据库管理器
- `StoreManager | None`：存储管理器，配置里没写 `artifact_base_url` 时为 `None`
常见异常：
- `ValueError("provide url (or set db_url in config)")`：配置里没写 `db_url`

最小示例：

```python
from agentfabric import AgentFabric

db, store = AgentFabric("examples/acebench_schema.yaml")
db.init_schema()

if store is not None:
  r = store.put("/path/to/local.json", "runs/001/")
  with store.open(r.url, "rb") as f:
    data = f.read(32)
```

---

## DB（db 管理器）
说明：db 是 `AgentFabric()` 的第一个返回值

### 写法：`def init_schema(self) -> None`
功能：在数据库里创建配置中写到的所有表
返回：`None`

### 写法：`def add(self, obj: Any) -> None`
功能：新增一条数据到某个表
参数1：`obj`：要写入的一条数据对象，通常用 `db.models["表名"](...)` 创建
返回：`None`

### 写法：`def add_all(self, objs: list[Any]) -> None`
功能：一次新增多条数据到某个表
参数1：`objs`：要写入的数据对象列表
返回：`None`

### 写法：`def query(self, table: str, filter: dict, *, as_dict: bool = False) -> list[Any]`
功能：按筛选条件查询某个表的数据
参数1：`table`：表名（配置里的 key）
参数2：`filter`：查询条件与分页参数，结构如下
- `where`：筛选条件（见本文“筛选条件 where 写法”）
- `limit`：最多返回条数（默认 `1000`）
- `offset`：跳过条数（默认 `0`）
参数3：`as_dict`：是否将结果转换为字典
- `False`：返回数据对象列表
- `True`：返回 `dict` 列表
返回：`list[Any]`

示例：

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

### 写法：`def update(self, table: str, where: dict, patch: dict) -> int`
功能：对满足 where 的行执行更新
参数1：`table`：表名
参数2：`where`：筛选条件（不能为空）
参数3：`patch`：要更新的列值（键为列名）
返回：`int`，影响行数（rowcount）

### 写法：`def delete_where(self, table: str, where: dict) -> int`
功能：删除满足 where 的行（安全约束：where 不能为空）
参数1：`table`：表名
参数2：`where`：筛选条件（不能为空）
返回：`int`，删除行数

### 写法：`def upsert(self, table: str, obj: Any, *, conflict_cols: list[str] | None = None) -> Any`
功能：写入一条数据，如果已存在就更新，不存在就新增
参数1：`table`：表名
参数2：`obj`：要写入的一条数据对象
参数3：`conflict_cols`：用哪些列判断“已存在”
- `None`：默认使用该表配置的 `primary_key`
返回：`Any`，返回写入后的那条数据对象
常见异常：
- `ValueError("no primary key defined; provide conflict_cols")`：表无主键且未提供 conflict_cols
 - `IntegrityError`：写入的数据不符合数据库的约束，比如必填没填、重复、外键不匹配

### 写法：`def delete_by_pk(self, table: str, rows: list[dict[str, Any]]) -> int`
功能：按主键值批量删除（面向 UI/工具的更安全删除入口）
参数1：`table`：表名
参数2：`rows`：主键值列表，每个元素是包含主键列的 dict
返回：`int`，删除行数
特殊行为：
- `rows` 为空：直接返回 `0`
常见异常：
- `ValueError("no primary key defined")`：表未定义主键
- `ValueError("no complete primary key values provided")`：所有行都缺失主键值

### 写法：`models: dict[str, type]  # 通过 models[table_name] 获取数据对象类型`
功能：获取某个表对应的数据对象类型
参数1：`table_name`：表名
返回：`type`，可用来创建数据对象

示例：

```python
T = db.models["t"]
row = T(id="k", n=1, extra={"tag": "x"})
db.add(row)
```

### DB 默认值补齐（写入前自动补齐）
写法：无需调用（由 `add/add_all/upsert` 内部自动应用）
功能：当列在配置中声明 `default`，且用户传入缺失或 None 时，AgentFabric 在写入前自动补齐
- `default: "uuid4"`：填 `uuid.uuid4()`
- `default: "now"`：填 `datetime.now(timezone.utc)`
- `default: <literal>`：填该字面量的深拷贝（避免可变对象共享）

---

## Store（store 管理器）
说明：store 是 `AgentFabric()` 的第二个返回值，配置里没写 `artifact_base_url` 时为 `None`

### 写法：`def put(self, x: str | os.PathLike[str], y: str, z: str | None = None) -> PutResult`
功能：把本地文件写入目标位置并返回 `PutResult(url, sha256, size_bytes)`
参数1：`x`：要写入的本地文件路径（必须存在且是文件）
参数2：`y`：目标位置（相对或绝对均可，可以指向目录或文件）
- 相对路径：会与 `base_url` 拼接
- 以 `/` 结尾：一定当作目录
参数3：`z`：当 `y` 指向目录时用作目标文件名，否则通常可省略
返回：`PutResult`
常见异常：
- `FileNotFoundError`：`x` 不存在或不是文件
- `ValueError("directory traversal detected...")`：相对写入且目标发生目录穿越
- `ValueError("File extension mismatch...")`：当 `y` 明确指向文件且与 `x` 后缀不一致

### 写法：`def open(self, url: str, mode: str = "rb") -> BinaryIO`
功能：打开一个 URL 对应的文件并返回文件对象
参数1：`url`：要读取的对象 URL（通常来自 `PutResult.url` 或 DB 中存储的 URL）
参数2：`mode`：打开模式，常用 `"rb"`
返回：`BinaryIO`

### 写法：

```python
@dataclass(frozen=True)
class PutResult:
    url: str
    sha256: str
    size_bytes: int | None = None
```

功能：`put()` 的返回结构
参数1：`url`：目标对象 URL
参数2：`sha256`：内容哈希（hex）
参数3：`size_bytes`：写入字节数

---

## 配置模型（`agentfabric.config.spec.*`）

说明：你只需要写 YAML 配置文件，这里列出字段含义，方便照着写

### 写法：

```python
class ConfigSpec(BaseModel):
    version: int = 1
    db_url: str | None = None
    artifact_base_url: str | None = None
    postgres_schema: str | None = None
    tables: dict[str, TableSpec]
```

功能：顶层配置对象
参数1：`version`：配置版本
参数2：`db_url`：数据库连接 URL（`AgentFabric(config_path)` 会用它来连库）
参数3：`artifact_base_url`：文件/对象存储的 base_url（写了才会返回 `store`；不写则 `store` 为 `None`）
参数4：`postgres_schema`：把表放到数据库里的哪个命名空间下，一般不需要改
参数5：`tables`：表定义

### 写法：

```python
class TableSpec(BaseModel):
    description: str | None = None
    primary_key: list[str]
    columns: dict[str, ColumnSpec]
    indexes: list[IndexSpec] = []
    foreign_keys: list[ForeignKeySpec] = []
```

功能：单表结构定义
参数1：`description`：描述信息
参数2：`primary_key`：每一行数据的唯一标识字段列表（必填，主键列必须 `nullable: false`）
参数3：`columns`：列定义（禁止定义名为 `extra` 的列，`extra` 为系统保留列并会自动追加）
参数4：`indexes`：额外索引
参数5：`foreign_keys`：外键（可选，用来约束某些列必须在另一个表里存在）

### 写法：

```python
class ColumnSpec(BaseModel):
    type: Literal["list", "str", "text", "int", "float", "bool", "datetime", "json", "uuid"]
    item_type: Literal["str", "text", "int", "float", "bool", "datetime", "json", "uuid"] | None = None
    nullable: bool = True
    default: Any | None = None
    index: bool = False
    filterable: bool = False
```

功能：列定义
参数1：`type`：列类型
参数2：`item_type`：当 `type == "list"` 时必填，用来指定列表元素类型
参数3：`nullable`：是否可为空
参数4：`default`：默认值（支持 `"now"`、`"uuid4"` 或字面量）
参数5：`index`：是否为该列生成单列索引
参数6：`filterable`：是否允许用户用它来做筛选条件（影响 `DB.query()` 的 where）

### 写法：

```python
class IndexSpec(BaseModel):
    name: str
    columns: list[str]
```

功能：多列索引定义
参数1：`name`：索引名（不能为空）
参数2：`columns`：列名列表（至少 1 个）

### 写法：

```python
class ForeignKeySpec(BaseModel):
    columns: list[str]
    ref_table: str
    ref_columns: list[str]
    on_delete: Literal["cascade", "restrict", "set_null", "no_action"] | None = None
```

功能：外键定义
参数1：`columns`：本表列
参数2：`ref_table`：引用表名
参数3：`ref_columns`：引用表列
参数4：`on_delete`：删除行为

---

## 筛选条件 where 写法（进阶）

### 写法：`def build_where(table: Any, where: dict[str, Any], *, allowed_fields: set[str] | None = None) -> list[Any]`
功能：把 where 里的筛选条件翻译成数据库能执行的过滤条件，一般情况下你不需要直接调用它
参数1：`table`：内部用的表对象（普通使用 DB 的同学通常不需要传）
参数2：`where`：筛选条件（见下）
参数3：`allowed_fields`：允许被用来筛选的字段集合（DB 会自动传）
返回：`list[Any]`，内部使用的过滤条件列表
常见异常：
- `TypeError`：where 结构不符合要求
- `ValueError`：使用了不支持的条件写法、extra 路径写错、或用了不允许筛选的字段

#### where 写法 1：字段映射（简单）

写法：

```python
where = {
  "col": {"eq": 1, "lt": 3},
  "extra.tag": {"like": "d%"},
}
```

功能：同一字段里写多个条件时，表示都要满足

#### where 写法 2：布尔组合（更灵活）

写法：

```python
where = {
  "and": [
    {"col": {"eq": 1}},
    {"col": {"gt": 0}},
    {"other": {"ne": "x"}},
  ]
}

where = {
  "or": [
    {"a": {"eq": 1}},
    {"b": {"eq": 2}},
  ]
}
```

功能：允许把多个条件用 `and/or` 组合起来，也可以和字段映射写法混用

#### 支持的比较方式（普通列）
写法：`{"field": {"op": value}}`
功能：
- `eq` / `ne` / `lt` / `lte` / `gt` / `gte`
- `in_` / `nin`
- `like`
- `is_null: True/False`

重要约束：
- 禁止写 `eq: None` 或 `ne: None`，NULL 判断必须用 `is_null: True/False`，否则抛 `ValueError`
- `in_: []` 会被当作肯定查不到（保证空结果），`nin: []` 会被当作不加这个条件

#### `extra.*`（扩展字段）
写法：`{"extra.a.b": {...}}`
功能：用 `extra` 这个扩展字段里的某个 key 来做筛选
路径规则：
- `extra.a.b.c` 等价于 `extra['a']['b']['c']`
- JSON key 内含 `.`：可用反斜杠转义，比如 `extra.a\\.b.c` 表示 key `a.b` 再取 `c`
比较方式限制：`eq/ne/in_/nin/is_null/like`，其他会抛 `ValueError`

---

## CLI（可选）

### 写法：`agentfabric` 命令行
功能：启动网页界面（用于查看和操作数据）
参数：
- `agentfabric ui --config <path>`：指定 AgentFabric 使用的 YAML 配置文件路径（可选）
- `--host <host>`：默认 `127.0.0.1`
- `--port <port>`：默认 `8501`
- `--toolbar-mode auto|developer|viewer|minimal`：网页工具栏模式
- `--no-browser`：不自动打开浏览器

示例：

```bash
agentfabric ui --config examples/acebench_schema.yaml --host 0.0.0.0 --port 8501
```

### 写法：`def main(argv: Sequence[str] | None = None) -> int`
功能：CLI 的 Python 入口
参数1：`argv`：参数列表，None 表示使用 `sys.argv`
返回：`int`，进程退出码（内部可能 `SystemExit`）
