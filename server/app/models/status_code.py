"""
统一响应状态码定义

按 AI 开发总则分段：
- 0          : 成功
- 40000-40999: 客户端错误（参数校验、权限等）
- 50000-50999: 服务端错误
- 60000-60999: 第三方服务异常
"""


class StatusCode:
    """业务状态码常量"""

    # 成功
    SUCCESS = 0

    # 客户端错误 40000-40999
    BAD_REQUEST = 40000
    # 契约 1.1 专用：删除知识点时该知识点仍被其他知识点依赖（见 docs/API契约文档.md
    # DELETE /knowledge-points/{id} 的响应示例，码值 40001 由契约固定）
    KNOWLEDGE_POINT_HAS_DEPENDENTS = 40001
    DIAGNOSIS_INSUFFICIENT_DATA = 40002
    GRAPH_QUERY_INVALID = 40003
    UNAUTHORIZED = 40100
    FORBIDDEN = 40101
    NOT_FOUND = 40400
    CONFLICT = 40900
    TOO_MANY_REQUESTS = 40901  # 触发速率限制（HTTP 429）

    # 服务端错误 50000-50999
    INTERNAL_ERROR = 50000
    DATABASE_ERROR = 50001
    NEO4J_ERROR = 50002

    # 第三方服务异常 60000-60999
    LLM_ERROR = 60000
    LLM_TIMEOUT = 60001
    LLM_INVALID_RESPONSE = 60002


# 可读的状态码消息映射
STATUS_MESSAGES = {
    StatusCode.SUCCESS: "成功",
    StatusCode.BAD_REQUEST: "请求参数错误",
    StatusCode.KNOWLEDGE_POINT_HAS_DEPENDENTS: "知识点被其他知识点依赖，无法删除",
    StatusCode.DIAGNOSIS_INSUFFICIENT_DATA: "答题记录不足，无法诊断",
    StatusCode.UNAUTHORIZED: "未登录或登录已过期",
    StatusCode.FORBIDDEN: "无权访问",
    StatusCode.NOT_FOUND: "资源不存在",
    StatusCode.CONFLICT: "资源冲突",
    StatusCode.TOO_MANY_REQUESTS: "请求过于频繁，请稍后再试",
    StatusCode.INTERNAL_ERROR: "服务器内部错误",
    StatusCode.DATABASE_ERROR: "数据库异常",
    StatusCode.NEO4J_ERROR: "图数据库异常",
    StatusCode.LLM_ERROR: "大模型服务异常",
    StatusCode.LLM_TIMEOUT: "大模型请求超时",
    StatusCode.LLM_INVALID_RESPONSE: "大模型返回异常",
}
