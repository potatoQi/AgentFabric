# ArtifactStore（冷资源 URL）

`agentfabric.ArtifactStore` 用于把“大文件/冷资源”写入文件系统或对象存储，并把返回的 URL 写进 DB。

为什么需要它：
- DB 里更适合存“结构化元数据”（字段可筛选、可 join）
- 大文件（patch diff、traj json、日志、模型输出）更适合存到文件系统/S3，只把 `url` + `sha256` 回填 DB

## 初始化

```python
from agentfabric import ArtifactStore

store = ArtifactStore(base_url="file:///tmp/agentfabric-artifacts")
# 也可以是 s3://bucket/prefix 之类（依赖 fsspec 对应的 filesystem）
```

`base_url` 的含义：
- 所有写入 API 都接收 `relpath`（相对路径），最终会拼成 `url = base_url + "/" + relpath`
- 例：`base_url="file:///tmp/af"` + `relpath="runs/001/traj.json"`
    → `url="file:///tmp/af/runs/001/traj.json"`

可用的 URL 形式：
- 本地：`file:///...` 或者不带 scheme 的绝对/相对路径（例如 `/data/artifacts`）
- 对象存储：例如 `s3://bucket/prefix/...`（需要安装/配置对应的 fsspec backend 与凭据）

## 写入

对外推荐只用一个统一接口：`store.put(x, y, z=None)`。

- `x`：要写入的东西
    - 仅支持：本地文件路径（`str` / `Path`）
- `y`：目标路径（可以是相对路径或绝对路径）
    - 相对路径：自动拼接到 `base_url` 下
    - 绝对路径：直接写到这个路径（例如 `/data/artifacts/...` 或 `s3://bucket/prefix/...`）
    - `y` 可以指向“目录”或“文件”
- `z`：当 `y` 指向目录时可选的文件名；当 `y` 是文件时会被忽略

额外规则：如果 `y` 指向文件（例如 `runs/001/traj.json`），会校验 `x` 和 `y` 的后缀名必须一致（比如都是 `.json`），否则会报错。

假设：
- 你初始化时用了 `base_url="file:///tmp/agentfabric-artifacts"`
- 那么写入 `relpath="runs/001/traj.json"` 最终会落在：
    `file:///tmp/agentfabric-artifacts/runs/001/traj.json`

### 1) x 是本地文件路径；y 是目录

如果 `y` 指向目录且 `z` 不指定：会自动用源文件名落到目录下面。

```python
from pathlib import Path

# 先准备一个本地文件
local_traj = "/tmp/traj.json"
Path(local_traj).write_text('{"steps": []}\n', encoding="utf-8")

# y 是目录（相对路径，会拼到 base_url 下）
r1 = store.put(local_traj, "runs/001/")
print("traj url:", r1.url)
print("traj sha256:", r1.sha256)
print("traj bytes:", r1.size_bytes)
```

你可以把 `r1.url` 存到 DB 的 `traj_url` 字段。

### 2) 先把 Python 对象写到本地文件；再 put 到目标文件

```python
import json

local_metric = "/tmp/metric.json"
with open(local_metric, "w", encoding="utf-8") as f:
    json.dump({"pass": True, "score": 0.9}, f, ensure_ascii=False, indent=2)

r2 = store.put(local_metric, "runs/001/metric.json")
print("metric url:", r2.url)
```

你可以把 `r2.url` 存到 DB 的 `metric_url`（如果你有这个字段）或者放到 `extra` 里。

### 3) y 是目录；z 指定文件名

提示：`store.put(x, y, z)` 的 `x` 必须是一个真实存在的本地文件路径。

```python
from pathlib import Path

# x 是本地文件；y 指向目录；z 指定文件名
local_patch = "/tmp/patch.diff"
Path(local_patch).write_text("diff --git a/a.py b/a.py\n...\n", encoding="utf-8")

r3 = store.put(local_patch, "runs/001/", "patch.diff")
print("patch url:", r3.url)
```

你可以把 `r3.url` 存到 DB 的 `patch_url` 字段。

返回值 `PutResult`：
- `url`: 最终写入位置（你应该把它存到 DB 的 `*_url` 字段里）
- `sha256`: 内容哈希（用于去重/校验/追溯）
- `size_bytes`: 写入大小（对 `put()` 会填）

