"""
简化版项目结构图 — 层级清晰、间距大、无重叠
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
import os, sys

sys.stdout.reconfigure(encoding="utf-8")
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False

fig, ax = plt.subplots(figsize=(16, 11))
ax.set_xlim(0, 16)
ax.set_ylim(0, 11)
ax.axis("off")
ax.set_facecolor("#f8f9fa")
fig.patch.set_facecolor("#f8f9fa")

C = {
    "root": "#1a1a2e", "server": "#16213e", "admin": "#0f3460",
    "frontend": "#533483", "algo": "#e94560", "kg": "#0a8f5c",
    "docs": "#555", "ref": "#999",
}

def box(ax, x, y, w, h, text, color, fs=10, bold=False, tc="white"):
    b = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.08",
                       facecolor=color, edgecolor=color, linewidth=1.2)
    ax.add_patch(b)
    ax.text(x + w/2, y + h/2, text, ha="center", va="center",
            fontsize=fs, color=tc, weight="bold" if bold else "normal")

def arr(ax, x1, y1, x2, y2):
    ax.plot([x1, x2], [y1, y2], color="#aaa", lw=1.0, zorder=0)

# ── 标题 ──
ax.text(8, 10.6, "Creation — 项目结构", ha="center", fontsize=18, weight="bold", color="#1a1a2e")

# ═══ L1: 根 ═══
box(ax, 6.5, 9.7, 3.0, 0.55, "creation/", C["root"], fs=13, bold=True)

# ═══ L2: 五大核心目录 ═══
l2 = [
    ("server/ 后端",  0.6, 8.2, 2.4, C["server"]),
    ("admin/ 管理后台", 3.4, 8.2, 2.6, C["admin"]),
    ("frontend/ 客户端", 6.4, 8.2, 3.2, C["frontend"]),
    ("algorithm/ 算法", 10.0, 8.2, 2.6, C["algo"]),
    ("kg-data/ 知识图谱", 13.0, 8.2, 2.6, C["kg"]),
]
for label, x, y, w, c in l2:
    box(ax, x, y, w, 0.5, label, c, fs=10, bold=True)
    arr(ax, 8, 9.7, x + w/2, y + 0.5)

# docs
box(ax, 0.6, 9.7, 2.4, 0.5, "docs/ 文档", C["docs"], fs=9, bold=True)
arr(ax, 8, 9.7, 1.8, 9.7)

# ═══ L3: 子项 ═══
# server
svr = [("main.py", 0.7, 7.1), ("config", 1.9, 7.1), ("routers", 0.7, 6.4),
       ("models", 1.9, 6.4), ("services", 0.7, 5.7), ("db", 1.9, 5.7)]
for t, x, y in svr:
    box(ax, x, y, 1.0, 0.38, t, C["server"], fs=8)
arr(ax, 1.8, 8.2, 1.2, 7.48)
arr(ax, 1.8, 8.2, 2.4, 7.48)

# admin
adm = [("知识图谱", 3.5, 7.1), ("题库管理", 4.8, 7.1), ("学生看板", 3.5, 6.4),
       ("社交管理", 4.8, 6.4), ("AI周报", 3.5, 5.7), ("系统配置", 4.8, 5.7)]
for t, x, y in adm:
    box(ax, x, y, 1.1, 0.38, t, C["admin"], fs=8)
arr(ax, 4.7, 8.2, 4.05, 7.48)
arr(ax, 4.7, 8.2, 5.35, 7.48)

# frontend
box(ax, 6.7, 7.1, 1.5, 0.38, "H5 网页版", C["frontend"], fs=8)
box(ax, 8.4, 7.1, 1.5, 0.38, "微信小程序", C["frontend"], fs=8)
arr(ax, 8.0, 8.2, 7.45, 7.48)
arr(ax, 8.0, 8.2, 9.15, 7.48)

# algorithm
box(ax, 10.2, 7.1, 2.2, 0.38, "DINA 认知诊断", C["algo"], fs=8)
box(ax, 10.2, 6.5, 2.2, 0.38, "路径规划", C["algo"], fs=8)
box(ax, 10.2, 5.9, 2.2, 0.38, "Notebooks", C["algo"], fs=8)
arr(ax, 11.3, 8.2, 11.3, 7.48)

# kg-data
box(ax, 13.3, 7.1, 2.0, 0.38, "data/", C["kg"], fs=8)
box(ax, 13.3, 6.5, 2.0, 0.38, "scripts/", C["kg"], fs=8)
box(ax, 13.3, 5.9, 2.0, 0.38, "output/", C["kg"], fs=8)
arr(ax, 14.3, 8.2, 14.3, 7.48)

# ═══ L4: 底层存储 ═══
box(ax, 3.0, 2.8, 3.0, 0.7, "Neo4j\n知识图谱存储", "#c0392b", fs=10, bold=True)
box(ax, 6.5, 2.8, 3.0, 0.7, "SQL Server\n用户/答题/社交", "#c0392b", fs=10, bold=True)
box(ax, 10.0, 2.8, 3.0, 0.7, "LLM API\nDeepSeek/通义千问", "#8e44ad", fs=10, bold=True)

# 数据流箭头
arr(ax, 4.5, 3.5, 4.5, 5.7)   # services -> neo4j
arr(ax, 8.0, 3.5, 8.0, 5.7)   # services -> sqlserver
arr(ax, 11.5, 3.5, 11.5, 5.7)  # services -> llm

ax.text(8, 2.1, "API: {\"code\":0,\"data\":...,\"message\":\"\"}  |  .env 配置  |  算法先 Notebook 再移植 service",
        ha="center", fontsize=9, color="#555")

# ── 保存 ──
out = os.path.join(os.path.dirname(__file__), "项目结构图.png")
fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
plt.close(fig)
print(f"OK: {out}")
