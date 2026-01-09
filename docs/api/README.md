# API 文档（agentfabric）

本文档覆盖“用户可直接使用”的全部 API：

- 顶层导出：
  - `agentfabric.DB`
  - `agentfabric.ArtifactStore`
  - `agentfabric.load_config`
- 约定与核心数据结构：
  - 配置模型（`agentfabric.config.spec.*`）
  - Filter DSL（`agentfabric.db.query.build_where` 的输入结构）
  - ArtifactStore 的返回结构（`agentfabric.artifacts.store.PutResult`）

> 说明：本仓库并未实现“严格的稳定/弃用策略”。以下文档以当前代码为准，建议你把“只通过顶层导出的符号使用”作为稳定 API 边界。

## 快速索引

- DB：见 [docs/api/db.md](db.md)
- ArtifactStore：见 [docs/api/artifacts.md](artifacts.md)
- 配置/YAML：见 [docs/api/config.md](config.md)
- Filter DSL：见 [docs/api/filter-dsl.md](filter-dsl.md)
- 错误与异常：见 [docs/api/errors.md](errors.md)

## 顶层导入示例

```python
from agentfabric import DB, ArtifactStore, load_config

cfg = load_config("examples/acebench_schema.yaml")

db = DB(
    url="postgresql+psycopg://user:pass@localhost:5432/db",
    config=cfg,
)

db.init_schema()

store = ArtifactStore(base_url="file:///tmp/agentfabric_artifacts")
```
