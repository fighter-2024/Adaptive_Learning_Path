<template>
  <view class="page">
    <!-- 知识点信息 -->
    <view v-if="detail" class="detail-card">
      <text class="detail-name">{{ detail.name }}</text>
      <text class="detail-desc">{{ detail.description }}</text>

      <view class="detail-meta">
        <view class="meta-item">
          <text class="meta-label">难度</text>
          <text class="meta-value">{{ difficultyStars }}</text>
        </view>
        <view class="meta-item">
          <text class="meta-label">预计用时</text>
          <text class="meta-value">{{ detail.estimated_time }} 分钟</text>
        </view>
        <view class="meta-item">
          <text class="meta-label">掌握概率</text>
          <text class="meta-value" :class="masteryClass">{{ masteryPercent }}%</text>
        </view>
      </view>
    </view>

    <!-- 前置知识点 -->
    <uni-section title="前置知识" type="line">
      <uni-list v-if="prerequisites.length">
        <uni-list-item v-for="p in prerequisites" :key="p.id" :title="p.name"
                       :rightText="p.mastered ? '已掌握 ✅' : '未掌握'"
                       @click="goDetail(p.id)">
        </uni-list-item>
      </uni-list>
      <view v-else class="empty-tip">
        <text>无前置依赖，可直接学习</text>
      </view>
    </uni-section>

    <!-- 关联题目 -->
    <uni-section title="练习题目" type="line">
      <uni-list v-if="questions.length">
         <uni-list-item v-for="q in questions" :key="q.id" :title="q.content"
                        :note="`${q.type === 'single_choice' ? '单选题' : '多选题'} · 难度 ${q.difficulty}`"
                        :rightText="q.done ? '已做' : '未做'"
                        @click="goQuiz()">
        </uni-list-item>
      </uni-list>
      <view v-else class="empty-tip">
        <text>暂无关联题目</text>
      </view>
    </uni-section>

    <!-- 操作 -->
    <view class="bottom-actions">
      <button class="btn-quiz" @click="goQuiz()">开始答题</button>
      <button class="btn-chat" @click="goChat">问 AI</button>
    </view>
  </view>
</template>

<script setup>
import { ref, computed } from 'vue'
import { onLoad, onShow } from '@dcloudio/uni-app'
import { get, showRequestError } from '@/utils/request'

const knowledgePointId = ref('')
const detail = ref(null)
const prerequisites = ref([])
const questions = ref([])

const masteryPercent = computed(() => Math.round((detail.value?.mastery_probability || 0) * 100))
const masteryClass = computed(() => masteryPercent.value >= 80 ? 'mastered' : masteryPercent.value >= 40 ? 'learning' : 'weak')
const difficultyStars = computed(() => {
  const d = detail.value?.difficulty || 0
  return '⭐'.repeat(Math.round(d * 5))
})

async function loadData() {
  try {
    const id = knowledgePointId.value
    if (!id) return
    const data = await get(`/api/student/knowledge-points/${id}`)
    detail.value = data
    prerequisites.value = data.prerequisites || []
    questions.value = data.questions || []
  } catch (error) {
    showRequestError(error, '加载知识点详情失败')
  }
}

function goDetail(id) {
  uni.navigateTo({ url: `/pages/learning/detail?id=${id}` })
}

function goQuiz() {
  const id = encodeURIComponent(knowledgePointId.value)
  uni.navigateTo({ url: `/pages/quiz/quiz?knowledge_point_id=${id}` })
}

function goChat() {
  uni.navigateTo({ url: `/pages/chat/index?kpId=${encodeURIComponent(knowledgePointId.value)}` })
}

onLoad((options = {}) => {
  knowledgePointId.value = options.id || options.knowledge_point_id || ''
  loadData()
})

// 答题成功后返回本页时重新读取掌握度、题目完成状态和前置知识状态。
onShow(() => {
  if (knowledgePointId.value && detail.value) loadData()
})
</script>

<style lang="scss" scoped>
.page { padding: 20rpx; padding-bottom: 140rpx; }

.detail-card {
  background: #fff;
  border-radius: 16rpx;
  padding: 32rpx;
  margin-bottom: 24rpx;
}
.detail-name { font-size: 36rpx; font-weight: bold; display: block; }
.detail-desc { font-size: 26rpx; color: #7f8c8d; margin-top: 12rpx; line-height: 1.6; display: block; }

.detail-meta { display: flex; margin-top: 20rpx; gap: 32rpx; }
.meta-item { display: flex; flex-direction: column; }
.meta-label { font-size: 22rpx; color: #7f8c8d; }
.meta-value { font-size: 26rpx; font-weight: 500; margin-top: 4rpx; }
.meta-value.mastered { color: #18bc37; }
.meta-value.learning { color: #4f8cff; }
.meta-value.weak { color: #f5a623; }

.empty-tip { padding: 32rpx; text-align: center; color: #7f8c8d; font-size: 26rpx; }

.bottom-actions {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  display: flex;
  gap: 20rpx;
  padding: 20rpx;
  background: #fff;
  box-shadow: 0 -2rpx 12rpx rgba(0,0,0,.06);
}
.btn-quiz { flex: 1; background: #4f8cff; color: #fff; border: none; border-radius: 12rpx; padding: 22rpx; font-size: 28rpx; }
.btn-chat { flex: 1; background: #fff; color: #4f8cff; border: 1rpx solid #4f8cff; border-radius: 12rpx; padding: 22rpx; font-size: 28rpx; }
</style>
