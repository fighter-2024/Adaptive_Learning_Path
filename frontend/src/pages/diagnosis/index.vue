<template>
  <view class="page">
    <!-- 诊断概览卡片 -->
    <view class="diag-card">
      <text class="diag-title">认知诊断结果</text>
      <text class="diag-time" v-if="lastDiagnosedAt">
        最近诊断：{{ lastDiagnosedAt }}
      </text>
      <text v-if="trace" class="diag-trace">
        本次使用 {{ trace.answer_count }} 条答题 · {{ trace.repeat_strategy === 'latest_attempt' ? '重复题取最近一次' : trace.repeat_strategy }} ·
        {{ trace.converged ? 'EM 已收敛' : 'EM 未收敛' }} · 迭代 {{ trace.iterations }} 次
      </text>

      <!-- 掌握率进度 -->
      <view class="diag-progress">
        <text class="progress-label">总体掌握率</text>
        <view class="progress-bar">
          <view class="progress-fill" :style="{ width: masteryPercent + '%' }"></view>
        </view>
        <text class="progress-value">{{ masteryPercent }}%</text>
      </view>

      <!-- 统计数据 -->
      <view class="diag-stats">
        <view class="stat-item">
          <text class="stat-value stat-mastered">{{ masteredCount }}</text>
          <text class="stat-label">已掌握</text>
        </view>
        <view class="stat-item">
          <text class="stat-value stat-learning">{{ learningCount }}</text>
          <text class="stat-label">学习中</text>
        </view>
        <view class="stat-item">
          <text class="stat-value stat-weak">{{ weakCount }}</text>
          <text class="stat-label">薄弱</text>
        </view>
      </view>
    </view>

    <!-- 操作按钮 -->
    <view class="action-buttons">
      <button class="btn-primary" :disabled="diagnosing" @click="runDiagnosis">
        {{ diagnosing ? '诊断中…' : '重新诊断' }}
      </button>
      <button class="btn-secondary" @click="goExplain">AI 解读</button>
    </view>

    <!-- 知识点掌握详情 -->
    <uni-section title="知识点掌握详情" type="line">
      <uni-list>
        <uni-list-item v-for="item in details" :key="item.id" :title="item.name"
                       :note="masteryNote(item)"
                       :rightText="statusMap[item.status]">
        </uni-list-item>
      </uni-list>
    </uni-section>

    <view v-if="diagnosisNotice && !loading && !errorMessage" class="empty">
      <text>{{ emptyReason }}</text>
      <button v-if="showLearningEntry" class="learning-button" @click="goLearning">去学习答题</button>
    </view>
    <view v-if="errorMessage" class="error-card">
      <text>{{ errorMessage }}</text>
      <button class="retry-button" @click="loadDiagnosis">重试</button>
    </view>
  </view>
</template>

<script setup>
import { ref, computed } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { useAppStore } from '@/store/app'
import { get, post, showRequestError } from '@/utils/request'

const appStore = useAppStore()

const lastDiagnosedAt = computed(() => appStore.lastDiagnosedAt || '')
const masteryPercent = computed(() => {
  const probabilities = details.value
    .map(item => item.mastery_probability)
    .filter(value => value !== null && value !== undefined)
  if (!probabilities.length) return Math.round(appStore.masteryRate * 100)
  return Math.round(probabilities.reduce((sum, value) => sum + value, 0) / probabilities.length * 100)
})

const details = ref([])
const masteredCount = ref(0)
const learningCount = ref(0)
const weakCount = ref(0)
const loading = ref(false)
const diagnosing = ref(false)
const errorMessage = ref('')
const emptyReason = ref('暂无有效答题记录，请先完成一些题目后再进行诊断。')
const diagnosisNotice = ref('')
const trace = ref(null)

const statusMap = { mastered: '已掌握', learning: '学习中', weak: '薄弱', not_started: '未开始' }
const showLearningEntry = computed(() => diagnosisNotice.value.includes('暂无有效答题记录'))

function masteryNote(item) {
  const probability = item?.mastery_probability
  if (probability === null || probability === undefined || !Number.isFinite(Number(probability))) {
    return '掌握度 暂无数据'
  }
  return `掌握度 ${Math.round(Number(probability) * 100)}%`
}

