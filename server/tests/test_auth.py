"""
认证模块单元测试

测试覆盖：
- bcrypt 密码哈希/验证
- JWT 签发/解码/过期
- Pydantic 模型校验
- 路由注册正确性
"""

import time
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models.auth import LoginRequest, RegisterRequest, TokenResponse, UserInfo
from app.services.auth_service import (
    _generate_user_id,
    create_jwt_token,
    decode_jwt_token,
    hash_password,
    verify_password,
)
from app.services.rate_limiter import reset_rate_limits


class TestPasswordHashing:
    """密码哈希与验证"""

    def test_hash_and_verify(self):
        """哈希后可以正确验证"""
        password = "test_password_123"
        hashed = hash_password(password)
        assert hashed != password
        assert verify_password(password, hashed) is True

    def test_wrong_password_fails(self):
        """错误密码验证失败"""
        hashed = hash_password("correct_password")
        assert verify_password("wrong_password", hashed) is False

    def test_hash_is_unique_per_call(self):
        """每次哈希结果不同（salt 随机）"""
        password = "same_password"
        h1 = hash_password(password)
        h2 = hash_password(password)
        assert h1 != h2

    def test_verify_invalid_hash_returns_false(self):
        """数据库中的哈希格式异常（如示例数据占位哈希）时不抛异常，按验证失败处理"""
        assert verify_password("any_password", "$2b$12$dummy_hash_001") is False
        assert verify_password("any_password", "not-a-bcrypt-hash") is False


class TestJWT:
    """JWT 签发与解码"""

    def test_create_and_decode_token(self):
        """签发后可以正确解码"""
        token_resp = create_jwt_token("stu_test", "testuser", "student")
        payload = decode_jwt_token(token_resp.token)

        assert payload["user_id"] == "stu_test"
        assert payload["username"] == "testuser"
        assert payload["role"] == "student"

    def test_token_expires_in_correct(self):
        """过期时间与配置一致"""
        token_resp = create_jwt_token("stu_test", "testuser", "student")
        expected = settings.JWT_EXPIRE_MINUTES * 60
        assert token_resp.expires_in == expected
        assert token_resp.token_type == "Bearer"

    def test_expired_token_raises(self):
        """过期 Token 抛出异常"""
        # 手动构造一个已过期的 Token
        now = datetime.now(timezone.utc)
        expire = now - timedelta(minutes=1)
        payload = {
            "user_id": "stu_test",
            "username": "testuser",
            "role": "student",
            "iat": now - timedelta(minutes=10),
            "exp": expire,
        }
        token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")

        with pytest.raises(jwt.ExpiredSignatureError):
            decode_jwt_token(token)

    def test_invalid_token_raises(self):
        """无效 Token 抛出异常"""
        with pytest.raises(jwt.InvalidTokenError):
            decode_jwt_token("invalid.token.here")


class TestModels:
    """Pydantic 模型校验"""

    def test_register_request_valid(self):
        """正常注册请求"""
        req = RegisterRequest(username="testuser", password="123456", name="测试")
        assert req.username == "testuser"
        assert req.role == "student"  # 默认值

    def test_register_request_username_too_short(self):
        """用户名太短"""
        with pytest.raises(ValueError):
            RegisterRequest(username="ab", password="123456", name="测试")

    def test_register_request_password_too_short(self):
        """密码太短"""
        with pytest.raises(ValueError):
            RegisterRequest(username="testuser", password="12345", name="测试")

    def test_register_request_invalid_role(self):
        """无效角色"""
        with pytest.raises(ValueError):
            RegisterRequest(username="testuser", password="123456", name="测试", role="teacher")

    def test_login_request_valid(self):
        """正常登录请求"""
        req = LoginRequest(username="testuser", password="123456")
        assert req.username == "testuser"

    def test_token_response_model(self):
        """Token 响应模型"""
        tr = TokenResponse(token="abc.def.ghi", expires_in=3600)
        assert tr.token_type == "Bearer"

    def test_user_info_model(self):
        """用户信息模型"""
        ui = UserInfo(user_id="stu_001", username="testuser", name="测试", role="student")
        assert ui.user_id == "stu_001"
        assert ui.avatar is None


