"""
系统配置模块

使用 pydantic-settings 从 .env 文件和环境变量加载配置。
所有敏感信息（密钥、密码、连接串）禁止硬编码，一律走配置。
"""

import logging
import math
import os
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# 默认占位符，生产环境必须覆盖
_DEFAULT_SECRET_KEY = "change-me-in-production"
_INSECURE_SECRET_KEYS = {
    _DEFAULT_SECRET_KEY,
    "change-me-to-a-random-secret",
    "your-secret-key-here",
    "your_jwt_secret_here",
}

# .env 固定解析到 server/ 目录（本文件位于 server/app/config/settings.py），
# 避免因启动时的工作目录不同（如从仓库根目录 uvicorn server.app.main:app）
# 导致读不到 server/.env。来源优先级见 settings_customise_sources：.env 高于环境变量。
_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"


class Settings(BaseSettings):
    """应用全局配置，字段名大写自动映射到 .env 中的同名环境变量"""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        """调整配置来源优先级：`.env` 优先于进程环境变量。

        pydantic-settings 默认顺序是「环境变量 > .env」。本机开发时，任何残留的
        `SQLSERVER_*` / `NEO4J_*` 环境变量都会静默改变数据库连接方式：曾出现
        `SQLSERVER_ENCRYPT=yes` + `TrustServerCertificate=no` 生效，与实例的
        自生成证书握手失败（SQLSTATE 08001 / SEC_E_UNTRUSTED_ROOT），而 `.env`
        中明明是可用配置，导致反复出现「SQL 连不上」且难以定位。

        本项目以 `server/.env` 为唯一权威配置来源，故把 dotenv 提到 env 之前：
        显式传入的初始化参数（含测试）仍为最高优先级，`.env` 未定义的键
        依然可以由环境变量提供。

        Returns:
            按优先级从高到低排列的配置来源
        """
        return (
            init_settings,
            dotenv_settings,
            env_settings,
            file_secret_settings,
        )

    # ========== 应用基础信息 ==========
    APP_NAME: str = "Adaptive Learning System"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True
    ENVIRONMENT: str = "development"  # development / test / production

    # ========== Neo4j 图数据库 ==========
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = ""

    # ========== SQL Server 关系数据库 ==========
    SQLSERVER_DRIVER: str = "ODBC Driver 17 for SQL Server"
    SQLSERVER_HOST: str = "localhost"
    SQLSERVER_PORT: int = 1433
    SQLSERVER_DATABASE: str = "adaptive_learning"
    SQLSERVER_USER: str = "sa"
    SQLSERVER_PASSWORD: str = ""
    SQLSERVER_TRUSTED_CONNECTION: str = "no"  # yes / no，Windows 集成认证时用 yes
    SQLSERVER_ENCRYPT: str = "no"  # 生产环境建议 yes
    SQLSERVER_TRUST_SERVER_CERTIFICATE: str = "yes"  # 生产环境建议 no

    # ========== LLM 大模型 ==========
    LLM_PROVIDER: str = "deepseek"  # deepseek / qwen
    LLM_API_KEY: str = ""
    LLM_API_BASE: str = ""
    LLM_MODEL: str = "deepseek-chat"
    LLM_TIMEOUT: int = 30  # 请求超时（秒）

    # ========== DINA 认知诊断模型参数 ==========
    DINA_EM_MAX_ITERATIONS: int = 500
    DINA_EM_CONVERGENCE_THRESHOLD: float = 0.001
    DINA_S_INITIAL: float = 0.2  # 失误率初始值
    DINA_G_INITIAL: float = 0.2  # 猜测率初始值

    # ========== 学习路径算法参数 ==========
    # 四项权重必须处于 [0, 1] 且总和为 1；具体校验由路径服务复用，
    # 这样运行时管理端更新和启动时配置使用同一套规则。
    PATH_WEIGHT_MASTERY: float = 0.4
    PATH_WEIGHT_TARGET_DISTANCE: float = 0.3
    PATH_WEIGHT_DIFFICULTY: float = 0.2
    PATH_WEIGHT_TIME_COST: float = 0.1
    PATH_WEIGHT_PROFILE: str = "default-v1"

    # ========== JWT 认证 ==========
    SECRET_KEY: str = _DEFAULT_SECRET_KEY
    JWT_EXPIRE_MINUTES: int = 1440  # 24 小时

    # ========== 认证速率限制（防暴力破解，内存滑动窗口，按客户端 IP） ==========
    RATE_LIMIT_LOGIN_MAX_ATTEMPTS: int = 10  # 登录：窗口内最大尝试次数
    RATE_LIMIT_LOGIN_WINDOW_SECONDS: int = 300  # 登录：窗口长度（秒）
    RATE_LIMIT_REGISTER_MAX_ATTEMPTS: int = 10  # 注册：窗口内最大尝试次数
    RATE_LIMIT_REGISTER_WINDOW_SECONDS: int = 600  # 注册：窗口长度（秒）

    # ========== CORS 跨域配置 ==========
    # 逗号分隔的来源白名单；"*" 表示允许所有来源（仅开发环境）。
    # 注意：配置了具体来源时浏览器才允许携带凭证（allow_credentials），
    # 通配符 * 与凭证模式互斥（CORS 规范），生产环境请配置具体前端域名。
    CORS_ALLOW_ORIGINS: str = "*"

    # ========== 服务端口 ==========
    SERVER_HOST: str = "0.0.0.0"
    SERVER_PORT: int = 8000

    def describe_sqlserver(self) -> str:
        """返回不含密码的 SQL Server 有效连接参数摘要。

        用于启动日志与故障排查：连接失败时能直接看出实际生效的
        Encrypt / TrustServerCertificate / 认证方式，不必再靠猜。

        Returns:
            形如 `server=localhost,1433; database=...; Encrypt=no; ...` 的摘要
        """
        auth = (
            "Trusted_Connection=yes"
            if self.SQLSERVER_TRUSTED_CONNECTION.strip().lower() == "yes"
            else f"UID={self.SQLSERVER_USER}"
        )
        return (
            f"driver={self.SQLSERVER_DRIVER}; "
            f"server={self.SQLSERVER_HOST},{self.SQLSERVER_PORT}; "
            f"database={self.SQLSERVER_DATABASE}; "
            f"Encrypt={self.SQLSERVER_ENCRYPT}; "
            f"TrustServerCertificate={self.SQLSERVER_TRUST_SERVER_CERTIFICATE}; "
            f"{auth}"
        )

    @model_validator(mode="after")
    def _validate_secret_key(self) -> "Settings":
        """安全校验：生产环境下 SECRET_KEY 不能使用默认占位符

        默认值仅用于开发调试。部署前必须在 .env 中设置强随机密钥。
        """
        production_mode = self.ENVIRONMENT.strip().lower() in {
            "prod",
            "production",
        } or not self.DEBUG
        insecure_secret = self.SECRET_KEY.strip().lower() in {
            item.lower() for item in _INSECURE_SECRET_KEYS
        }
        if production_mode and (insecure_secret or len(self.SECRET_KEY.strip()) < 32):
            raise ValueError(
                "生产环境禁止使用默认或过短的 SECRET_KEY，请配置至少 32 个字符的随机密钥"
            )
        if insecure_secret:
            logger.warning(
                "\n"
                "  ╔══════════════════════════════════════════════════════════════╗\n"
                "  ║  ⚠️  安全警告: SECRET_KEY 仍为默认占位符                      ║\n"
                "  ║  JWT 令牌可被任何人伪造。请在 .env 中设置 SECRET_KEY 为        ║\n"
                "  ║  一个强随机字符串（建议 32+ 字节）。                           ║\n"
                "  ║  示例: python -c \"import secrets; print(secrets.token_hex(32))\" ║\n"
                "  ╚══════════════════════════════════════════════════════════════╝"
            )
        return self

    @model_validator(mode="after")
    def _validate_path_weights(self) -> "Settings":
        """启动时校验路径权重范围和总和，避免服务使用半合法配置。"""
        weights = (
            self.PATH_WEIGHT_MASTERY,
            self.PATH_WEIGHT_TARGET_DISTANCE,
            self.PATH_WEIGHT_DIFFICULTY,
            self.PATH_WEIGHT_TIME_COST,
        )
        if any(not math.isfinite(value) or value < 0 or value > 1 for value in weights):
            raise ValueError("路径权重必须都在 0 到 1 之间")
        if abs(sum(weights) - 1.0) > 0.0001:
            raise ValueError("路径权重总和必须为 1")
        if not self.PATH_WEIGHT_PROFILE.strip():
            raise ValueError("路径权重 profile 不能为空")
        return self

# 全局单例，各模块通过 from app.config import settings 引用
settings = Settings()