写入语义（重要）：
- 写入是“覆盖”语义：同一个 `relpath` 重复写入会覆盖旧内容
- 会计算 `sha256`：
    - `put()`：对本地源文件内容计算

一致性与原子性：
- 本地（`file://` 或无 scheme）
    - 会自动创建目录
    - 采用临时文件 + `os.replace`，单机上是原子替换（避免写到一半读到半截文件）
- 对象存储（如 `s3://`）
    - MVP 不保证原子性（对象存储的“覆盖写”语义和一致性因后端而异）
    - 如果你需要强一致/防覆盖，建议在上层通过“内容寻址路径（按 sha256 命名）”或“写一次不覆盖”的约定来实现

常见落盘路径建议（非强制）：
- `runs/<run_id>/patch.diff`
- `runs/<run_id>/traj.json`
- `runs/<run_id>/metric.json`

## 读取

你在 DB 里存的是 `PutResult.url`（例如 `traj_url/patch_url`），读取时直接用这个 `url` 即可。

### 1) 读取为 bytes（推荐默认）

```python
with store.open(r1.url, "rb") as f:
    data = f.read()

print(type(data), len(data))  # <class 'bytes'> ...
```

适用场景：patch diff、二进制文件、或者你不确定编码/内容格式。

### 2) 读取为 str（文本）

当你明确知道内容是文本（例如 `.txt/.md/.diff`），可以用文本模式。

```python
with store.open(r1.url, "r") as f:
    text = f.read()

print(text[:200])
```

注意：`fsspec.open(..., "r")` 的编码处理和具体 filesystem backend 有关；如果你遇到编码问题，稳妥方式是先用 `"rb"` 读 bytes，再自己解码：

```python
with store.open(r1.url, "rb") as f:
    text = f.read().decode("utf-8")
```

### 3) 读取为 JSON（dict/list）

```python
import json

with store.open(r1.url, "rb") as f:
    obj = json.loads(f.read().decode("utf-8"))

print(type(obj), obj)
```

### 4) 和 DB 联动：从表里取 url 再读取

```python
from agentfabric import DB, ArtifactStore
import json

db = DB(
    url="postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME",
    config_path="examples/acebench_schema.yaml",
)
store = ArtifactStore(base_url="file:///tmp/agentfabric-artifacts")

# 假设 ace_traj.traj_url 里存的是 store.put(...) 返回的 url
rows = db.query(
    "ace_traj",
    where={"instance_id": "ins_001", "attempt": 0},
    limit=1,
)
row = rows[0]

traj_url = row.traj_url  # 或者 row.as_dict()["traj_url"]
with store.open(traj_url, "rb") as f:
    traj = json.loads(f.read().decode("utf-8"))

print("loaded steps:", len(traj.get("steps", [])))
```

说明：
- `open(url, mode)` 是对 `fsspec.open(...).open()` 的轻封装
- 一般建议默认用 `mode="rb"`（bytes）最稳妥；文本/JSON 的解码与解析由调用方显式控制

## 和 DB 联动的完整例子

典型模式是：先写 artifact 拿到 URL，再把 URL 写进 DB。

```python
from agentfabric import DB, ArtifactStore

db = DB(
    url="postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME",
    config_path="examples/acebench_schema.yaml",
)

store = ArtifactStore(base_url="file:///tmp/agentfabric-artifacts")

# 1) 写入 patch/traj
import json
from pathlib import Path

local_patch = "/tmp/patch.diff"
Path(local_patch).write_text("diff --git ...\n", encoding="utf-8")
patch = store.put(local_patch, "runs/001/patch.diff")

local_traj = "/tmp/traj.json"
with open(local_traj, "w", encoding="utf-8") as f:
    json.dump({"steps": []}, f, ensure_ascii=False, indent=2)
traj = store.put(local_traj, "runs/001/traj.json")

# 2) 把 URL 回填到 ace_traj 表
Traj = db.models["ace_traj"]
row = Traj(
    instance_id="ins_001",
    gold_patch_cov=0.42,
    agent="my_agent",
    model="gpt-5.2",
    attempt=0,
    patch_url=patch.url,
    traj_url=traj.url,
)
db.upsert("ace_traj", row)
```
