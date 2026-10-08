<template>
  <view class="page">
    <text class="title">AI 诊断解读</text>
    <text v-if="loading" class="state">正在读取诊断并生成解读…</text>
    <view v-else-if="error" class="state error"><text>{{ error }}</text><button @click="loadExplain">重试</button></view>
    <view v-else-if="result">
      <text v-if="result.degraded" class="state degraded">规则解读 · {{ result.degraded_reason }}</text>
      <view class="card"><rich-text :nodes="markdownNodes(result.explanation)" /></view>
      <view class="card"><text class="label">你的优势</text><text v-if="!result.strengths.length" class="hint">暂无已记录的优势知识点</text><text v-for="s in result.strengths" :key="s" class="tag strength">{{ s }}</text></view>
      <view class="card"><text class="label">需要加强</text><text v-if="!result.weaknesses.length" class="hint">暂无已记录的薄弱知识点</text><text v-for="s in result.weaknesses" :key="s" class="tag weak">{{ s }}</text></view>
      <view class="card"><text class="label">学习建议</text><rich-text :nodes="markdownNodes(result.suggestion)" /></view>
      <button @click="goLearning">打开学习总览</button>
    </view>
  </view>
</template>
<script setup>
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { post, showRequestError } from '@/utils/request'
import { markdownNodes } from '@/utils/aiText'
const result = ref(null), loading = ref(false), error = ref('')
async function loadExplain() {
  if (loading.value) return
  loading.value = true; error.value = ''; result.value = null
  try { result.value = await post('/api/student/diagnosis/explain', {}, { timeout: 35000 }) }
  catch (e) { error.value = showRequestError(e, '获取解读失败').message }
  finally { loading.value = false }
}
function goLearning() { uni.switchTab({ url: '/pages/learning/index' }) }
onShow(loadExplain)
</script>
<style scoped>
.page{padding:28rpx}.title{font-size:36rpx;font-weight:bold;display:block;margin-bottom:24rpx}.card{background:#fff;padding:28rpx;margin:20rpx 0;border-radius:16rpx;font-size:28rpx}.label{font-weight:bold;display:block;margin-bottom:18rpx}.tag{display:inline-block;padding:12rpx;margin:6rpx;border-radius:8rpx;font-size:24rpx}.strength{background:#e5f7e9;color:#237d39}.weak{background:#fff1df;color:#995712}.state{display:block;padding:24rpx;color:#66758b}.degraded{background:#fff5db;color:#8a5800}.error{color:#b33737}.hint{font-size:24rpx;color:#66758b}
</style>
