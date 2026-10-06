/**
 * app.js — 应用全局状态管理（Pinia）
 *
 * 管理跨页面的全局状态：
 *   - 学生诊断结果（α 向量）
 *   - 当前锁定知识点
 *   - 全局加载/错误状态
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useAppStore = defineStore('app', () => {
  // ========== 状态 ==========

  /**
   * DINA 诊断结果 — α 向量
   * 结构：{ "kp_001": 0.92, "kp_002": 0.78, ... }
   */
  const alphaVector = ref({})

  /** 最近一次诊断时间 */
  const lastDiagnosedAt = ref('')

  /** 最近一次诊断的可追踪字段 */
  const diagnosisTrace = ref(null)

  /** 诊断成功后的数据失效版本，供路径等页面刷新真实状态 */
  const diagnosisVersion = ref(0)

  /** 全屏加载中 */
  const loading = ref(false)

  /** 全局提示信息 */
  const toastMessage = ref('')

  // ========== 计算属性 ==========

  /** 知识点总数（α 向量维度） */
  const totalKnowledgePoints = computed(() => Object.keys(alphaVector.value).length)

  /** 已掌握知识点列表（概率 ≥ 0.8） */
  const masteredPoints = computed(() =>
    Object.entries(alphaVector.value)
      .filter(([, prob]) => prob >= 0.8)
      .map(([id]) => id)
  )

  /** 薄弱知识点列表（概率 < 0.4） */
  const weakPoints = computed(() =>
    Object.entries(alphaVector.value)
      .filter(([, prob]) => prob < 0.4)
      .map(([id]) => id)
  )

  /** 掌握率（已掌握 / 总知识点数） */
  const masteryRate = computed(() => {
    const total = totalKnowledgePoints.value
    if (total === 0) return 0
    return masteredPoints.value.length / total
  })

  // ========== 方法 ==========

  /**
   * 更新诊断结果
   * @param {Object} alpha - α 向量
   * @param {string} diagnosedAt - 诊断时间 (ISO 8601)
   * @param {Object|null} trace - 诊断可追踪字段
   */
  function setDiagnosis(alpha, diagnosedAt = '', trace = null) {
    alphaVector.value = { ...alpha }
    lastDiagnosedAt.value = diagnosedAt || new Date().toISOString()
    diagnosisTrace.value = trace
    diagnosisVersion.value += 1
  }

  /** 清空当前用户没有历史诊断时的页面状态。 */
  function clearDiagnosis() {
    alphaVector.value = {}
    lastDiagnosedAt.value = ''
    diagnosisTrace.value = null
  }

  /** 显示全局加载 */
  function showLoading() {
    loading.value = true
  }

  /** 隐藏全局加载 */
  function hideLoading() {
    loading.value = false
  }

  /** 显示轻提示 */
  function toast(msg) {
    toastMessage.value = msg
    uni.showToast({ title: msg, icon: 'none', duration: 2000 })
  }

  return {
    alphaVector,
    lastDiagnosedAt,
    diagnosisTrace,
    diagnosisVersion,
    loading,
    toastMessage,
    totalKnowledgePoints,
    masteredPoints,
    weakPoints,
    masteryRate,
    setDiagnosis,
    clearDiagnosis,
    showLoading,
    hideLoading,
    toast
  }
})