async function loadDiagnosis() {
  loading.value = true
  errorMessage.value = ''
  diagnosisNotice.value = ''
  try {
    const [kpData, latestDiagnosis] = await Promise.all([
      get('/api/student/knowledge-points'),
      get('/api/student/diagnosis')
    ])
    if (latestDiagnosis) {
      appStore.setDiagnosis(latestDiagnosis.alpha_vector, latestDiagnosis.diagnosed_at, latestDiagnosis.trace)
      trace.value = latestDiagnosis.trace || null
    } else {
      appStore.clearDiagnosis()
      trace.value = null
    }
    const list = Array.isArray(kpData?.list) ? kpData.list : []
    details.value = list
    masteredCount.value = list.filter(i => i.status === 'mastered').length
    learningCount.value = list.filter(i => i.status === 'learning').length
    weakCount.value = list.filter(i => i.status === 'weak').length
    if (!list.length) {
      emptyReason.value = '暂无知识点数据，请稍后重试。'
      diagnosisNotice.value = emptyReason.value
    } else if (!latestDiagnosis && list.every(item => item.status === 'not_started')) {
      emptyReason.value = '暂无有效答题记录，请先完成一些题目后再进行诊断。'
      diagnosisNotice.value = emptyReason.value
    } else if (!latestDiagnosis) {
      emptyReason.value = '已有掌握度快照，但还没有诊断会话；可点击“重新诊断”。'
      diagnosisNotice.value = emptyReason.value
    }
  } catch (error) {
    errorMessage.value = error?.message || '诊断数据加载失败，请重试'
    showRequestError(error, '加载诊断数据失败')
  } finally {
    loading.value = false
  }
}

async function runDiagnosis() {
  if (diagnosing.value) return
  diagnosing.value = true
  uni.showLoading({ title: '诊断中...' })
  try {
    const result = await post('/api/student/diagnosis')
    appStore.setDiagnosis(result.alpha_vector, result.diagnosed_at, result.trace)
    trace.value = result.trace || null
    diagnosisNotice.value = ''
    await loadDiagnosis()
    uni.showToast({ title: '诊断完成', icon: 'success' })
  } catch (error) {
    const requestError = showRequestError(error, '诊断失败，请稍后重试')
    if (requestError.code === 40002) {
      errorMessage.value = ''
      emptyReason.value = '暂无有效答题记录，请先完成一些题目后再进行诊断。'
      diagnosisNotice.value = emptyReason.value
    } else {
      errorMessage.value = requestError.message || '诊断失败，请稍后重试'
    }
  } finally {
    diagnosing.value = false
    uni.hideLoading()
  }
}

function goExplain() {
  uni.navigateTo({ url: '/pages/diagnosis/explain' })
}

function goLearning() {
  uni.switchTab({ url: '/pages/learning/index' })
}

onShow(() => {
  if (!diagnosing.value) loadDiagnosis()
})
</script>

<style lang="scss" scoped>
.page { padding: 20rpx; padding-bottom: 40rpx; }

.diag-card {
  background: #fff;
  border-radius: 16rpx;
  padding: 32rpx;
  margin-bottom: 24rpx;
}
.diag-title { font-size: 34rpx; font-weight: bold; }
.diag-time, .diag-trace { font-size: 24rpx; color: #7f8c8d; margin-top: 8rpx; display: block; }
.diag-trace { color: #526789; }

.diag-progress {
  margin-top: 28rpx;
  display: flex;
  align-items: center;
  gap: 16rpx;
}
.progress-label { font-size: 24rpx; color: #7f8c8d; white-space: nowrap; }
.progress-bar { flex: 1; height: 16rpx; background: #f0f2f5; border-radius: 8rpx; overflow: hidden; }
.progress-fill { height: 100%; background: linear-gradient(90deg, #4f8cff, #18bc37); border-radius: 8rpx; transition: width .5s; }
.progress-value { font-size: 28rpx; font-weight: bold; color: #4f8cff; }

.diag-stats {
  display: flex;
  justify-content: space-around;
  margin-top: 28rpx;
  text-align: center;
}
.stat-item { display: flex; flex-direction: column; }
.stat-value { font-size: 40rpx; font-weight: bold; }
.stat-mastered { color: #18bc37; }
.stat-learning { color: #4f8cff; }
.stat-weak { color: #f5a623; }
.stat-label { font-size: 24rpx; color: #7f8c8d; margin-top: 4rpx; }

.action-buttons {
  display: flex;
  gap: 20rpx;
  margin-bottom: 24rpx;
}
.btn-primary {
  flex: 1;
  background: #4f8cff;
  color: #fff;
  border: none;
  border-radius: 12rpx;
  padding: 24rpx;
  font-size: 28rpx;
}
.btn-secondary {
  flex: 1;
  background: #fff;
  color: #4f8cff;
  border: 1rpx solid #4f8cff;
  border-radius: 12rpx;
  padding: 24rpx;
  font-size: 28rpx;
}

.empty, .error-card { padding: 60rpx 0; text-align: center; color: #7f8c8d; font-size: 26rpx; }
.learning-button { width: 240rpx; margin-top: 24rpx; background: #4f8cff; color: #fff; font-size: 24rpx; }
.error-card { margin-top: 24rpx; padding: 28rpx; border-radius: 14rpx; background: #fff8f7; color: #c45c52; }
.retry-button { width: 180rpx; margin-top: 20rpx; background: #ee6f60; color: #fff; font-size: 24rpx; }
</style>
