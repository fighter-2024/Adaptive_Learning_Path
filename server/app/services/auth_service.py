"""
认证业务服务

负责用户注册、登录、信息查询等核心业务逻辑。
Service 层不接触 HTTP 请求/响应对象，只处理纯业务数据。
密码使用 bcrypt 哈希，JWT 使用 PyJWT 签发与校验。
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import bcrypt
import jwt
import pyodbc

from app.config import settings
from app.models.auth import TokenResponse, UserInfo

logger = logging.getLogger(__name__)

# ==================== 密码处理 ====================


def hash_password(password: str) -> str:
    """对明文密码进行 bcrypt 哈希

    Args:
        password: 明文密码

    Returns:
        bcrypt 哈希后的密文
    """
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """验证明文密码是否匹配 bcrypt 哈希

    数据库中的哈希格式异常（脏数据/占位值）时不抛异常，
    记 warning 日志并按验证失败处理，避免把内部错误泄露给客户端。

    Args:
        password: 明文密码
        password_hash: 数据库中存储的 bcrypt 哈希

    Returns:
        密码是否正确
    """
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError) as e:
        # 如 init.sql 示例数据的占位哈希（"Invalid salt"）会走到这里
        logger.warning("密码哈希格式异常，按验证失败处理: %s", e)
        return False


# ==================== JWT 处理 ====================


def create_jwt_token(user_id: str, username: str, role: str) -> TokenResponse:
    """签发 JWT 访问令牌

    说明：JWT 的 iat/exp 使用 UTC（令牌需要跨时区的绝对时间）。
    业务时间戳（created_at / last_login_at 等）统一用服务器本地时间，
    与 SQL Server GETDATE() 一致，见 app.db.sqlserver.get_local_now。

    Args:
        user_id: 用户业务 ID
        username: 登录账号
        role: 用户角色

    Returns:
        TokenResponse: 包含 token 和过期信息
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)

    payload = {
        "user_id": user_id,
        "username": username,
        "role": role,
        "iat": now,
        "exp": expire,
    }

    token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    expires_in = settings.JWT_EXPIRE_MINUTES * 60

    return TokenResponse(token=token, expires_in=expires_in)


def decode_jwt_token(token: str) -> dict:
    """解析并校验 JWT 令牌

    Args:
        token: JWT 字符串

    Returns:
        解码后的 payload 字典，含 user_id / username / role

    Raises:
        jwt.ExpiredSignatureError: Token 已过期
        jwt.InvalidTokenError: Token 无效
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])


# ==================== 数据库操作（线程池执行） ====================


def _generate_user_id(role: str) -> str:
    """根据角色生成业务 ID

    学生: stu_{uuid8}，管理员: adm_{uuid8}

    Args:
        role: student 或 admin

    Returns:
        业务 ID 字符串
    """
    prefix = "stu" if role == "student" else "adm"
    short_uuid = uuid.uuid4().hex[:8]
    return f"{prefix}_{short_uuid}"


def _get_connection() -> pyodbc.Connection:
    """获取 SQL Server 数据库连接（同步）

    延迟导入避免循环依赖。
    """
    from app.db.sqlserver import get_connection

    return get_connection()


def _db_register(username: str, password_hash: str, name: str, role: str) -> UserInfo:
    """在数据库中创建新用户（同步执行）

    Args:
        username: 登录账号
        password_hash: bcrypt 哈希后的密码
        name: 显示名称
        role: student 或 admin

    Returns:
        创建后的 UserInfo

    Raises:
        ValueError: 用户名已存在
        pyodbc.Error: 数据库异常
    """
    user_id = _generate_user_id(role)
    now = datetime.now()  # 业务时间戳：服务器本地时间，与 SQL Server GETDATE() 一致

    conn = _get_connection()
    try:
        cursor = conn.cursor()

        # 检查用户名唯一性
        cursor.execute("SELECT COUNT(1) FROM users WHERE username = ?", (username,))
        if cursor.fetchone()[0] > 0:
            raise ValueError(f"用户名 {username} 已被注册")

        # 插入用户记录
        cursor.execute(
            """
            INSERT INTO users (user_id, username, password_hash, name, role, created_at, is_active)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            """,
            (user_id, username, password_hash, name, role, now),
        )
        conn.commit()

        logger.info("新用户注册成功: user_id=%s, username=%s, role=%s", user_id, username, role)

        return UserInfo(
            user_id=user_id,
            username=username,
            name=name,
            role=role,
            created_at=now,
        )

    except pyodbc.Error as e:
        conn.rollback()
        logger.error("注册用户数据库错误: %s", e)
        raise
    finally:
        conn.close()


def _db_login(username: str) -> Optional[Tuple[dict, str]]:
    """根据用户名查询用户记录（同步执行）

    Args:
        username: 登录账号

    Returns:
        (用户字典, password_hash) 或 None
    """
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT user_id, username, name, role, avatar, password_hash, is_active, created_at
            FROM users
            WHERE username = ?
            """,
            (username,),
        )
        row = cursor.fetchone()
        if row is None:
            return None

        user_dict = {
            "user_id": row[0],
            "username": row[1],
            "name": row[2],
            "role": row[3],
            "avatar": row[4],
            "is_active": bool(row[6]),
            "created_at": row[7],
        }
        password_hash = row[5]
        return (user_dict, password_hash)
    finally:
        conn.close()


