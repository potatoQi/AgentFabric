# AgentFabric 使用说明

这份文档说明如何使用 `agentfabric`：用 YAML 注册 schema、创建表、写入/查询数据、以及管理 artifacts。

## 文档导航

- [快速开始](quickstart.md)
- [Schema YAML 规范](schema-yaml.md)
- [DB API（增删改查 / upsert）](db-api.md)
- [Filter DSL（where/limit/offset）](filter-dsl.md)
- [ArtifactStore（冷资源 URL）](artifacts.md)
- [ACE-Bench 两表示例](acebench.md)

## 运行测试

- 纯单元测试（不需要 Postgres）：`uv run pytest -q`
- 黑盒 Postgres 端到端测试（自动启动 docker Postgres）：`bash scripts/run_blackbox_postgres_tests.sh`
	- 默认使用“随机容器名 + 自动挑空闲端口”避免冲突；可用环境变量覆盖（例如 `AGENTFABRIC_PG_PORT` / `AGENTFABRIC_PG_USER`）
	- 调试时可设置 `AGENTFABRIC_PG_KEEP=1` 让容器跑完不自动 stop
