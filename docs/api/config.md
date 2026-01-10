# 配置与 YAML

本页已合并到单文件 API 文档

请查看 [docs/api/README.md](README.md)
  - `cascade`：父删除级联删除子
  - `restrict`：父删除被阻止
  - `set_null`：父删除时把子列设为 NULL（要求子列可空）
  - `no_action`/None：不设置 ondelete

## 固定列：`extra`

所有表都会自动追加一列：

- `extra JSONB NOT NULL DEFAULT '{}'::jsonb`

用户无需在 YAML 里声明它。
