/**
 * 将当前学生知识点接口返回的数据归一化为首页与“我的”页可用的掌握统计。
 * 掌握率口径：status=mastered 的知识点数 / 当前接口返回的知识点总数。
 * 该口径使用后端按当前 JWT 计算的状态，不读取跨账号的本地缓存。
 */
export function summarizeKnowledgePoints(data) {
  const list = Array.isArray(data?.list) ? data.list : []
  const masteredCount = list.filter((item) => item?.status === 'mastered').length

  return {
    hasData: list.length > 0,
    totalKnowledgePoints: list.length,
    masteredCount,
    masteryPercent: list.length ? Math.round((masteredCount / list.length) * 100) : null
  }
}
