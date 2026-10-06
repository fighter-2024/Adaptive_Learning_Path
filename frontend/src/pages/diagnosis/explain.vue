<template>
  <view class="page">
    <view class="header">
      <text class="header-title">🤖 AI 诊断解读</text>
    </view>

    <!-- AI 解读内容 -->
    <view v-if="explanation" class="explain-card">
      <text class="explain-text">{{ explanation }}</text>
    </view>

    <!-- 优势 -->
    <uni-section v-if="strengths.length" title="🎯 你的优势" type="line">
      <uni-list>
        <uni-list-item v-for="s in strengths" :key="s" :title="s" />
      </uni-list>
    </uni-section>

    <!-- 薄弱 -->
    <uni-section v-if="weaknesses.length" title="⚠️ 需要加强" type="line">
      <uni-list>
        <uni-list-item v-for="w in weaknesses" :key="w" :title="w" />
      </uni-list>
    </uni-section>

    <!-- 建议 -->
    <view v-if="suggestion" class="suggestion-card">
      <text class="suggestion-label">💡 学习建议</text>
      <text class="suggestion-text">{{ suggestion }}</text>
    </view>

    <view v-if="!explanation && !loading" class="empty">
      <text class="empty-text">暂无诊断数据</text>
      <button class="btn-load" @click="loadExplain">获取 AI 解读</button>
    </view>
  </view>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { post, showRequestError } from '@/utils/request'

const explanation = ref('')
const strengths = ref([])
const weaknesses = ref([])
const suggestion = ref('')
const loading = ref(false)

async function loadExplain() {
  loading.value = true
  try {
    const data = await post('/api/student/diagnosis/explain')
    explanation.value = data.explanation || ''
    strengths.value = data.strengths || []
    weaknesses.value = data.weaknesses || []
    suggestion.value = data.suggestion || ''
  } catch (error) {
    showRequestError(error, '获取解读失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadExplain()
})
</script>

<style lang="scss" scoped>
.page { padding: 20rpx; padding-bottom: 40rpx; }
.header { margin-bottom: 24rpx; }
.header-title { font-size: 34rpx; font-weight: bold; }

.explain-card {
  background: #fff;
  border-radius: 16rpx;
  padding: 32rpx;
  margin-bottom: 24rpx;
}
.explain-text { font-size: 28rpx; line-height: 1.8; }

.suggestion-card {
  background: linear-gradient(135deg, #e8f8e8, #f0fff0);
  border-radius: 12rpx;
  padding: 24rpx;
  margin-top: 24rpx;
}
.suggestion-label { font-size: 26rpx; font-weight: 500; color: #18bc37; display: block; }
.suggestion-text { font-size: 26rpx; color: #2c3e50; margin-top: 8rpx; line-height: 1.6; display: block; }

.empty { padding: 80rpx 0; text-align: center; }
.empty-text { font-size: 28rpx; color: #7f8c8d; display: block; }
.btn-load { margin-top: 24rpx; background: #4f8cff; color: #fff; border: none; border-radius: 12rpx; padding: 18rpx 40rpx; font-size: 26rpx; }
</style>