class TestUserIDGeneration:
    """业务 ID 生成"""

    def test_student_id_prefix(self):
        """学生 ID 以 stu_ 开头"""
        uid = _generate_user_id("student")
        assert uid.startswith("stu_")

    def test_admin_id_prefix(self):
        """管理员 ID 以 adm_ 开头"""
        uid = _generate_user_id("admin")
        assert uid.startswith("adm_")

    def test_id_is_unique(self):
        """每次生成不同 ID"""
        ids = {_generate_user_id("student") for _ in range(50)}
        assert len(ids) == 50

    def test_id_format(self):
        """ID 格式: prefix_xxxxxxxx (8 位十六进制)"""
        import re

        uid = _generate_user_id("student")
        assert re.match(r"^stu_[0-9a-f]{8}$", uid) is not None


class TestRoutes:
    """路由注册验证"""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    @pytest.fixture(autouse=True)
    def _reset_limits(self):
        """每个用例前清空速率限制计数，保证用例相互独立"""
        reset_rate_limits()
        yield
        reset_rate_limits()

    def test_auth_routes_registered(self, client):
        """验证 auth 路由已注册"""
        # 注册端点存在（返回 422 表示参数校验失败，而非 404）
        resp = client.post("/auth/register")
        assert resp.status_code != 404

        resp = client.post("/auth/login")
        assert resp.status_code != 404

    def test_auth_me_requires_token(self, client):
        """GET /auth/me 无 Token 返回 401"""
        resp = client.get("/auth/me")
        assert resp.status_code == 401

    def test_health_endpoints_still_work(self, client):
        """管理后台和学员端健康检查仍可访问（健康检查不要求登录）"""
        resp = client.get("/api/admin/health")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

        resp = client.get("/api/student/health")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    def test_login_wrong_credentials_returns_401(self, client, monkeypatch):
        """登录失败（凭证错误/账号禁用）→ HTTP 401 + 业务码 40100（统一格式）"""

        async def fake_login(username: str, password: str) -> TokenResponse:
            raise ValueError("用户名或密码错误")

        monkeypatch.setattr("app.routers.auth.login", fake_login)
        resp = client.post(
            "/auth/login", json={"username": "testuser", "password": "wrong"}
        )
        assert resp.status_code == 401
        body = resp.json()
        assert set(body.keys()) == {"code", "data", "message"}
        assert body["code"] == 40100

    def test_register_admin_role_rejected_403(self, client):
        """注册接口强制 student 角色：传 admin → HTTP 403 + 业务码 40101"""
        resp = client.post(
            "/auth/register",
            json={
                "username": "badadmin",
                "password": "123456",
                "name": "假管理员",
                "role": "admin",
            },
        )
        assert resp.status_code == 403
        body = resp.json()
        assert set(body.keys()) == {"code", "data", "message"}
        assert body["code"] == 40101

    def test_login_rate_limited(self, client, monkeypatch):
        """登录接口触发速率限制：窗口内超过上限返回 429（统一响应格式）"""
        # 调低阈值便于测试；依赖运行时读取 settings，monkeypatch 即时生效
        monkeypatch.setattr(settings, "RATE_LIMIT_LOGIN_MAX_ATTEMPTS", 3)
        monkeypatch.setattr(settings, "RATE_LIMIT_LOGIN_WINDOW_SECONDS", 3600)

        async def fake_login(username: str, password: str) -> TokenResponse:
            return TokenResponse(token="fake.token", expires_in=3600)

        monkeypatch.setattr("app.routers.auth.login", fake_login)

        payload = {"username": "testuser", "password": "123456"}
        for _ in range(3):
            resp = client.post("/auth/login", json=payload)
            assert resp.status_code == 200
        # 第 4 次触发限流
        resp = client.post("/auth/login", json=payload)
        assert resp.status_code == 429
        body = resp.json()
        assert set(body.keys()) == {"code", "data", "message"}
        assert body["code"] == 40901

    def test_register_rate_limited(self, client, monkeypatch):
        """注册接口触发速率限制：窗口内超过上限返回 429"""
        monkeypatch.setattr(settings, "RATE_LIMIT_REGISTER_MAX_ATTEMPTS", 3)
        monkeypatch.setattr(settings, "RATE_LIMIT_REGISTER_WINDOW_SECONDS", 3600)

        async def fake_register(
            username: str, password: str, name: str, role: str = "student"
        ) -> UserInfo:
            return UserInfo(
                user_id="stu_test", username=username, name=name, role="student"
            )

        monkeypatch.setattr("app.routers.auth.register", fake_register)

        payload = {"username": "newuser", "password": "123456", "name": "新同学"}
        for _ in range(3):
            resp = client.post("/auth/register", json=payload)
            assert resp.status_code == 200
        resp = client.post("/auth/register", json=payload)
        assert resp.status_code == 429
        assert resp.json()["code"] == 40901
