# ArtifactStore API（`agentfabric.ArtifactStore`）

`ArtifactStore` 负责“把本地文件写入某个目标存储位置，并返回可回读的 URL”。

当前实现特点：

- 统一主入口：`put(x, y, z=None)`
- `x` **只能是本地已存在文件路径**
- 当 `y` 明确指向文件时，会强制校验 `x` 与 `y` 的后缀一致
- 支持 `file://` 与其他 fsspec 支持的 scheme（如 `s3://`，取决于环境）
- 本地写入（file/本地路径）采用原子写（临时文件 + `os.replace`）

## 构造函数

```python
from agentfabric import ArtifactStore

store = ArtifactStore(base_url: str)
```

- `base_url`：相对路径写入的基准。
  - 例：`file:///tmp/agentfabric_artifacts`
  - 例：`s3://my-bucket/prefix`（需要环境支持）

## 返回结构：`PutResult`

`put*` 方法返回：

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class PutResult:
    url: str
    sha256: str
    size_bytes: int | None = None
```

- `url`：目标对象的可回读 URL
- `sha256`：内容 hash（hex）
- `size_bytes`：写入的字节数（部分实现路径下为 None/或可用）

## 统一写入：`put(x, y, z=None)`

```python
store.put(
    x: str | os.PathLike[str],
    y: str,
    z: str | None = None,
) -> PutResult
```

语义：

- `x`：本地文件路径，必须存在且是文件，否则抛 `FileNotFoundError`。
- `y`：目标路径（可以是相对/绝对；可以指向目录或文件）。
  - 若 `y` 是相对路径，会与 `base_url` 拼接。
  - 若 `y` 指向目录：最终文件名由 `z` 或源文件名推导。
  - 若 `y` 指向文件：最终目标就是该文件。
- `z`：当 `y` 是目录时，可用来指定目标文件名；当 `y` 是文件时会被忽略。

### 目录 vs 文件的判断规则（简化理解）

- `y` 以 `/` 结尾：一定当成目录
- `y` 看起来像文件名（最后一段包含 `.`）：倾向当成文件
- `y` 是绝对本地路径且存在：用真实 `is_dir()` 判定
- 其他情况：尽量按“目录”处理

### 后缀一致性校验

当且仅当 `y` 明确指向文件（例如 `runs/001/patch.diff` 或 `.../a.txt`）时：

- `Path(x).suffix` 必须等于目标文件的 suffix
- 不一致会抛 `ValueError("File extension mismatch: ...")`

示例：

```python
patch = "/tmp/patch.diff"
store.put(patch, "runs/001/patch.diff")  # OK
store.put(patch, "runs/001/patch.txt")   # ValueError
```

### 端到端闭环示例（与 DB 联动）

```python
from agentfabric import DB, ArtifactStore

store = ArtifactStore(base_url="file:///tmp/agentfabric_artifacts")

# 1) put 本地文件
res = store.put("/tmp/patch.diff", "runs/001/patch.diff")

# 2) 写入 DB
Traj = db.models["ace_traj"]
row = Traj(
    instance_id="ins_001",
    gold_patch_cov=0.42,
    agent="agent",
    model="model",
    attempt=0,
    patch_url=res.url,
    extra={"kind": "patch"},
)

db.upsert("ace_traj", row)

# 3) 从 DB 查回 URL，open 读取
got = db.query("ace_traj", {"where": {"attempt": {"eq": 0}}, "limit": 1})
with store.open(got[0].patch_url, "rb") as f:
    content = f.read()
```

## 读取：`open(url, mode="rb")`

```python
store.open(url: str, mode: str = "rb") -> BinaryIO
```

- `url`：通常来自 `PutResult.url` 或 DB 中存储的 URL。
- `mode`：通常用 `"rb"`。

## 原子性与一致性说明

- 本地路径 / `file://`：写入采用临时文件 + `os.replace`，单机上具备原子替换语义。
- 非本地（如对象存储）：当前实现不保证原子性；一致性由底层存储保证。
