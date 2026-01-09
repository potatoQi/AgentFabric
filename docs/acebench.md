# ACE-Bench 两表示例

本仓库提供了 ACE-Bench 的 schema 示例：

- `examples/acebench_schema.yaml`

## 表结构要点

- `ace_instance`
  - 复合主键：`(instance_id, gold_patch_cov)`
  - `f2p/p2p`：`list[text]`（映射到 Postgres `text[]`）

- `ace_traj`
  - 外键：`(instance_id, gold_patch_cov) -> ace_instance(instance_id, gold_patch_cov)`
  - 主键（你确认的组合）：`(agent, model, instance_id, attempt, gold_patch_cov)`

## 为什么 `ace_traj` 需要存 `instance_id/gold_patch_cov`

如果外键引用的是这两列，那么这两列必须作为 `ace_traj` 的实际列存在：外键约束就是“本表列”引用“他表列”。

如果你希望 `ace_traj` 不重复存这两列，常见做法是让 `ace_instance` 额外有一个单列主键（例如 `instance_pk uuid`），`ace_traj` 只存 `instance_pk` 外键。