def _db_update_last_login(user_id: str) -> None:
    """更新用户最后登录时间（同步执行）

    该函数被 login() 以 asyncio.create_task 异步派发（不阻塞登录响应），
    因此必须吞掉全部异常（包括建连失败），避免后台任务产生
    "Task exception was never retrieved" 告警。
    """
    try:
        conn = _get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET last_login_at = ? WHERE user_id = ?",
                (datetime.now(), user_id),
            )
            conn.commit()
        except pyodbc.Error as e:
            conn.rollback()
            logger.warning("更新 last_login_at 失败: %s", e)
        finally:
            conn.close()
    except Exception as e:
        # 连接都建立不了（数据库不可用等）：只记日志，不影响登录主流程
        logger.warning("更新 last_login_at 失败（无法建立连接）: %s", e)


def _db_get_user_by_id(user_id: str) -> Optional[dict]:
    """根据 user_id 查询用户信息（同步执行）"""
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT user_id, username, name, role, avatar, created_at, last_login_at
            FROM users
            WHERE user_id = ? AND is_active = 1
            """,
            (user_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None

        return {
            "user_id": row[0],
            "username": row[1],
            "name": row[2],
            "role": row[3],
            "avatar": row[4],
            "created_at": row[5],
            "last_login_at": row[6],
        }
    finally:
        conn.close()


# ==================== 异步服务接口 ====================


async def register(username: str, password: str, name: str, role: str = "student") -> UserInfo:
    """注册新用户

    Args:
        username: 登录账号，3-50 字符
        password: 明文密码，最少 6 字符
        name: 显示名称
        role: 角色，默认 student

    Returns:
        新创建的 UserInfo

    Raises:
        ValueError: 用户名已存在
    """
    password_hash = hash_password(password)

    # 将同步数据库操作放到线程池执行，避免阻塞事件循环
    user_info = await asyncio.to_thread(
        _db_register, username, password_hash, name, role
    )
    return user_info


async def login(username: str, password: str) -> TokenResponse:
    """用户登录

    Args:
        username: 登录账号
        password: 明文密码

    Returns:
        TokenResponse: JWT 令牌及过期信息

    Raises:
        ValueError: 用户名或密码错误、账号已禁用
    """
    result = await asyncio.to_thread(_db_login, username)
    if result is None:
        raise ValueError("用户名或密码错误")

    user_dict, password_hash = result

    if not user_dict.get("is_active", False):
        raise ValueError("账号已被禁用，请联系管理员")

    if not verify_password(password, password_hash):
        raise ValueError("用户名或密码错误")

    # 异步更新最后登录时间
    asyncio.create_task(asyncio.to_thread(_db_update_last_login, user_dict["user_id"]))

    return create_jwt_token(
        user_id=user_dict["user_id"],
        username=user_dict["username"],
        role=user_dict["role"],
    )


async def get_user_by_id(user_id: str) -> Optional[UserInfo]:
    """根据用户 ID 获取用户信息

    Args:
        user_id: 用户业务 ID

    Returns:
        UserInfo 或 None（用户不存在/已禁用）
    """
    result = await asyncio.to_thread(_db_get_user_by_id, user_id)
    if result is None:
        return None

    return UserInfo(**result)
