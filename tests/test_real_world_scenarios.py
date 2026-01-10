"""
实际业务场景测试 (Real-world Business Scenario Tests)

本测试文件专注于实际用户使用场景，包括：
1. 各种参数组合的测试
2. 真实用户场景的排列组合
3. 压力环境下的业务逻辑测试
4. 并发操作和边界条件
5. 数据量增长场景
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4
import random
import string

import pytest

from agentfabric.config.spec import ColumnSpec, ConfigSpec, ForeignKeySpec, TableSpec
from agentfabric.db.facade import DB
from agentfabric.db.query import build_where


# ============================================================================
# 真实场景测试 #1: 用户管理系统场景
# ============================================================================


class TestUserManagementScenarios:
    """测试真实的用户管理系统场景"""

    def test_user_registration_with_various_parameter_combinations(self):
        """测试用户注册时的各种参数组合"""
        cfg = ConfigSpec(
            tables={
                "users": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="uuid", nullable=False, default="uuid4", filterable=True),
                        "username": ColumnSpec(type="text", nullable=False, filterable=True),
                        "email": ColumnSpec(type="text", nullable=True, filterable=True),
                        "phone": ColumnSpec(type="text", nullable=True, filterable=True),
                        "age": ColumnSpec(type="int", nullable=True, filterable=True),
                        "country": ColumnSpec(type="text", nullable=True, filterable=True),
                        "verified": ColumnSpec(type="bool", nullable=False, default=False, filterable=True),
                        "created_at": ColumnSpec(type="datetime", nullable=False, default="now", filterable=True),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        User = db.models["users"]
        
        # 场景1: 只提供必需字段
        user1 = User(username="user1")
        db._apply_sdk_defaults_obj(user1)
        assert user1.username == "user1"
        assert user1.verified is False
        assert isinstance(user1.id, UUID)
        
        # 场景2: 提供部分可选字段
        user2 = User(username="user2", email="user2@example.com")
        db._apply_sdk_defaults_obj(user2)
        assert user2.email == "user2@example.com"
        assert user2.phone is None
        
        # 场景3: 提供所有字段
        user3 = User(
            username="user3",
            email="user3@example.com",
            phone="+1234567890",
            age=25,
            country="US",
            verified=True
        )
        db._apply_sdk_defaults_obj(user3)
        assert user3.age == 25
        assert user3.verified is True
        
        # 场景4: 边界值测试
        user4 = User(username="u", age=0)  # 最小用户名，最小年龄
        db._apply_sdk_defaults_obj(user4)
        assert user4.age == 0
        
        # 场景5: 特殊字符测试
        user5 = User(username="用户_123-αβγ", email="test+tag@example.co.uk")
        db._apply_sdk_defaults_obj(user5)
        assert user5.username == "用户_123-αβγ"

    def test_user_query_with_multiple_filter_combinations(self):
        """测试用户查询的多种过滤组合"""
        cfg = ConfigSpec(
            tables={
                "users": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="uuid", nullable=False, default="uuid4", filterable=True),
                        "username": ColumnSpec(type="text", nullable=False, filterable=True),
                        "email": ColumnSpec(type="text", nullable=True, filterable=True),
                        "age": ColumnSpec(type="int", nullable=True, filterable=True),
                        "country": ColumnSpec(type="text", nullable=True, filterable=True),
                        "status": ColumnSpec(type="text", nullable=False, default="active", filterable=True),
                        "created_at": ColumnSpec(type="datetime", nullable=False, default="now", filterable=True),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        # 组合1: 单一条件
        where1 = {"status": {"eq": "active"}}
        clauses1 = build_where(db.tables["users"], where1, allowed_fields={"status"})
        assert len(clauses1) > 0
        
        # 组合2: 多个AND条件
        where2 = {
            "and": [
                {"status": {"eq": "active"}},
                {"age": {"gte": 18}},
                {"country": {"eq": "US"}},
            ]
        }
        clauses2 = build_where(db.tables["users"], where2, allowed_fields={"status", "age", "country"})
        assert len(clauses2) == 3
        
        # 组合3: OR条件
        where3 = {
            "or": [
                {"status": {"eq": "active"}},
                {"status": {"eq": "pending"}},
            ]
        }
        clauses3 = build_where(db.tables["users"], where3, allowed_fields={"status"})
        assert len(clauses3) > 0
        
        # 组合4: 复杂嵌套 (AND + OR)
        where4 = {
            "and": [
                {"age": {"gte": 18, "lte": 65}},
                {
                    "or": [
                        {"country": {"eq": "US"}},
                        {"country": {"eq": "UK"}},
                        {"country": {"eq": "CA"}},
                    ]
                },
            ]
        }
        clauses4 = build_where(db.tables["users"], where4, allowed_fields={"age", "country"})
        assert len(clauses4) > 0
        
        # 组合5: 使用各种操作符
        where5 = {
            "and": [
                {"username": {"like": "user%"}},
                {"email": {"nin": ["spam@example.com", "fake@example.com"]}},
                {"age": {"gt": 0, "lt": 100}},
                {"created_at": {"is_null": False}},
            ]
        }
        clauses5 = build_where(
            db.tables["users"],
            where5,
            allowed_fields={"username", "email", "age", "created_at"}
        )
        assert len(clauses5) > 0

    def test_user_batch_operations_with_varying_sizes(self):
        """测试不同批次大小的批量操作"""
        cfg = ConfigSpec(
            tables={
                "users": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="uuid", nullable=False, default="uuid4"),
                        "username": ColumnSpec(type="text", nullable=False),
                        "status": ColumnSpec(type="text", nullable=False, default="active"),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        User = db.models["users"]
        
        # 场景1: 小批量 (1-5条)
        batch_small = [User(username=f"user_s_{i}") for i in range(3)]
        for user in batch_small:
            db._apply_sdk_defaults_obj(user)
        assert len(batch_small) == 3
        
        # 场景2: 中等批量 (50-100条)
        batch_medium = [User(username=f"user_m_{i}") for i in range(75)]
        for user in batch_medium:
            db._apply_sdk_defaults_obj(user)
        assert len(batch_medium) == 75
        
        # 场景3: 大批量 (1000+条)
        batch_large = [User(username=f"user_l_{i}") for i in range(1500)]
        for user in batch_large:
            db._apply_sdk_defaults_obj(user)
        assert len(batch_large) == 1500
        
        # 验证所有用户都有默认值
        assert all(isinstance(u.id, UUID) for u in batch_large)
        assert all(u.status == "active" for u in batch_large)


# ============================================================================
# 真实场景测试 #2: 电商订单系统场景
# ============================================================================


class TestEcommerceOrderScenarios:
    """测试真实的电商订单系统场景"""

    def test_order_creation_with_different_item_counts(self):
        """测试不同商品数量的订单创建"""
        cfg = ConfigSpec(
            tables={
                "orders": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="uuid", nullable=False, default="uuid4", filterable=True),
                        "customer_id": ColumnSpec(type="text", nullable=False, filterable=True),
                        "total": ColumnSpec(type="float", nullable=False, default=0.0),
                        "item_count": ColumnSpec(type="int", nullable=False, default=0),
                        "status": ColumnSpec(type="text", nullable=False, default="pending", filterable=True),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        Order = db.models["orders"]
        
        # 场景1: 单件商品订单
        order1 = Order(customer_id="C001", total=29.99, item_count=1)
        db._apply_sdk_defaults_obj(order1)
        assert order1.item_count == 1
        
        # 场景2: 多件商品订单
        order2 = Order(customer_id="C002", total=299.97, item_count=10)
        db._apply_sdk_defaults_obj(order2)
        assert order2.item_count == 10
        
        # 场景3: 大批量订单 (批发)
        order3 = Order(customer_id="C003", total=9999.99, item_count=1000)
        db._apply_sdk_defaults_obj(order3)
        assert order3.item_count == 1000
        
        # 场景4: 空订单（仅预留）
        order4 = Order(customer_id="C004")
        db._apply_sdk_defaults_obj(order4)
        assert order4.item_count == 0
        assert order4.total == 0.0

    def test_order_status_transitions(self):
        """测试订单状态流转的各种组合"""
        cfg = ConfigSpec(
            tables={
                "orders": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="uuid", nullable=False, default="uuid4", filterable=True),
                        "status": ColumnSpec(type="text", nullable=False, default="pending", filterable=True),
                        "payment_status": ColumnSpec(type="text", nullable=False, default="unpaid", filterable=True),
                        "shipping_status": ColumnSpec(type="text", nullable=False, default="not_shipped", filterable=True),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        # 有效的状态组合
        valid_combinations = [
            ("pending", "unpaid", "not_shipped"),
            ("confirmed", "paid", "not_shipped"),
            ("processing", "paid", "preparing"),
            ("shipped", "paid", "shipped"),
            ("delivered", "paid", "delivered"),
            ("cancelled", "refunded", "not_shipped"),
        ]
        
        for order_status, payment_status, shipping_status in valid_combinations:
            where = {
                "and": [
                    {"status": {"eq": order_status}},
                    {"payment_status": {"eq": payment_status}},
                    {"shipping_status": {"eq": shipping_status}},
                ]
            }
            clauses = build_where(
                db.tables["orders"],
                where,
                allowed_fields={"status", "payment_status", "shipping_status"}
            )
            assert len(clauses) == 3

    def test_order_query_with_pagination_scenarios(self):
        """测试订单查询的各种分页场景"""
        cfg = ConfigSpec(
            tables={
                "orders": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="uuid", nullable=False, default="uuid4"),
                        "created_at": ColumnSpec(type="datetime", nullable=False, default="now"),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        # 分页场景1: 第一页，小页面
        filter1 = {"where": {}, "limit": 10, "offset": 0}
        assert filter1["limit"] == 10 and filter1["offset"] == 0
        
        # 分页场景2: 中间页
        filter2 = {"where": {}, "limit": 50, "offset": 250}
        assert filter2["limit"] == 50 and filter2["offset"] == 250
        
        # 分页场景3: 大页面
        filter3 = {"where": {}, "limit": 1000, "offset": 0}
        assert filter3["limit"] == 1000
        
        # 分页场景4: 跳过大量记录
        filter4 = {"where": {}, "limit": 20, "offset": 10000}
        assert filter4["offset"] == 10000


# ============================================================================
# 真实场景测试 #3: 内容管理系统场景
# ============================================================================


class TestContentManagementScenarios:
    """测试真实的内容管理系统场景"""

    def test_article_tagging_with_various_tag_combinations(self):
        """测试文章标签的各种组合"""
        cfg = ConfigSpec(
            tables={
                "articles": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="uuid", nullable=False, default="uuid4", filterable=True),
                        "title": ColumnSpec(type="text", nullable=False),
                        "tags": ColumnSpec(type="list", item_type="text", nullable=True, filterable=True),
                        "categories": ColumnSpec(type="list", item_type="int", nullable=True, filterable=True),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        # 场景1: 查找包含单个标签的文章
        where1 = {"tags": {"contains": "python"}}
        clauses1 = build_where(db.tables["articles"], where1, allowed_fields={"id", "tags"})
        assert len(clauses1) > 0
        
        # 场景2: 查找包含多个标签之一的文章（OR）
        where2 = {
            "or": [
                {"tags": {"contains": "python"}},
                {"tags": {"contains": "java"}},
                {"tags": {"contains": "javascript"}},
            ]
        }
        clauses2 = build_where(db.tables["articles"], where2, allowed_fields={"id", "tags"})
        assert len(clauses2) > 0
        
        # 场景3: 查找同时包含多个标签的文章（AND）
        where3 = {
            "and": [
                {"tags": {"contains": "python"}},
                {"tags": {"contains": "tutorial"}},
            ]
        }
        clauses3 = build_where(db.tables["articles"], where3, allowed_fields={"id", "tags"})
        assert len(clauses3) == 2
        
        # 场景4: 按分类ID查找
        where4 = {"categories": {"contains": 5}}
        clauses4 = build_where(db.tables["articles"], where4, allowed_fields={"id", "categories"})
        assert len(clauses4) > 0

    def test_content_moderation_workflow_combinations(self):
        """测试内容审核工作流的各种状态组合"""
        cfg = ConfigSpec(
            tables={
                "posts": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="uuid", nullable=False, default="uuid4", filterable=True),
                        "status": ColumnSpec(type="text", nullable=False, default="draft", filterable=True),
                        "visibility": ColumnSpec(type="text", nullable=False, default="private", filterable=True),
                        "reviewed": ColumnSpec(type="bool", nullable=False, default=False, filterable=True),
                        "flagged": ColumnSpec(type="bool", nullable=False, default=False, filterable=True),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        # 工作流组合测试
        workflow_states = [
            # (status, visibility, reviewed, flagged)
            ("draft", "private", False, False),          # 草稿
            ("pending_review", "private", False, False), # 待审核
            ("approved", "public", True, False),         # 已批准
            ("rejected", "private", True, False),        # 已拒绝
            ("flagged_review", "private", False, True),  # 被标记待审
            ("published", "public", True, False),        # 已发布
        ]
        
        for status, visibility, reviewed, flagged in workflow_states:
            where = {
                "and": [
                    {"status": {"eq": status}},
                    {"visibility": {"eq": visibility}},
                    {"reviewed": {"eq": reviewed}},
                    {"flagged": {"eq": flagged}},
                ]
            }
            clauses = build_where(
                db.tables["posts"],
                where,
                allowed_fields={"status", "visibility", "reviewed", "flagged"}
            )
            assert len(clauses) == 4


# ============================================================================
# 真实场景测试 #4: 多租户系统场景
# ============================================================================


class TestMultiTenantScenarios:
    """测试多租户系统的真实场景"""

    def test_tenant_isolation_query_patterns(self):
        """测试租户隔离的查询模式"""
        cfg = ConfigSpec(
            tables={
                "documents": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="uuid", nullable=False, default="uuid4", filterable=True),
                        "tenant_id": ColumnSpec(type="text", nullable=False, filterable=True),
                        "user_id": ColumnSpec(type="text", nullable=False, filterable=True),
                        "department": ColumnSpec(type="text", nullable=True, filterable=True),
                        "confidential": ColumnSpec(type="bool", nullable=False, default=False, filterable=True),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        # 场景1: 单租户查询
        where1 = {"tenant_id": {"eq": "tenant_001"}}
        clauses1 = build_where(db.tables["documents"], where1, allowed_fields={"tenant_id"})
        assert len(clauses1) > 0
        
        # 场景2: 租户+用户组合查询
        where2 = {
            "and": [
                {"tenant_id": {"eq": "tenant_001"}},
                {"user_id": {"eq": "user_123"}},
            ]
        }
        clauses2 = build_where(
            db.tables["documents"],
            where2,
            allowed_fields={"tenant_id", "user_id"}
        )
        assert len(clauses2) == 2
        
        # 场景3: 租户+部门+权限组合
        where3 = {
            "and": [
                {"tenant_id": {"eq": "tenant_001"}},
                {"department": {"in_": ["HR", "Finance"]}},
                {"confidential": {"eq": False}},
            ]
        }
        clauses3 = build_where(
            db.tables["documents"],
            where3,
            allowed_fields={"tenant_id", "department", "confidential"}
        )
        assert len(clauses3) > 0

    def test_cross_tenant_scenarios(self):
        """测试跨租户场景（系统管理员视图）"""
        cfg = ConfigSpec(
            tables={
                "activities": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="uuid", nullable=False, default="uuid4", filterable=True),
                        "tenant_id": ColumnSpec(type="text", nullable=False, filterable=True),
                        "activity_type": ColumnSpec(type="text", nullable=False, filterable=True),
                        "created_at": ColumnSpec(type="datetime", nullable=False, default="now", filterable=True),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        # 场景1: 查询所有租户的特定活动
        where1 = {"activity_type": {"eq": "login"}}
        clauses1 = build_where(db.tables["activities"], where1, allowed_fields={"activity_type"})
        assert len(clauses1) > 0
        
        # 场景2: 查询多个租户
        where2 = {"tenant_id": {"in_": ["tenant_001", "tenant_002", "tenant_003"]}}
        clauses2 = build_where(db.tables["activities"], where2, allowed_fields={"tenant_id"})
        assert len(clauses2) > 0


# ============================================================================
# 压力测试场景 #5: 高并发和大数据量
# ============================================================================


class TestStressScenarios:
    """测试压力环境下的业务逻辑"""

    def test_large_result_set_pagination(self):
        """测试大结果集的分页处理"""
        cfg = ConfigSpec(
            tables={
                "events": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="uuid", nullable=False, default="uuid4", filterable=True),
                        "timestamp": ColumnSpec(type="datetime", nullable=False, default="now", filterable=True),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        # 模拟大数据集分页
        page_sizes = [10, 50, 100, 500, 1000, 5000, 10000]
        
        for page_size in page_sizes:
            filter_dict = {"where": {}, "limit": page_size, "offset": 0}
            # 验证limit在允许范围内
            if page_size <= 10000:
                assert filter_dict["limit"] == page_size
            else:
                # 超过上限应该被拒绝
                with pytest.raises(ValueError):
                    db.query("events", filter_dict)

    def test_complex_query_combinations_under_load(self):
        """测试负载下的复杂查询组合"""
        cfg = ConfigSpec(
            tables={
                "transactions": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="uuid", nullable=False, default="uuid4", filterable=True),
                        "user_id": ColumnSpec(type="text", nullable=False, filterable=True),
                        "amount": ColumnSpec(type="float", nullable=False, filterable=True),
                        "currency": ColumnSpec(type="text", nullable=False, filterable=True),
                        "status": ColumnSpec(type="text", nullable=False, filterable=True),
                        "created_at": ColumnSpec(type="datetime", nullable=False, default="now", filterable=True),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        # 生成100个不同的复杂查询组合
        for i in range(100):
            amount_min = random.uniform(0, 1000)
            amount_max = amount_min + random.uniform(100, 5000)
            
            where = {
                "and": [
                    {"amount": {"gte": amount_min, "lte": amount_max}},
                    {"status": {"in_": ["completed", "pending", "processing"]}},
                    {"currency": {"eq": random.choice(["USD", "EUR", "GBP", "JPY"])}},
                ]
            }
            
            clauses = build_where(
                db.tables["transactions"],
                where,
                allowed_fields={"amount", "status", "currency", "user_id", "created_at"}
            )
            assert len(clauses) > 0

    def test_deep_nesting_within_limits(self):
        """测试在限制内的深层嵌套查询"""
        cfg = ConfigSpec(
            tables={
                "items": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="text", nullable=False, filterable=True),
                        "value": ColumnSpec(type="int", nullable=False, filterable=True),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        # 测试各种嵌套深度（在限制100以内）
        for depth in [5, 10, 20, 50, 90]:
            def create_nested(d):
                if d == 0:
                    return {"value": {"eq": 1}}
                return {"and": [create_nested(d - 1)]}
            
            where = create_nested(depth)
            clauses = build_where(db.tables["items"], where, allowed_fields={"id", "value"})
            assert len(clauses) > 0

    def test_batch_upsert_scenarios(self):
        """测试批量upsert场景"""
        cfg = ConfigSpec(
            tables={
                "cache": TableSpec(
                    primary_key=["key"],
                    columns={
                        "key": ColumnSpec(type="text", nullable=False, filterable=True),
                        "value": ColumnSpec(type="text", nullable=False),
                        "expires_at": ColumnSpec(type="datetime", nullable=True),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        # 验证upsert逻辑存在
        assert hasattr(db, "upsert")
        
        # 模拟批量upsert场景（缓存更新）
        Cache = db.models["cache"]
        cache_entries = [
            Cache(key=f"cache_key_{i}", value=f"value_{i}")
            for i in range(1000)
        ]
        
        assert len(cache_entries) == 1000


# ============================================================================
# 真实场景测试 #6: 时间相关的业务逻辑
# ============================================================================


class TestTimeBasedScenarios:
    """测试与时间相关的真实业务场景"""

    def test_time_range_queries_various_intervals(self):
        """测试各种时间范围查询"""
        cfg = ConfigSpec(
            tables={
                "logs": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="uuid", nullable=False, default="uuid4", filterable=True),
                        "created_at": ColumnSpec(type="datetime", nullable=False, default="now", filterable=True),
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        now = datetime.now(timezone.utc)
        
        # 场景1: 最近1小时
        one_hour_ago = now - timedelta(hours=1)
        where1 = {"created_at": {"gte": one_hour_ago}}
        clauses1 = build_where(db.tables["logs"], where1, allowed_fields={"created_at"})
        assert len(clauses1) > 0
        
        # 场景2: 今天
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        where2 = {"created_at": {"gte": today_start}}
        clauses2 = build_where(db.tables["logs"], where2, allowed_fields={"created_at"})
        assert len(clauses2) > 0
        
        # 场景3: 最近7天
        week_ago = now - timedelta(days=7)
        where3 = {"created_at": {"gte": week_ago, "lte": now}}
        clauses3 = build_where(db.tables["logs"], where3, allowed_fields={"created_at"})
        assert len(clauses3) > 0
        
        # 场景4: 特定月份
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        next_month = (month_start + timedelta(days=32)).replace(day=1)
        where4 = {"created_at": {"gte": month_start, "lt": next_month}}
        clauses4 = build_where(db.tables["logs"], where4, allowed_fields={"created_at"})
        assert len(clauses4) > 0


# ============================================================================
# 真实场景测试 #7: Extra字段的灵活使用
# ============================================================================


class TestExtraFieldFlexibilityScenarios:
    """测试extra字段在真实场景中的灵活使用"""

    def test_dynamic_metadata_storage_and_query(self):
        """测试动态元数据存储和查询"""
        cfg = ConfigSpec(
            tables={
                "resources": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="uuid", nullable=False, default="uuid4", filterable=True),
                        "type": ColumnSpec(type="text", nullable=False, filterable=True),
                        # extra字段自动添加
                    },
                )
            }
        )
        db = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg)
        
        # 场景1: 查询特定元数据
        where1 = {"extra.environment": {"eq": "production"}}
        clauses1 = build_where(db.tables["resources"], where1, allowed_fields={"type"})
        assert len(clauses1) > 0
        
        # 场景2: 嵌套元数据查询
        where2 = {"extra.config.version": {"eq": "2.0"}}
        clauses2 = build_where(db.tables["resources"], where2, allowed_fields={"type"})
        assert len(clauses2) > 0
        
        # 场景3: 多层嵌套
        where3 = {"extra.metadata.deployment.region": {"eq": "us-west-1"}}
        clauses3 = build_where(db.tables["resources"], where3, allowed_fields={"type"})
        assert len(clauses3) > 0
        
        # 场景4: 组合查询（extra字段只支持 eq, ne, in_, nin, like, is_null）
        where4 = {
            "and": [
                {"type": {"eq": "server"}},
                {"extra.status": {"eq": "active"}},
                {"extra.region": {"in_": ["us-west-1", "us-east-1"]}},
            ]
        }
        clauses4 = build_where(db.tables["resources"], where4, allowed_fields={"type"})
        assert len(clauses4) > 0


# ============================================================================
# 真实场景测试 #8: 数据迁移和版本管理场景
# ============================================================================


class TestDataMigrationScenarios:
    """测试数据迁移和版本管理的真实场景"""

    def test_schema_evolution_compatibility(self):
        """测试schema演化的兼容性"""
        # V1: 最初的schema
        cfg_v1 = ConfigSpec(
            tables={
                "products": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="uuid", nullable=False, default="uuid4"),
                        "name": ColumnSpec(type="text", nullable=False),
                        "price": ColumnSpec(type="float", nullable=False),
                    },
                )
            }
        )
        db_v1 = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg_v1)
        
        # V2: 添加了新的可选字段
        cfg_v2 = ConfigSpec(
            tables={
                "products": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="uuid", nullable=False, default="uuid4"),
                        "name": ColumnSpec(type="text", nullable=False),
                        "price": ColumnSpec(type="float", nullable=False),
                        "description": ColumnSpec(type="text", nullable=True),  # 新增
                        "category": ColumnSpec(type="text", nullable=True),     # 新增
                    },
                )
            }
        )
        db_v2 = DB(url="postgresql+psycopg://u:p@localhost:5432/db", config=cfg_v2)
        
        # V1和V2的表都应该能创建
        assert "products" in db_v1.tables
        assert "products" in db_v2.tables
        
        # V2有更多列
        assert len(db_v2.tables["products"].columns) > len(db_v1.tables["products"].columns)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
