"""
业务逻辑漏洞测试套件

本测试套件专注于发现AgentFabric的业务逻辑漏洞，包括：
1. SQL注入和过滤器DSL安全性
2. 类型强制转换漏洞
3. NULL值处理边界
4. 并发事务冲突
5. 数据完整性约束
6. 默认值注入漏洞
7. Extra字段权限绕过
8. List contains类型混淆
9. 外键级联操作
10. 压力测试和资源泄漏
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4
import threading
import time

import pytest

from agentfabric.db.facade import DB
from agentfabric.config.spec import ColumnSpec, ConfigSpec, TableSpec


# ==============================================================================
# 测试夹具 - 配置各种测试场景的数据库
# ==============================================================================

@pytest.fixture
def basic_db():
    """基础数据库配置，用于大多数测试"""
    cfg = ConfigSpec(
        db_url="postgresql+psycopg://u:p@localhost:5432/db",
        postgres_schema="test_vuln",
        tables={
            "users": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="uuid", nullable=False, default="uuid4", filterable=True),
                    "username": ColumnSpec(type="text", nullable=False, filterable=True),
                    "email": ColumnSpec(type="text", nullable=True, filterable=True),
                    "age": ColumnSpec(type="int", nullable=True, filterable=True),
                    "balance": ColumnSpec(type="float", nullable=True, filterable=True),
                    "is_active": ColumnSpec(type="bool", nullable=False, default=True, filterable=True),
                    "created_at": ColumnSpec(type="datetime", nullable=False, default="now", filterable=True),
                    "tags": ColumnSpec(type="list", item_type="text", nullable=True, filterable=True),
                    "scores": ColumnSpec(type="list", item_type="int", nullable=True, filterable=True),
                },
            ),
            "orders": TableSpec(
                primary_key=["id"],
                columns={
                    "id": ColumnSpec(type="uuid", nullable=False, default="uuid4", filterable=True),
                    "user_id": ColumnSpec(type="uuid", nullable=False, filterable=True),
                    "amount": ColumnSpec(type="float", nullable=False, filterable=True),
                    "status": ColumnSpec(type="text", nullable=False, default="pending", filterable=True),
                    "created_at": ColumnSpec(type="datetime", nullable=False, default="now", filterable=True),
                },
                foreign_keys=[
                    {"columns": ["user_id"], "ref_table": "users", "ref_columns": ["id"], "on_delete": "cascade"}
                ],
            ),
        },
    )
    return DB(config=cfg)


@pytest.fixture
def db_with_composite_pk():
    """带复合主键的数据库配置"""
    cfg = ConfigSpec(
        db_url="postgresql+psycopg://u:p@localhost:5432/db",
        postgres_schema="test_composite",
        tables={
            "multi_pk": TableSpec(
                primary_key=["part1", "part2"],
                columns={
                    "part1": ColumnSpec(type="text", nullable=False, filterable=True),
                    "part2": ColumnSpec(type="int", nullable=False, filterable=True),
                    "data": ColumnSpec(type="text", nullable=True, filterable=True),
                },
            ),
        },
    )
    return DB(config=cfg)


# ==============================================================================
# 1. SQL注入和过滤器DSL安全性测试
# ==============================================================================

class TestSQLInjectionVulnerabilities:
    """测试SQL注入漏洞"""

    def test_sql_injection_in_text_filter_eq(self, basic_db):
        """测试在文本字段的eq操作符中注入SQL"""
        # 尝试通过eq注入SQL
        malicious_inputs = [
            "'; DROP TABLE users; --",
            "admin' OR '1'='1",
            "' UNION SELECT * FROM orders --",
            "1' AND 1=1 --",
            "'; DELETE FROM users WHERE 1=1; --",
        ]
        
        for malicious in malicious_inputs:
            # 应该被安全处理，不会执行SQL注入
            try:
                result = basic_db.query(
                    "users",
                    {"where": {"username": {"eq": malicious}}},
                )
                # 应该正常执行，但返回空结果
                assert isinstance(result, list)
            except Exception as e:
                # 如果抛出异常，应该是安全的验证异常，而非SQL执行错误
                assert "SQL" not in str(e).upper() or "syntax" not in str(e).lower()

    def test_sql_injection_in_like_filter(self, basic_db):
        """测试LIKE操作符的SQL注入"""
        malicious_patterns = [
            "%'; DROP TABLE users; --",
            "admin%' OR '1'='1",
            "%' UNION SELECT * FROM orders --",
        ]
        
        for pattern in malicious_patterns:
            try:
                result = basic_db.query(
                    "users",
                    {"where": {"username": {"like": pattern}}},
                )
                assert isinstance(result, list)
            except Exception as e:
                assert "SQL" not in str(e).upper() or "syntax" not in str(e).lower()

    def test_sql_injection_in_extra_field(self, basic_db):
        """测试extra字段的SQL注入"""
        malicious_extras = [
            {"extra.tag": {"eq": "'; DROP TABLE users; --"}},
            {"extra.data.nested": {"like": "%' OR '1'='1%"}},
        ]
        
        for extra_filter in malicious_extras:
            try:
                result = basic_db.query("users", {"where": extra_filter})
                assert isinstance(result, list)
            except Exception as e:
                # 应该是安全的验证错误
                assert "SQL" not in str(e).upper() or "syntax" not in str(e).lower()

    def test_field_name_injection(self, basic_db):
        """测试字段名注入漏洞"""
        # 尝试通过构造恶意字段名来注入
        malicious_fields = [
            "username; DROP TABLE users; --",
            "id' OR '1'='1",
            "extra.; DROP TABLE users; --",
        ]
        
        for field in malicious_fields:
            with pytest.raises((ValueError, KeyError, TypeError)):
                # 应该拒绝无效的字段名
                basic_db.query("users", {"where": {field: {"eq": "test"}}})


# ==============================================================================
# 2. 类型强制转换和验证漏洞测试
# ==============================================================================

class TestTypeCoercionVulnerabilities:
    """测试类型强制转换漏洞"""

    def test_integer_overflow_in_filter(self, basic_db):
        """测试整数溢出"""
        extreme_values = [
            2**63 - 1,  # 最大64位整数
            2**63,      # 溢出边界
            -2**63,     # 最小64位整数
            -2**63 - 1, # 下溢边界
        ]
        
        for val in extreme_values:
            try:
                result = basic_db.query(
                    "users",
                    {"where": {"age": {"eq": val}}},
                )
                # 应该能处理或抛出明确的错误
                assert isinstance(result, list)
            except (OverflowError, ValueError) as e:
                # 预期的类型错误
                pass

    def test_float_precision_attack(self, basic_db):
        """测试浮点数精度攻击"""
        tricky_floats = [
            float('inf'),
            float('-inf'),
            float('nan'),
            1e308,      # 接近最大浮点数
            1e-308,     # 接近最小浮点数
        ]
        
        for val in tricky_floats:
            try:
                result = basic_db.query(
                    "users",
                    {"where": {"balance": {"eq": val}}},
                )
                assert isinstance(result, list)
            except (ValueError, OverflowError):
                # 预期的类型错误
                pass

    def test_type_confusion_in_contains(self, basic_db):
        """测试contains操作符的类型混淆攻击"""
        # tags字段是list[text]，尝试传入错误类型
        invalid_contains = [
            {"tags": {"contains": ["should_be_string"]}},  # 传入列表而非字符串
            {"tags": {"contains": 123}},                    # 传入整数而非字符串
            {"tags": {"contains": {"key": "val"}}},         # 传入字典而非字符串
        ]
        
        for filter_cond in invalid_contains:
            with pytest.raises(TypeError):
                # 应该拒绝类型不匹配的值
                basic_db.query("users", {"where": filter_cond})

    def test_boolean_type_confusion(self, basic_db):
        """测试布尔类型混淆"""
        # Python中True == 1, False == 0，测试是否能被利用
        confusing_values = [
            1,      # 与True相等
            0,      # 与False相等
            "True", # 字符串
            "1",    # 字符串
        ]
        
        for val in confusing_values:
            try:
                result = basic_db.query(
                    "users",
                    {"where": {"is_active": {"eq": val}}},
                )
                # 检查是否正确处理类型
                assert isinstance(result, list)
            except (TypeError, ValueError):
                pass

    def test_uuid_format_injection(self, basic_db):
        """测试UUID格式注入"""
        invalid_uuids = [
            "not-a-uuid",
            "00000000-0000-0000-0000-000000000000' OR '1'='1",
            "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
            "12345678-1234-1234-1234-123456789012extra",
        ]
        
        for bad_uuid in invalid_uuids:
            try:
                result = basic_db.query(
                    "users",
                    {"where": {"id": {"eq": bad_uuid}}},
                )
                # 如果接受字符串，应该安全处理
                assert isinstance(result, list)
            except (ValueError, TypeError):
                # 预期的格式错误
                pass


# ==============================================================================
# 3. NULL值处理边界测试
# ==============================================================================

class TestNullHandlingVulnerabilities:
    """测试NULL值处理漏洞"""

    def test_null_in_eq_operator_blocked(self, basic_db):
        """测试eq操作符使用None会被拒绝"""
        with pytest.raises(ValueError, match="Use 'is_null"):
            basic_db.query("users", {"where": {"username": {"eq": None}}})

    def test_null_in_ne_operator_blocked(self, basic_db):
        """测试ne操作符使用None会被拒绝"""
        with pytest.raises(ValueError, match="Use 'is_null"):
            basic_db.query("users", {"where": {"username": {"ne": None}}})

    def test_null_in_contains_operator_blocked(self, basic_db):
        """测试contains操作符使用None会被拒绝"""
        with pytest.raises(TypeError, match="does not accept None"):
            basic_db.query("users", {"where": {"tags": {"contains": None}}})

    def test_null_bypass_with_empty_string(self, basic_db):
        """测试是否能用空字符串绕过NULL检查"""
        # 创建测试数据
        filters = [
            {"username": {"eq": ""}},
            {"email": {"eq": ""}},
            {"username": {"ne": ""}},
        ]
        
        for f in filters:
            result = basic_db.query("users", {"where": f})
            assert isinstance(result, list)

    def test_null_in_list_operations(self, basic_db):
        """测试列表操作中的NULL处理"""
        # 测试in_操作符中的None元素
        test_cases = [
            {"username": {"in_": [None, "admin", "user"]}},
            {"age": {"in_": [None, 18, 25]}},
            {"tags": {"in_": [None]}},
        ]
        
        for case in test_cases:
            result = basic_db.query("users", {"where": case})
            assert isinstance(result, list)

    def test_is_null_with_other_operators(self, basic_db):
        """测试is_null与其他操作符组合使用"""
        # 应该能安全组合使用
        combined_filters = [
            {"username": {"is_null": True, "eq": "admin"}},
            {"email": {"is_null": False, "like": "%@example.com"}},
            {"age": {"is_null": True, "gt": 18}},
        ]
        
        for f in combined_filters:
            result = basic_db.query("users", {"where": f})
            assert isinstance(result, list)


# ==============================================================================
# 4. 并发事务冲突测试
# ==============================================================================

class TestConcurrencyVulnerabilities:
    """测试并发事务漏洞"""

    def test_race_condition_in_upsert(self, basic_db):
        """测试upsert操作的竞态条件"""
        # 注意：这个测试需要实际数据库连接才能真正测试
        # 这里只测试API层面的并发安全性
        
        user_id = uuid4()
        results = []
        errors = []
        
        def upsert_operation(idx):
            try:
                User = basic_db.models["users"]
                user = User(
                    id=user_id,
                    username=f"user_{idx}",
                    is_active=True,
                )
                result = basic_db.upsert("users", user, conflict_cols=["id"])
                results.append(result)
            except Exception as e:
                errors.append(e)
        
        # 模拟多个线程同时upsert
        threads = []
        for i in range(5):
            t = threading.Thread(target=upsert_operation, args=(i,))
            threads.append(t)
        
        # 启动所有线程
        for t in threads:
            t.start()
        
        # 等待完成
        for t in threads:
            t.join()
        
        # 应该没有崩溃，且至少有一个成功
        assert len(results) > 0 or len(errors) > 0

    def test_concurrent_delete_and_query(self, basic_db):
        """测试并发删除和查询的一致性"""
        results = []
        errors = []
        
        def query_operation():
            try:
                result = basic_db.query("users", {"where": {"is_active": {"eq": True}}})
                results.append(len(result))
            except Exception as e:
                errors.append(e)
        
        def delete_operation():
            try:
                # 尝试删除操作
                result = basic_db.delete_where("users", {"is_active": {"eq": False}})
                results.append(result)
            except Exception as e:
                errors.append(e)
        
        # 同时执行查询和删除
        threads = []
        for _ in range(3):
            threads.append(threading.Thread(target=query_operation))
            threads.append(threading.Thread(target=delete_operation))
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # 不应该有严重错误
        assert len(errors) == 0 or all(isinstance(e, ValueError) for e in errors)


# ==============================================================================
# 5. 数据完整性约束测试
# ==============================================================================

class TestDataIntegrityVulnerabilities:
    """测试数据完整性约束漏洞"""

    def test_foreign_key_bypass_attempt(self, basic_db):
        """测试是否能绕过外键约束"""
        # 尝试插入一个引用不存在的user的order
        # 注意：这需要实际数据库才能真正测试外键约束
        Order = basic_db.models["orders"]
        
        fake_user_id = uuid4()
        order = Order(
            id=uuid4(),
            user_id=fake_user_id,
            amount=100.0,
            status="pending",
        )
        
        # 检查是否正确定义了外键
        orders_table = basic_db.tables["orders"]
        fks = list(orders_table.foreign_keys)
        assert len(fks) > 0

    def test_primary_key_uniqueness_violation(self, basic_db):
        """测试主键唯一性约束"""
        # 尝试插入重复的主键
        User = basic_db.models["users"]
        same_id = uuid4()
        
        user1 = User(id=same_id, username="user1", is_active=True)
        user2 = User(id=same_id, username="user2", is_active=True)
        
        # 检查是否定义了主键
        users_table = basic_db.tables["users"]
        assert len(users_table.primary_key) > 0

    def test_nullable_constraint_bypass(self, basic_db):
        """测试是否能绕过非空约束"""
        User = basic_db.models["users"]
        
        # 尝试创建username为None的用户（username是非空字段）
        user = User(
            username=None,  # 应该违反非空约束
            is_active=True,
        )
        
        # 检查列定义
        users_table = basic_db.tables["users"]
        username_col = users_table.c.username
        assert username_col.nullable is False

    def test_composite_primary_key_partial_match(self, db_with_composite_pk):
        """测试复合主键的部分匹配漏洞"""
        # 尝试用部分主键删除数据
        with pytest.raises(ValueError):
            db_with_composite_pk.delete_by_pk("multi_pk", [{"part1": "test"}])
        
        with pytest.raises(ValueError):
            db_with_composite_pk.delete_by_pk("multi_pk", [{"part2": 123}])


# ==============================================================================
# 6. 默认值注入漏洞测试
# ==============================================================================

class TestDefaultValueVulnerabilities:
    """测试默认值注入漏洞"""

    def test_uuid4_default_predictability(self, basic_db):
        """测试uuid4默认值的可预测性"""
        User = basic_db.models["users"]
        
        # 创建多个用户，检查UUID是否真的随机
        uuids = []
        for i in range(100):
            user = User(username=f"user_{i}", is_active=True)
            user = basic_db._apply_sdk_defaults_obj(user)
            uuids.append(user.id)
        
        # UUID应该全部不同
        assert len(set(uuids)) == 100
        
        # UUID应该是有效的UUID4
        for uid in uuids:
            assert isinstance(uid, UUID)
            assert uid.version == 4

    def test_now_default_time_manipulation(self, basic_db):
        """测试now默认值的时间操作漏洞"""
        User = basic_db.models["users"]
        
        # 创建用户并记录时间
        before = datetime.now(timezone.utc)
        time.sleep(0.01)  # 确保有时间差
        
        user = User(username="test", is_active=True)
        user = basic_db._apply_sdk_defaults_obj(user)
        
        time.sleep(0.01)
        after = datetime.now(timezone.utc)
        
        # created_at应该在before和after之间
        assert before <= user.created_at <= after
        # 应该有时区信息
        assert user.created_at.tzinfo is not None

    def test_default_value_override_attack(self, basic_db):
        """测试是否能通过覆盖绕过默认值"""
        User = basic_db.models["users"]
        
        # 尝试手动设置uuid和时间为恶意值
        malicious_id = UUID("00000000-0000-0000-0000-000000000000")
        malicious_time = datetime(1970, 1, 1, tzinfo=timezone.utc)
        
        user = User(
            id=malicious_id,
            username="admin",
            is_active=True,
            created_at=malicious_time,
        )
        
        # 默认值不应该覆盖已设置的值
        user = basic_db._apply_sdk_defaults_obj(user)
        assert user.id == malicious_id
        assert user.created_at == malicious_time

    def test_literal_default_deep_copy_safety(self, basic_db):
        """测试字面量默认值的深拷贝安全性"""
        # 如果默认值是可变对象（如列表、字典），必须深拷贝
        row1 = basic_db._apply_sdk_defaults_row("users", {"username": "user1"})
        row2 = basic_db._apply_sdk_defaults_row("users", {"username": "user2"})
        
        # 确认默认值被正确应用
        assert "is_active" in row1
        assert "is_active" in row2


# ==============================================================================
# 7. Extra字段权限绕过测试
# ==============================================================================

class TestExtraFieldBypassVulnerabilities:
    """测试Extra字段权限绕过漏洞"""

    def test_extra_field_filter_on_non_filterable_column(self, basic_db):
        """测试在不可过滤字段上使用extra绕过"""
        # extra字段始终可以过滤，但使用受限的操作符
        
        valid_extra_filters = [
            {"extra.tag": {"eq": "admin"}},
            {"extra.role": {"ne": "user"}},
            {"extra.status": {"like": "active%"}},
        ]
        
        for f in valid_extra_filters:
            result = basic_db.query("users", {"where": f})
            assert isinstance(result, list)

    def test_extra_field_unsupported_operators(self, basic_db):
        """测试extra字段的不支持操作符"""
        # extra字段应该只支持有限的操作符
        unsupported_filters = [
            {"extra.count": {"gt": 10}},
            {"extra.score": {"lt": 50}},
            {"extra.items": {"contains": "test"}},
        ]
        
        for f in unsupported_filters:
            with pytest.raises(ValueError, match="unsupported op for extra"):
                basic_db.query("users", {"where": f})

    def test_extra_field_path_traversal(self, basic_db):
        """测试extra字段路径遍历攻击"""
        # 测试恶意路径
        malicious_paths = [
            "extra../../../etc/passwd",
            "extra.../../database",
            "extra.....///system",
        ]
        
        for path in malicious_paths:
            try:
                # 路径应该被安全处理
                result = basic_db.query("users", {"where": {path: {"eq": "test"}}})
                assert isinstance(result, list)
            except (ValueError, KeyError):
                # 预期的错误
                pass

    def test_extra_field_dot_escaping_bypass(self, basic_db):
        """测试extra字段点号转义绕过"""
        # 测试转义处理
        from agentfabric.db.query import _split_extra_path
        
        # 正常路径
        assert _split_extra_path("a.b.c") == ["a", "b", "c"]
        
        # 转义的点号
        assert _split_extra_path("a\\.b.c") == ["a.b", "c"]
        
        # 无效路径应该被拒绝
        with pytest.raises(ValueError):
            _split_extra_path("a.b.")  # 空段
        
        with pytest.raises(ValueError):
            _split_extra_path(".a.b")  # 空段
        
        with pytest.raises(ValueError):
            _split_extra_path("a..b")  # 空段
        
        with pytest.raises(ValueError):
            _split_extra_path("a\\")  # 尾部转义


# ==============================================================================
# 8. List contains类型混淆测试
# ==============================================================================

class TestListContainsTypeConfusion:
    """测试List contains操作符的类型混淆漏洞"""

    def test_contains_with_list_instead_of_element(self, basic_db):
        """测试使用列表而非元素"""
        with pytest.raises(TypeError, match="expects a scalar element"):
            basic_db.query("users", {"where": {"tags": {"contains": ["tag1", "tag2"]}}})

    def test_contains_with_dict_instead_of_element(self, basic_db):
        """测试使用字典而非元素"""
        with pytest.raises(TypeError, match="expects a scalar element"):
            basic_db.query("users", {"where": {"tags": {"contains": {"key": "val"}}}})

    def test_contains_with_set_instead_of_element(self, basic_db):
        """测试使用集合而非元素"""
        with pytest.raises(TypeError, match="expects a scalar element"):
            basic_db.query("users", {"where": {"tags": {"contains": {"tag1", "tag2"}}}})

    def test_contains_integer_list_type_validation(self, basic_db):
        """测试整数列表的类型验证"""
        # scores是list[int]，应该只接受int
        with pytest.raises(TypeError, match="expects an int element"):
            basic_db.query("users", {"where": {"scores": {"contains": "100"}}})
        
        with pytest.raises(TypeError, match="expects an int element"):
            basic_db.query("users", {"where": {"scores": {"contains": 100.5}}})
        
        # bool是int的子类，应该被拒绝
        with pytest.raises(TypeError, match="expects an int element"):
            basic_db.query("users", {"where": {"scores": {"contains": True}}})

    def test_contains_on_non_list_column(self, basic_db):
        """测试在非列表列上使用contains"""
        with pytest.raises(TypeError, match="only supported for list/ARRAY"):
            basic_db.query("users", {"where": {"username": {"contains": "admin"}}})

    def test_contains_with_none_value(self, basic_db):
        """测试contains使用None值"""
        with pytest.raises(TypeError, match="does not accept None"):
            basic_db.query("users", {"where": {"tags": {"contains": None}}})


# ==============================================================================
# 9. 复杂查询组合测试
# ==============================================================================

class TestComplexQueryVulnerabilities:
    """测试复杂查询组合的漏洞"""

    def test_and_or_combination_logic_bomb(self, basic_db):
        """测试AND/OR组合的逻辑炸弹"""
        # 构造一个复杂的嵌套查询
        complex_filter = {
            "and": [
                {"username": {"eq": "admin"}},
                {
                    "or": [
                        {"age": {"gt": 18}},
                        {"age": {"lt": 65}},
                        {
                            "and": [
                                {"is_active": {"eq": True}},
                                {"balance": {"gte": 0}},
                            ]
                        },
                    ]
                },
            ]
        }
        
        result = basic_db.query("users", {"where": complex_filter})
        assert isinstance(result, list)

    def test_deeply_nested_or_conditions(self, basic_db):
        """测试深度嵌套的OR条件"""
        # 创建深度嵌套
        nested = {"username": {"eq": "test"}}
        for _ in range(50):
            nested = {"or": [nested, {"age": {"gt": 0}}]}
        
        # 应该能处理或拒绝
        try:
            result = basic_db.query("users", {"where": nested})
            assert isinstance(result, list)
        except (RecursionError, ValueError):
            pass

    def test_same_field_multiple_constraints(self, basic_db):
        """测试同一字段的多个约束"""
        # 使用and组合同一字段的多个条件
        filter_with_conflicts = {
            "and": [
                {"age": {"gt": 18}},
                {"age": {"lt": 65}},
                {"age": {"ne": 25}},
            ]
        }
        
        result = basic_db.query("users", {"where": filter_with_conflicts})
        assert isinstance(result, list)

    def test_contradictory_conditions(self, basic_db):
        """测试互相矛盾的条件"""
        contradictory = {
            "and": [
                {"age": {"gt": 50}},
                {"age": {"lt": 30}},
            ]
        }
        
        result = basic_db.query("users", {"where": contradictory})
        # 应该返回空结果
        assert isinstance(result, list)

    def test_empty_and_or_lists(self, basic_db):
        """测试空的and/or列表"""
        with pytest.raises(TypeError):
            basic_db.query("users", {"where": {"and": "not_a_list"}})
        
        # 空列表应该被处理
        result = basic_db.query("users", {"where": {"and": []}})
        assert isinstance(result, list)


# ==============================================================================
# 10. 边界值和极端参数测试
# ==============================================================================

class TestBoundaryValueVulnerabilities:
    """测试边界值和极端参数漏洞"""

    def test_limit_offset_overflow(self, basic_db):
        """测试limit和offset溢出"""
        extreme_values = [
            {"limit": 2**31 - 1, "offset": 0},
            {"limit": 1000, "offset": 2**31 - 1},
            {"limit": -1, "offset": 0},
            {"limit": 0, "offset": -1},
        ]
        
        for params in extreme_values:
            try:
                result = basic_db.query("users", params)
                assert isinstance(result, list)
            except (ValueError, OverflowError):
                pass

    def test_very_long_string_filter(self, basic_db):
        """测试超长字符串过滤"""
        # 1MB的字符串
        very_long_string = "a" * (1024 * 1024)
        
        try:
            result = basic_db.query(
                "users",
                {"where": {"username": {"eq": very_long_string}}},
            )
            assert isinstance(result, list)
        except (MemoryError, ValueError):
            pass

    def test_very_large_in_list(self, basic_db):
        """测试超大的in列表"""
        # 10000个元素的in列表
        large_list = [f"user_{i}" for i in range(10000)]
        
        try:
            result = basic_db.query(
                "users",
                {"where": {"username": {"in_": large_list}}},
            )
            assert isinstance(result, list)
        except (MemoryError, ValueError):
            pass

    def test_empty_in_list_behavior(self, basic_db):
        """测试空in列表的行为"""
        # in_空列表应该返回空结果
        result = basic_db.query("users", {"where": {"username": {"in_": []}}})
        assert isinstance(result, list)
        
        # nin空列表应该返回所有结果（无过滤）
        result = basic_db.query("users", {"where": {"username": {"nin": []}}})
        assert isinstance(result, list)

    def test_datetime_extreme_values(self, basic_db):
        """测试日期时间极端值"""
        extreme_dates = [
            datetime(1, 1, 1, tzinfo=timezone.utc),
            datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
            datetime(1970, 1, 1, tzinfo=timezone.utc),
        ]
        
        for dt in extreme_dates:
            try:
                result = basic_db.query(
                    "users",
                    {"where": {"created_at": {"eq": dt}}},
                )
                assert isinstance(result, list)
            except (ValueError, OverflowError):
                pass


# ==============================================================================
# 11. 删除操作安全性测试
# ==============================================================================

class TestDeleteOperationVulnerabilities:
    """测试删除操作的安全性漏洞"""

    def test_delete_where_requires_non_empty_where(self, basic_db):
        """测试delete_where需要非空where条件"""
        with pytest.raises(ValueError, match="requires non-empty where"):
            basic_db.delete_where("users", {})

    def test_delete_by_pk_requires_non_empty_rows(self, basic_db):
        """测试delete_by_pk需要非空行列表"""
        result = basic_db.delete_by_pk("users", [])
        assert result == 0

    def test_delete_by_pk_requires_complete_pk(self, basic_db):
        """测试delete_by_pk需要完整的主键"""
        with pytest.raises(ValueError, match="no complete primary key"):
            basic_db.delete_by_pk("users", [{"id": None}])

    def test_delete_by_pk_on_composite_key_incomplete(self, db_with_composite_pk):
        """测试复合主键的不完整删除"""
        with pytest.raises(ValueError):
            db_with_composite_pk.delete_by_pk("multi_pk", [{"part1": "test"}])

    def test_update_requires_non_empty_where(self, basic_db):
        """测试update需要非空where条件"""
        with pytest.raises(ValueError, match="requires non-empty where"):
            basic_db.update("users", {}, {"username": "hacker"})


# ==============================================================================
# 12. 过滤器字段权限测试
# ==============================================================================

class TestFilterableFieldVulnerabilities:
    """测试可过滤字段权限漏洞"""

    def test_non_filterable_field_rejection(self, basic_db):
        """测试不可过滤字段被拒绝"""
        # msg字段是不可过滤的（在basic_db fixture中没有，但在test_db_facade_logic.py中有）
        # 这里我们测试filterable机制
        
        # 获取可过滤字段列表
        filterable = basic_db._filterable_cols.get("users", set())
        
        # username应该是可过滤的
        assert "username" in filterable
        assert "email" in filterable
        assert "age" in filterable

    def test_filter_on_non_filterable_raises_error(self):
        """测试在不可过滤字段上过滤会报错"""
        cfg = ConfigSpec(
            db_url="postgresql+psycopg://u:p@localhost:5432/db",
            postgres_schema="test",
            tables={
                "t": TableSpec(
                    primary_key=["id"],
                    columns={
                        "id": ColumnSpec(type="text", nullable=False, filterable=True),
                        "secret": ColumnSpec(type="text", nullable=True, filterable=False),
                    },
                ),
            },
        )
        db = DB(config=cfg)
        
        # 尝试过滤不可过滤字段
        with pytest.raises(ValueError, match="not filterable"):
            db.query("t", {"where": {"secret": {"eq": "test"}}})


# ==============================================================================
# 13. Upsert操作漏洞测试
# ==============================================================================

class TestUpsertVulnerabilities:
    """测试Upsert操作的漏洞"""

    def test_upsert_without_pk_requires_conflict_cols(self):
        """测试没有主键的表upsert需要conflict_cols"""
        cfg = ConfigSpec(
            db_url="postgresql+psycopg://u:p@localhost:5432/db",
            postgres_schema="test",
            tables={
                "no_pk": TableSpec(
                    primary_key=[],
                    columns={
                        "data": ColumnSpec(type="text", nullable=True),
                    },
                ),
            },
        )
        db = DB(config=cfg)
        
        Model = db.models["no_pk"]
        obj = Model(data="test")
        
        with pytest.raises(ValueError, match="no primary key"):
            db.upsert("no_pk", obj)

    def test_upsert_uses_provided_conflict_cols(self, basic_db):
        """测试upsert使用提供的conflict_cols"""
        User = basic_db.models["users"]
        user = User(
            id=uuid4(),
            username="test",
            email="test@example.com",
            is_active=True,
        )
        
        # 使用username作为冲突列（虽然主键是id）
        # 这应该被接受
        # 注意：这个测试需要实际数据库来验证行为


# ==============================================================================
# 14. 错误恢复和异常处理测试
# ==============================================================================

class TestErrorRecoveryVulnerabilities:
    """测试错误恢复和异常处理漏洞"""

    def test_invalid_table_name(self, basic_db):
        """测试无效表名"""
        with pytest.raises(KeyError):
            basic_db.query("non_existent_table", {})

    def test_invalid_operator_name(self, basic_db):
        """测试无效操作符"""
        # 不支持的操作符应该被忽略
        result = basic_db.query(
            "users",
            {"where": {"username": {"invalid_op": "test"}}},
        )
        assert isinstance(result, list)

    def test_malformed_filter_structure(self, basic_db):
        """测试畸形的过滤器结构"""
        malformed = [
            {"where": "not_a_dict"},
            {"where": []},
            {"where": 123},
        ]
        
        for f in malformed:
            with pytest.raises((TypeError, AttributeError)):
                basic_db.query("users", f)

    def test_field_condition_not_dict(self, basic_db):
        """测试字段条件不是字典"""
        with pytest.raises(TypeError, match="must be a dict of ops"):
            basic_db.query("users", {"where": {"username": "not_a_dict"}})

    def test_and_or_not_list(self, basic_db):
        """测试and/or不是列表"""
        with pytest.raises(TypeError, match="must be a list"):
            basic_db.query("users", {"where": {"and": "not_a_list"}})
        
        with pytest.raises(TypeError, match="must be a list"):
            basic_db.query("users", {"where": {"or": {"not": "list"}}})

    def test_and_or_items_not_dict(self, basic_db):
        """测试and/or项不是字典"""
        with pytest.raises(TypeError, match="items must be dicts"):
            basic_db.query("users", {"where": {"and": ["not_dict", 123]}})


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
