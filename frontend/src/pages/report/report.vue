<template>
  <view class="page">
    <text class="title">学习周报</text>
    <view class="week-bar"><button size="mini" :disabled="loading" @click="changeWeek(-7)">上一周</button><text>{{ weekStart }}</text><button size="mini" :disabled="loading || weekStart >= currentWeek" @click="changeWeek(7)">下一周</button></view>
    <text v-if="loading" class="state">正在统计本周学习记录…</text>
    <view v-else-if="error" class="state error"><text>{{ error }}</text><button @click="loadReport">重试</button></view>
    <view v-else-if="report">
      <text class="hint">{{ report.week_start }} ～ {{ report.week_end }}</text>
      <view class="stats"><view class="stat"><text class="number">{{ report.questions_done }}</text><text>作答次数</text></view><view class="stat"><text class="number">{{ Math.round(report.correct_rate * 100) }}%</text><text>正确率</text></view><view class="stat"><text class="number">{{ report.study_time_minutes }}</text><text>作答分钟</text></view></view>
      <text v-if="!report.questions_done" class="state">本周暂无作答记录。打开学习总览开始练习。</text>
      <view class="card"><text class="label">本周新掌握</text><text v-if="!report.new_mastered.length" class="hint">暂无已记录的新掌握知识点</text><view v-for="kp in report.new_mastered" :key="kp.id" class="kp" @click="goDetail(kp.id)">{{ kp.name }} →</view></view>
      <view class="card"><text class="label">仍需加强</text><text v-if="!report.still_weak.length" class="hint">暂无已记录的薄弱知识点</text><view v-for="kp in report.still_weak" :key="kp.id" class="kp weak" @click="goDetail(kp.id)">{{ kp.name }} →</view></view>
      <view class="card"><text class="label">{{ report.degraded ? '规则总结' : 'AI 总结' }}</text><text v-if="report.degraded" class="degraded">{{ report.degraded_reason }}</text><rich-text :nodes="markdownNodes(report.ai_summary)" /></view>
      <text class="hint">{{ report.cached ? '已使用本周缓存' : '本次已生成' }} · {{ report.generated_at.slice(0,19).replace('T',' ') }}</text>
      <text class="hint">掌握变化依据诊断快照，本周结合当前掌握记录；作答时长来自提交记录。</text>
      <button :disabled="loading" @click="loadReport">刷新周报</button>
    </view>
  </view>
</template>
<script setup>
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { get, showRequestError } from '@/utils/request'
import { markdownNodes } from '@/utils/aiText'
function dateText(d) { return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}` }
const today = new Date(); today.setDate(today.getDate() - (today.getDay()+6)%7)
const currentWeek = dateText(today), weekStart = ref(currentWeek)
const report = ref(null), loading = ref(false), error = ref('')
async function loadReport() {
  if (loading.value) return
  loading.value = true; error.value = ''; report.value = null
  try { report.value = await get('/api/student/weekly-report', { week_start: weekStart.value }, { timeout: 35000 }) }
  catch (e) { error.value = showRequestError(e, '加载周报失败').message }
  finally { loading.value = false }
}
function changeWeek(days) { const d = new Date(`${weekStart.value}T12:00:00`); d.setDate(d.getDate()+days); weekStart.value = dateText(d); loadReport() }
function goDetail(id) { uni.navigateTo({ url: `/pages/learning/detail?id=${encodeURIComponent(id)}` }) }
onShow(loadReport)
</script>
<style scoped>
.page{padding:28rpx}.title{font-size:36rpx;font-weight:bold}.week-bar{display:flex;align-items:center;gap:14rpx;margin:24rpx 0;font-size:26rpx}.week-bar button{margin:0}.stats{display:flex;gap:12rpx;margin-top:24rpx}.stat{flex:1;text-align:center;background:white;padding:24rpx 8rpx;border-radius:12rpx;font-size:24rpx}.number{display:block;font-size:38rpx;color:#3979d8;margin-bottom:8rpx;font-weight:bold}.card{background:white;padding:28rpx;margin:24rpx 0;border-radius:16rpx;font-size:28rpx}.label{display:block;font-weight:bold;margin-bottom:18rpx}.hint{display:block;color:#66758b;font-size:23rpx;margin:16rpx 0}.kp{padding:18rpx;background:#e9f5ec;color:#237d39;border-radius:8rpx;margin:8rpx 0}.weak{background:#fff1df;color:#995712}.state{padding:24rpx;display:block;color:#66758b}.error{color:#b33737}.degraded{display:block;color:#8a5800;font-size:24rpx;margin-bottom:14rpx}
</style>
