# 单元测试要点清单

每条都是一个“单测应该覆盖的要点”，与 `tests/` 下的用例一一对应。

## ArtifactStore

- `put()` 只能接受真实存在的本地文件路径，否则抛 `FileNotFoundError`。
- 当 `y` 是相对目录（以 `/` 结尾）且 `z` 未指定时，目标文件名应自动采用源文件名。
- 当 `y` 是相对文件路径时，若 `x` 与 `y` 后缀不一致应抛 `ValueError`。
- 当 `y` 是相对文件路径时，即使提供了 `z` 也必须忽略并写入到 `y` 指定的文件。
- 当 `y` 是目录且显式给出 `z` 时，目标文件名必须使用 `z`。
- 当 `y` 是绝对文件路径时，`z` 必须被忽略，且同样执行后缀一致性校验。
- 当 `y` 是目录但不以 `/` 结尾且看起来不像文件名时，应仍按“目录”处理并写入到 `y/<源文件名>`。
- 当 `y` 是不存在的绝对目录路径且不以 `/` 结尾时，配合 `z` 也应能正确写入并自动创建目录。
- `base_url` 使用 `file://` scheme 时，`put()` 返回的 URL 与 `open()` 读取应能闭环验证内容一致。

## Filter DSL（build_where）

- `where[field]` 不是 dict 时必须抛 `TypeError`。
- 普通列在提供 `allowed_fields` 时必须强制 filterable 白名单，否则抛 `ValueError`。
- 同一字段可同时写多个算子并以 AND 组合（例如 `gte + lt + ne` 生成 3 个子条件）。
- `in_: []` 必须生成“空结果集”条件（实现上追加 `False`）。
- `nin: []` 必须是 no-op（不产生过滤条件）。
- `is_null: true/false` 必须分别生成 `IS NULL` / `IS NOT NULL` 条件。
- 普通列出现未知算子 key 时应被忽略（仅处理已支持的算子集合）。
- `is_null` 应可与其他算子同时存在并产生多个子条件。
- `extra.*` 只允许文本安全算子集合，遇到 `gt/gte/lt/lte` 等必须抛 `ValueError`。
- `extra.*` 的 `in_: []` / `nin: []` 边界行为应与普通列一致（空结果 / no-op）。

## Config / Schema

- `ColumnSpec(type="list")` 未提供 `item_type` 必须校验失败。
- 非 `list` 类型不允许提供 `item_type`（提供时必须校验失败）。
- `load_config()` 必须能从 YAML 解析出 `ConfigSpec` 并保留关键字段（如 `postgres_schema`、list 的 `item_type`）。
- `SchemaRegistry` 必须校验 primary key 列是否存在，不存在要报错。
- `SchemaRegistry` 必须校验外键引用表/引用列是否存在及列数是否匹配。
- `SchemaBuilder` 必须固定生成 `extra` 列，并按配置顺序生成复合主键列顺序。
- `map_type("list", item_type=...)` 必须返回 Postgres `ARRAY(...)` 类型。
- `ORMModelFactory` 必须把 snake_case 表名转换为 CamelCase 类名（例如 `ace_traj -> AceTraj`）。

## DB Facade（纯逻辑）

- `DB` 初始化时必须预计算每表的 default 规则集合与 filterable 列集合（不需要真实连库即可验证）。
- `DB` 初始化参数必须严格校验（url 为空、config/config_path 同时提供或同时缺失都应报错）。
- `_apply_sdk_defaults_row()` 必须为缺失/None 的列自动补齐 `uuid4/now/字面量 default`。
- `_apply_sdk_defaults_row()` 不得覆盖用户已提供的非空值。
- 字面量 default（尤其是 dict/list）必须用 deepcopy，确保不同 row 之间不会共享可变对象。
- `_apply_sdk_defaults_obj()` 必须对 ORM 实例缺失/None 属性做同样的 default 补齐。
- `_obj_to_dict()` 必须能把 ORM 对象转为 dict 且包含固定的 `extra` 字段。

## In-Out（黑盒 / Postgres，可选）

这些测试需要设置 `AGENTFABRIC_TEST_DB_URL`（或 `DATABASE_URL`）指向一个可用的 Postgres；未设置时应自动 skip。

建议按“覆盖面由小到大”的方式理解黑盒文件：
- `tests/test_inout_postgres_blackbox.py`：最小闭环（建表/写入/查询/update/upsert/artifact url）
- `tests/test_inout_postgres_acebench_yaml_blackbox.py`：使用 `examples/acebench_schema.yaml` 的真实结构（复合 PK/FK、list[text]、RESTRICT 删除语义）
- `tests/test_inout_postgres_stress_blackbox.py`：偏压力与组合行为（批量写入、分页、复杂 where、多次 upsert）
- `tests/test_inout_postgres_artifactstore_combo_blackbox.py`：DB + ArtifactStore 联动的边界与压力（后缀校验、URL 闭环、limit/offset 边界、多条件组合过滤、批量 artifacts 写入/读回）

- `DB.init_schema()` 能在指定 `postgres_schema` 下建表并完成 `add -> query` 的全链路回读。
- 复合主键表能被正确查询定位（`where` 同时命中多个 PK 列）。
- `filterable` 约束在黑盒查询中生效：对非 filterable 列的 where 必须报错。
- `extra.*` 文本过滤在黑盒查询中生效：写入 `extra` 后能用 `extra.key` 的算子查回。
- `update()` 在 where 为空时必须拒绝执行。
- `upsert()` 在主键冲突时必须执行更新并能查回更新后的值。
- `ArtifactStore.put -> DB 存 url -> store.open 读回` 形成端到端闭环，读回内容与写入一致。
- `DB(config_path=...)` 能从 YAML 配置文件启动并完成最小插入/查询回读。
