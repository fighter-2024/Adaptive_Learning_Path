<template>
  <view class="page">
    <view class="header">
      <text class="header-title">📊 学习周报</text>
      <text class="header-period">{{ report.week_start }} ~ {{ report.week_end }}</text>
    </view>

    <!-- 数据概览 -->
    <view class="report-stats">
      <view class="stat-card">
        <text class="stat-num">{{ report.questions_done || 0 }}</text>
        <text class="stat-label">答题数</text>
      </view>
      <view class="stat-card">
        <text class="stat-num">{{ correctRate }}%</text>
        <text class="stat-label">正确率</text>
      </view>
      <view class="stat-card">
        <text class="stat-num">{{ studyHours }}h</text>
        <text class="stat-label">学习时长</text>
      </view>
    </view>

    <!-- 新掌握 -->
    <uni-section v-if="report.new_mastered && report.new_mastered.length" title="🆕 本周新掌握" type="line">
      <uni-list>
        <uni-list-item v-for="kp in report.new_mastered" :key="kp.id" :title="kp.name" />
      </uni-list>
    </uni-section>

    <!-- 仍需加强 -->
    <uni-section v-if="report.still_weak && report.still_weak.length" title="🔧 仍需加强" type="line">
      <uni-list>
        <uni-list-item v-for="kp in report.still_weak" :key="kp.id" :title="kp.name" />
      </uni-list>
    </uni-section>

    <!-- AI 总结 -->
    <view v-if="report.ai_summary" class="ai-card">
      <text class="ai-label">🤖 AI 总结</text>
      <text class="ai-text">{{ report.ai_summary }}</text>
    </view>

    <view v-if="!report.week_start && !loading" class="empty">
      <text>暂无周报数据</text>
      <text class="empty-hint">TODO: 对接 GET /api/student/weekly-report</text>
    </view>
  </view>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { get, showRequestError } from '@/utils/request'

const report = ref({})
const loading = ref(false)

const correctRate = computed(() =>
  Math.round((report.value.correct_rate || 0) * 100)
)
const studyHours = computed(() =>
  Math.round((report.value.study_time_minutes || 0) / 60 * 10) / 10
)

async function loadReport() {
  loading.value = true
  try {
    const data = await get('/api/student/weekly-report')
    report.value = data || {}
  } catch (error) {
    showRequestError(error, '加载学习周报失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadReport()
})
</script>

<style lang="scss" scoped>
.page { padding: 20rpx; padding-bottom: 40rpx; }
.header { margin-bottom: 24rpx; }
.header-title { font-size: 34rpx; font-weight: bold; display: block; }
.header-period { font-size: 24rpx; color: #7f8c8d; margin-top: 8rpx; display: block; }

.report-stats {
  display: flex;
  gap: 16rpx;
  margin-bottom: 24rpx;
}
.stat-card {
  flex: 1;
  background: #fff;
  border-radius: 12rpx;
  padding: 28rpx 16rpx;
  text-align: center;
}
.stat-num { font-size: 36rpx; font-weight: bold; color: #4f8cff; display: block; }
.stat-label { font-size: 22rpx; color: #7f8c8d; margin-top: 6rpx; display: block; }

.ai-card {
  background: linear-gradient(135deg, #e8f0ff, #f0f5ff);
  border-radius: 12rpx;
  padding: 24rpx;
  margin-top: 24rpx;
}
.ai-label { font-size: 24rpx; color: #4f8cff; font-weight: 500; display: block; }
.ai-text { font-size: 26rpx; color: #2c3e50; margin-top: 8rpx; line-height: 1.6; display: block; }

.empty { padding: 80rpx 0; text-align: center; color: #7f8c8d; }
.empty-hint { font-size: 24rpx; color: #bdc3c7; margin-top: 12rpx; display: block; }
</style>
