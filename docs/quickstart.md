# 快速开始

## 1) 安装

如果你在本仓库内开发/运行（推荐用 uv）：

- `uv sync`

在其他项目里使用（发布到 PyPI 后）：

- `pip install agentfabric`

## 2) 准备一个 YAML schema

参考：`examples/acebench_schema.yaml`，或看 [Schema YAML 规范](schema-yaml.md)。

## 3) 连接 Postgres 并建表

```python
from agentfabric import DB

db = DB(
    url="postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME",
    config_path="examples/acebench_schema.yaml",
)

db.init_schema()
```

说明：
- `url` 里的 `DBNAME` 是 **PostgreSQL 数据库名**（database）。
- `postgres_schema`（YAML 里）是该数据库内部的 **schema/命名空间**（类似目录，用于隔离表名）。
    - 例：`url=.../mydb` + `postgres_schema=acebench` 表示在数据库 `mydb` 里创建 `acebench.ace_instance`、`acebench.ace_traj`。
    - 如果 `postgres_schema` 不填（或填 `public`），就会创建在默认 schema 下（例如 `public.ace_instance`）。
- `init_schema()` 是 `create_all` 语义：只创建不存在的表/索引；不做迁移。

## 4) 写入数据

`agentfabric` 会根据 YAML schema 动态生成 ORM Model（你可以把它理解成“按表名拿到一份 Python class”）：

```python
Instance = db.models["ace_instance"]  # 表 ace_instance 对应的 ORM 类

row = Instance(
    instance_id="ins_001",
    gold_patch_cov=0.42,
    repo="org/repo",
    commit="abc123",
    f2p=["fileA.py", "fileB.py"],
    p2p=["tests/test_a.py"],
    extra={"tag": "debug"},
)

db.add(row)
```

如果要写 `ace_traj` 表，同理：

```python
Traj = db.models["ace_traj"]

traj = Traj(
    instance_id="ins_001",
    gold_patch_cov=0.42,
    agent="my_agent",
    model="gpt-5.2",
    attempt=0,
    patch_url="file:///tmp/patch.diff",
    traj_url="file:///tmp/traj.json",
    metric={"pass": True},
)

db.add(traj)
```

注意：
- 每张表都有固定列 `extra`（JSONB）。
- 只要配置了 `default`，当写入时该列为 `None`/未提供，SDK 会在写入前自动补齐。
    - `default: now` → `datetime.now(timezone.utc)`
    - `default: uuid4` → `uuid.uuid4()`

## 5) 查询数据

```python
items = db.query(
    "ace_instance",
    {
        "where": {
            "repo": {"eq": "org/repo"},
            "extra.tag": {"eq": "debug"},
        },
        "limit": 100,
        "offset": 0,
    },
)

print(items[0].instance_id)
```

如果需要字典形式：

```python
rows = db.query("ace_instance", {"where": {}}, as_dict=True)
```

更多 filter 细节见 [Filter DSL](filter-dsl.md)。
