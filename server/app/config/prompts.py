"""
大模型 Prompt 模板集中管理（AI开发总则第八章「AI 大模型调用规范」）

Prompt 模板单独放本文件，业务逻辑里不硬编码 Prompt。
当前包含：学习路径推荐的通俗解释（对照 API 契约「2.4 学习路径」
GET /path/explain）。后续诊断解读、错题归因、周报等 Prompt 也应加到这里。

本模块保持零依赖：只拼字符串，不 import 业务模型。
"""

from typing import List, Optional

# 路径推荐解释系统提示词：限定助教身份、语气与输出要求
PATH_EXPLAIN_SYSTEM_PROMPT = (
    "你是一名耐心的自适应学习系统助教，面向初中学生。"
    "请根据用户提供的推荐学习路径，用通俗、鼓励的语气解释："
    "为什么按这个顺序学习、每一步的作用，以及总体时间安排建议。"
    "要求：不超过 300 字；称呼学生为「你」；不要编造路径之外的知识点；"
    "不要使用 Markdown 列表符号，用自然段落表达。"
)


def build_path_explain_user_prompt(
    target_name: Optional[str],
    steps: List[dict],
) -> str:
    """构建路径推荐解释的用户提示词

    Args:
        target_name: 目标知识点名称；None 表示全局推荐（无目标）
        steps: 路径步骤列表，每项需含 order / name /
            mastery_probability / difficulty / estimated_time / reason

    Returns:
        拼装好的用户提示词文本
    """
    lines: List[str] = []
    if target_name:
        lines.append(f"学习目标：掌握「{target_name}」。")
    else:
        lines.append("学习目标：系统推荐的全局下一步。")
    lines.append("推荐学习路径如下：")
    for step in steps:
        if step.get("mastery_probability") is not None:
            mastery_text = f"当前掌握 {step['mastery_probability']:.0%}"
        else:
            mastery_text = "尚未开始学习"
        lines.append(
            f"第{step['order']}步：{step['name']}（{mastery_text}，"
            f"难度 {step['difficulty']:.2f}，预计 {step['estimated_time']} 分钟）。"
            f"推荐理由：{step['reason']}。"
        )
    lines.append("请向学生解释这条路径。")
    return "\n".join(lines)
