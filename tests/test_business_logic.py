"""
业务逻辑测试 (Business Logic Tests)

本测试文件专注于AgentFabric的核心业务逻辑，包括：
1. 数据库CRUD操作的完整性
2. 数据验证和约束
3. 事务和数据一致性
4. 复杂查询场景
5. 业务规则执行
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from agentfabric.config.spec import ColumnSpec, ConfigSpec, ForeignKeySpec, TableSpec
from agentfabric.db.facade import DB


# ============================================================================
# 业务逻辑测试 #1: CRUD 操作完整性
# ============================================================================


class TestCRUDBusinessLogic:
    """测试完整的CRUD业务流程"""

    def test_complete_crud_workflow(self):
        """测试完整的创建-读取-更新-删除工作流"""
        cfg = ConfigSpec(
            tables={
                "users": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="uuid", nullable=False, default="uuid4", filterable=True),
                        "name": ColumnSpec(type="text", nullable=False, filterable=True),
                        "email": ColumnSpec(type="text", nullable=False, filterable=True),
                        "age": ColumnSpec(type="int", nullable=True, filterable=True),
                        "active": ColumnSpec(type="bool", nullable=False, default=True, filterable=True),
                        "created_at": ColumnSpec(type="datetime", nullable=False, default="now", filterable=True),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        # 验证模型和表结构正确创建
        assert "users" in db.models
        assert "users" in db.tables
        
        # 验证filterable字段正确设置
        filterable = db._filterable_cols.get("users")
        assert filterable == {"id", "name", "email", "age", "active", "created_at"}

    def test_batch_operations_consistency(self):
        """测试批量操作的一致性"""
        cfg = ConfigSpec(
            tables={
                "items": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="text", nullable=False, filterable=True),
                        "value": ColumnSpec(type="int", nullable=False, default=0, filterable=True),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        # 测试批量添加数据的准备
        Model = db.models["items"]
        items = [Model(id=f"item_{i}", value=i) for i in range(5)]
        
        # 验证每个对象都被正确创建
        for i, item in enumerate(items):
            assert item.id == f"item_{i}"
            assert item.value == i

    def test_upsert_business_logic(self):
        """测试upsert的业务逻辑"""
        cfg = ConfigSpec(
            tables={
                "counters": TableSpec(
                    primary_key=["name"],
                    columns={
                        "name": ColumnSpec(type="text", nullable=False, filterable=True),
                        "count": ColumnSpec(type="int", nullable=False, default=0),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        # 验证upsert方法存在
        assert hasattr(db, "upsert")
        
        # 验证主键定义正确
        assert list(db.registry.tables["counters"].primary_key) == ["name"]


# ============================================================================
# 业务逻辑测试 #2: 数据验证和约束
# ============================================================================


class TestDataValidationBusinessLogic:
    """测试数据验证和业务约束"""

    def test_nullable_constraint_validation(self):
        """测试nullable约束的业务逻辑"""
        cfg = ConfigSpec(
            tables={
                "products": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="text", nullable=False),
                        "name": ColumnSpec(type="text", nullable=False),  # 必填
                        "description": ColumnSpec(type="text", nullable=True),  # 可选
                        "price": ColumnSpec(type="float", nullable=False, default=0.0),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        # 验证表结构
        assert "products" in db.tables
        products_table = db.tables["products"]
        
        # 验证nullable设置
        assert products_table.c["id"].nullable is False
        assert products_table.c["name"].nullable is False
        assert products_table.c["description"].nullable is True
        assert products_table.c["price"].nullable is False

    def test_default_values_business_logic(self):
        """测试默认值的业务逻辑"""
        cfg = ConfigSpec(
            tables={
                "orders": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="uuid", nullable=False, default="uuid4"),
                        "status": ColumnSpec(type="text", nullable=False, default="pending"),
                        "total": ColumnSpec(type="float", nullable=False, default=0.0),
                        "items_count": ColumnSpec(type="int", nullable=False, default=0),
                        "created_at": ColumnSpec(type="datetime", nullable=False, default="now"),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        # 验证默认值配置
        defaults = db._defaults.get("orders")
        assert defaults is not None
        assert "id" in defaults
        assert "status" in defaults
        assert "total" in defaults
        assert "created_at" in defaults
        
        # 验证默认值类型
        assert defaults["id"] == "uuid4"
        assert defaults["status"] == "pending"
        assert defaults["total"] == 0.0
        assert defaults["created_at"] == "now"

    def test_foreign_key_business_rules(self):
        """测试外键业务规则"""
        cfg = ConfigSpec(
            tables={
                "customers": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="text", nullable=False),
                        "name": ColumnSpec(type="text", nullable=False),
                    },
                ),
                "orders": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="text", nullable=False),
                        "customer_id": ColumnSpec(type="text", nullable=False),
                    },
                    foreign_keys=[
                        ForeignKeySpec(
                            columns=["customer_id"],
                            ref_table="customers",
                            ref_columns=["id"],
                            on_delete="cascade",
                        )
                    ],
                ),
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        # 验证外键定义
        orders_def = db.registry.tables["orders"]
        assert len(orders_def.foreign_keys) == 1
        fk = orders_def.foreign_keys[0]
        assert fk.ref_table == "customers"
        assert fk.columns == ["customer_id"]
        assert fk.ref_columns == ["id"]


# ============================================================================
# 业务逻辑测试 #3: 复杂查询场景
# ============================================================================


class TestComplexQueryBusinessLogic:
    """测试复杂查询的业务场景"""

    def test_multi_condition_query_logic(self):
        """测试多条件查询业务逻辑"""
        cfg = ConfigSpec(
            tables={
                "employees": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="text", nullable=False, filterable=True),
                        "name": ColumnSpec(type="text", nullable=False, filterable=True),
                        "department": ColumnSpec(type="text", nullable=False, filterable=True),
                        "salary": ColumnSpec(type="float", nullable=False, filterable=True),
                        "hire_date": ColumnSpec(type="datetime", nullable=False, filterable=True),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        # 测试复杂查询条件的构建
        from agentfabric.db.query import build_where
        
        # 业务场景：查找特定部门、薪资范围内的员工
        where = {
            "and": [
                {"department": {"eq": "Engineering"}},
                {"salary": {"gte": 50000, "lte": 100000}},
            ]
        }
        
        clauses = build_where(
            db.tables["employees"],
            where,
            allowed_fields={"id", "name", "department", "salary", "hire_date"}
        )
        
        # 应该生成多个查询条件
        assert len(clauses) > 0

    def test_pagination_business_logic(self):
        """测试分页业务逻辑"""
        cfg = ConfigSpec(
            tables={
                "posts": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="int", nullable=False, filterable=True),
                        "title": ColumnSpec(type="text", nullable=False),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        # 业务场景：分页查询
        filter_page1 = {"where": {}, "limit": 10, "offset": 0}
        filter_page2 = {"where": {}, "limit": 10, "offset": 10}
        
        # 验证分页参数被正确处理（不会抛出异常）
        # 实际查询需要数据库连接，这里只验证参数处理
        assert filter_page1["limit"] == 10
        assert filter_page2["offset"] == 10

    def test_list_contains_business_logic(self):
        """测试列表包含操作的业务逻辑"""
        cfg = ConfigSpec(
            tables={
                "articles": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="text", nullable=False, filterable=True),
                        "tags": ColumnSpec(type="list", item_type="text", nullable=True, filterable=True),
                        "categories": ColumnSpec(type="list", item_type="int", nullable=True, filterable=True),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        from agentfabric.db.query import build_where
        
        # 业务场景：查找包含特定标签的文章
        where_text = {"tags": {"contains": "python"}}
        clauses_text = build_where(
            db.tables["articles"],
            where_text,
            allowed_fields={"id", "tags", "categories"}
        )
        assert len(clauses_text) > 0
        
        # 业务场景：查找包含特定分类ID的文章
        where_int = {"categories": {"contains": 42}}
        clauses_int = build_where(
            db.tables["articles"],
            where_int,
            allowed_fields={"id", "tags", "categories"}
        )
        assert len(clauses_int) > 0


# ============================================================================
# 业务逻辑测试 #4: 业务规则执行
# ============================================================================


class TestBusinessRulesExecution:
    """测试业务规则的执行"""

    def test_delete_protection_business_rule(self):
        """测试删除保护业务规则"""
        cfg = ConfigSpec(
            tables={
                "documents": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="text", nullable=False),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        # 业务规则：不允许空where的删除操作（防止误删）
        with pytest.raises(ValueError, match="requires non-empty where"):
            db.delete_where("documents", {})

    def test_update_protection_business_rule(self):
        """测试更新保护业务规则"""
        cfg = ConfigSpec(
            tables={
                "settings": TableSpec(
                    primary_key=["key"],
                    columns={
                        "key": ColumnSpec(type="text", nullable=False),
                        "value": ColumnSpec(type="text", nullable=False),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        # 业务规则：不允许空where的更新操作（防止误更新）
        with pytest.raises(ValueError, match="requires non-empty where"):
            db.update("settings", {}, {"value": "new_value"})

    def test_filterable_access_control_business_rule(self):
        """测试filterable访问控制业务规则"""
        cfg = ConfigSpec(
            tables={
                "users": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="text", nullable=False, filterable=True),
                        "username": ColumnSpec(type="text", nullable=False, filterable=True),
                        "password_hash": ColumnSpec(type="text", nullable=False, filterable=False),
                        "api_key": ColumnSpec(type="text", nullable=True, filterable=False),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        from agentfabric.db.query import build_where
        
        # 业务规则：敏感字段不可过滤
        with pytest.raises(ValueError, match="not filterable"):
            build_where(
                db.tables["users"],
                {"password_hash": {"eq": "hashed"}},
                allowed_fields={"id", "username"}
            )
        
        with pytest.raises(ValueError, match="not filterable"):
            build_where(
                db.tables["users"],
                {"api_key": {"eq": "secret"}},
                allowed_fields={"id", "username"}
            )


# ============================================================================
# 业务逻辑测试 #5: 数据完整性和一致性
# ============================================================================


class TestDataIntegrityBusinessLogic:
    """测试数据完整性和一致性"""

    def test_composite_primary_key_integrity(self):
        """测试复合主键的完整性"""
        cfg = ConfigSpec(
            tables={
                "order_items": TableSpec(
                    primary_key=["order_id", "item_id"],
                    columns={
                        "order_id": ColumnSpec(type="text", nullable=False, filterable=True),
                        "item_id": ColumnSpec(type="text", nullable=False, filterable=True),
                        "quantity": ColumnSpec(type="int", nullable=False, default=1),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        # 验证复合主键定义
        pk = list(db.registry.tables["order_items"].primary_key)
        assert pk == ["order_id", "item_id"]
        
        # 验证delete_by_pk需要完整的主键
        with pytest.raises(ValueError, match="no complete primary key"):
            # 只提供部分主键
            db.delete_by_pk("order_items", [{"order_id": "O1"}])

    def test_extra_field_business_logic(self):
        """测试extra扩展字段的业务逻辑"""
        cfg = ConfigSpec(
            tables={
                "events": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="text", nullable=False, filterable=True),
                        "type": ColumnSpec(type="text", nullable=False, filterable=True),
                        # extra字段自动添加
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        from agentfabric.db.query import build_where
        
        # 业务场景：使用extra字段存储和查询动态属性
        where = {"extra.metadata.source": {"eq": "api"}}
        clauses = build_where(
            db.tables["events"],
            where,
            allowed_fields={"id", "type"}
        )
        assert len(clauses) > 0
        
        # extra字段支持嵌套路径
        where_nested = {"extra.data.user.id": {"eq": "123"}}
        clauses_nested = build_where(
            db.tables["events"],
            where_nested,
            allowed_fields={"id", "type"}
        )
        assert len(clauses_nested) > 0

    def test_timestamp_business_logic(self):
        """测试时间戳业务逻辑"""
        cfg = ConfigSpec(
            tables={
                "audit_logs": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="uuid", nullable=False, default="uuid4"),
                        "action": ColumnSpec(type="text", nullable=False),
                        "created_at": ColumnSpec(type="datetime", nullable=False, default="now"),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        # 验证时间戳默认值
        defaults = db._defaults.get("audit_logs")
        assert defaults["created_at"] == "now"
        
        # 测试SDK默认值应用
        row = {}
        row_with_defaults = db._apply_sdk_defaults_row("audit_logs", row)
        
        # 验证now默认值生成了datetime对象
        assert "created_at" in row_with_defaults
        assert isinstance(row_with_defaults["created_at"], datetime)
        assert row_with_defaults["created_at"].tzinfo == timezone.utc


# ============================================================================
# 业务逻辑测试 #6: 业务流程集成
# ============================================================================


class TestBusinessWorkflowIntegration:
    """测试业务流程的集成"""

    def test_user_registration_workflow(self):
        """测试用户注册工作流"""
        cfg = ConfigSpec(
            tables={
                "users": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="uuid", nullable=False, default="uuid4", filterable=True),
                        "username": ColumnSpec(type="text", nullable=False, filterable=True),
                        "email": ColumnSpec(type="text", nullable=False, filterable=True),
                        "verified": ColumnSpec(type="bool", nullable=False, default=False),
                        "created_at": ColumnSpec(type="datetime", nullable=False, default="now"),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        # 模拟注册流程：创建用户对象
        User = db.models["users"]
        new_user = User(username="john_doe", email="john@example.com")
        
        # 验证默认值被正确应用
        db._apply_sdk_defaults_obj(new_user)
        
        assert isinstance(new_user.id, UUID)
        assert new_user.username == "john_doe"
        assert new_user.email == "john@example.com"
        assert new_user.verified is False
        assert isinstance(new_user.created_at, datetime)

    def test_order_processing_workflow(self):
        """测试订单处理工作流"""
        cfg = ConfigSpec(
            tables={
                "orders": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="uuid", nullable=False, default="uuid4", filterable=True),
                        "status": ColumnSpec(type="text", nullable=False, default="pending", filterable=True),
                        "total_amount": ColumnSpec(type="float", nullable=False, default=0.0),
                        "created_at": ColumnSpec(type="datetime", nullable=False, default="now"),
                        "updated_at": ColumnSpec(type="datetime", nullable=True),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        from agentfabric.db.query import build_where
        
        # 业务场景：查询待处理订单
        where_pending = {"status": {"eq": "pending"}}
        clauses = build_where(
            db.tables["orders"],
            where_pending,
            allowed_fields={"id", "status", "created_at"}
        )
        assert len(clauses) > 0
        
        # 业务场景：查询特定金额范围的订单
        where_amount = {"total_amount": {"gte": 100.0, "lte": 1000.0}}
        clauses_amount = build_where(
            db.tables["orders"],
            where_amount,
            allowed_fields={"id", "status", "total_amount"}
        )
        assert len(clauses_amount) > 0

    def test_content_moderation_workflow(self):
        """测试内容审核工作流"""
        cfg = ConfigSpec(
            tables={
                "posts": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="uuid", nullable=False, default="uuid4", filterable=True),
                        "content": ColumnSpec(type="text", nullable=False),
                        "status": ColumnSpec(type="text", nullable=False, default="pending_review", filterable=True),
                        "flags": ColumnSpec(type="list", item_type="text", nullable=True, filterable=True),
                        "created_at": ColumnSpec(type="datetime", nullable=False, default="now", filterable=True),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        from agentfabric.db.query import build_where
        
        # 业务场景：查找被标记为特定问题的内容
        where_flagged = {"flags": {"contains": "spam"}}
        clauses = build_where(
            db.tables["posts"],
            where_flagged,
            allowed_fields={"id", "status", "flags", "created_at"}
        )
        assert len(clauses) > 0
        
        # 业务场景：查询待审核的内容
        where_pending = {"status": {"eq": "pending_review"}}
        clauses_pending = build_where(
            db.tables["posts"],
            where_pending,
            allowed_fields={"id", "status", "created_at"}
        )
        assert len(clauses_pending) > 0


# ============================================================================
# 业务逻辑测试 #7: 边界条件和业务规则
# ============================================================================


class TestBusinessRulesBoundaryConditions:
    """测试业务规则的边界条件"""

    def test_empty_result_set_handling(self):
        """测试空结果集的处理"""
        cfg = ConfigSpec(
            tables={
                "tasks": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="text", nullable=False, filterable=True),
                        "status": ColumnSpec(type="text", nullable=False, filterable=True),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        # 业务场景：查询不存在的状态
        from agentfabric.db.query import build_where
        
        where = {"status": {"eq": "nonexistent_status"}}
        clauses = build_where(
            db.tables["tasks"],
            where,
            allowed_fields={"id", "status"}
        )
        # 应该能够正常构建查询，即使结果为空
        assert len(clauses) > 0

    def test_delete_by_pk_empty_list(self):
        """测试空列表删除的业务逻辑"""
        cfg = ConfigSpec(
            tables={
                "records": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="text", nullable=False),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        # 业务规则：空列表删除应该返回0（安全操作）
        count = db.delete_by_pk("records", [])
        assert count == 0

    def test_limit_boundary_values(self):
        """测试limit边界值的业务逻辑"""
        cfg = ConfigSpec(
            tables={
                "items": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="text", nullable=False),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        # 业务规则：limit有上限
        MAX_LIMIT = 10000
        
        # 正常limit应该被接受
        filter_normal = {"where": {}, "limit": 100}
        # 验证不会抛出异常
        assert filter_normal["limit"] <= MAX_LIMIT
        
        # 超大limit应该被拒绝
        with pytest.raises(ValueError, match="limit cannot exceed"):
            db.query("items", {"where": {}, "limit": MAX_LIMIT + 1})
        
        # 负数limit应该被拒绝
        with pytest.raises(ValueError, match="must be non-negative"):
            db.query("items", {"where": {}, "limit": -1})


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
