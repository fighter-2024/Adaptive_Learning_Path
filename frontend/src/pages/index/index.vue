<template>
  <view class="page">
    <!-- 欢迎区域 -->
    <view class="hero">
      <text class="hero-greeting">你好，{{ userName }}</text>
      <text class="hero-subtitle">今日学习目标：{{ todayGoal }}</text>
    </view>

    <!-- 学习概览卡片 -->
    <view class="overview-grid">
      <view class="overview-card card-blue" @click="navigateTo('/pages/diagnosis/index')">
        <text class="overview-value">{{ masteryPercent }}%</text>
        <text class="overview-label">掌握率</text>
      </view>
      <view class="overview-card card-green" @click="navigateTo('/pages/learning/index')">
        <text class="overview-value">{{ todayQuestions }}</text>
        <text class="overview-label">今日做题</text>
      </view>
      <view class="overview-card card-orange" @click="navigateTo('/pages/social/index')">
        <text class="overview-value">{{ streakDays }}</text>
        <text class="overview-label">连续打卡</text>
      </view>
    </view>

    <!-- 快捷入口 -->
    <uni-section title="快捷入口" type="line">
      <view class="quick-actions">
        <view class="quick-action" @click="navigateTo('/pages/path/path')">
          <text class="action-icon">🗺️</text>
          <text class="action-text">学习路径</text>
        </view>
        <view class="quick-action" @click="navigateTo('/pages/diagnosis/index')">
          <text class="action-icon">🔍</text>
          <text class="action-text">认知诊断</text>
        </view>
        <view class="quick-action" @click="navigateTo('/pages/report/report')">
          <text class="action-icon">📊</text>
          <text class="action-text">学习周报</text>
        </view>
        <view class="quick-action" @click="navigateTo('/pages/social/achievements')">
          <text class="action-icon">🏆</text>
          <text class="action-text">我的成就</text>
        </view>
      </view>
    </uni-section>

    <!-- 最近学习 -->
    <uni-section title="继续学习" type="line">
      <view class="recent-list">
        <view v-if="!recentList.length" class="empty-hint">
          <text>暂无学习记录，去学习页面开始吧！</text>
        </view>
        <view v-for="item in recentList" :key="item.id" class="recent-item"
              @click="navigateTo('/pages/learning/detail', { id: item.id })">
          <view class="recent-info">
            <text class="recent-name">{{ item.name }}</text>
            <text class="recent-chapter">{{ item.chapter }}</text>
          </view>
          <text class="recent-status" :class="item.status">
            {{ statusMap[item.status] }}
          </text>
        </view>
      </view>
    </uni-section>
  </view>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useUserStore } from '@/store/user'
import { useAppStore } from '@/store/app'

const userStore = useUserStore()
const appStore = useAppStore()

const userName = ref('同学')
const todayGoal = ref('完成 5 道题目')
const masteryPercent = ref(0)
const todayQuestions = ref(0)
const streakDays = ref(0)

const statusMap = {
  mastered: '已掌握',
  learning: '学习中',
  weak: '薄弱',
  not_started: '未开始'
}

/** 最近学习知识点 */
const recentList = ref([
  // { id: 'kp_001', name: '一元二次方程的定义', chapter: '一元二次方程', status: 'mastered' }
])

onMounted(() => {
  if (userStore.userInfo.name) {
    userName.value = userStore.userInfo.name
  }
  masteryPercent.value = Math.round(appStore.masteryRate * 100)
  // TODO: 从 API 获取真实数据 — todayQuestions, streakDays, recentList
})

function navigateTo(url, params) {
  uni.navigateTo({ url: params ? `${url}?id=${params.id}` : url })
}
</script>

<style lang="scss" scoped>
.page {
  padding: 20rpx;
  padding-bottom: 40rpx;
}

.hero {
  background: linear-gradient(135deg, #4f8cff 0%, #6ba0ff 100%);
  border-radius: 16rpx;
  padding: 40rpx 32rpx;
  margin-bottom: 24rpx;
  color: #fff;
}
.hero-greeting { font-size: 40rpx; font-weight: bold; display: block; }
.hero-subtitle { font-size: 26rpx; opacity: 0.85; margin-top: 8rpx; display: block; }

.overview-grid {
  display: flex;
  gap: 16rpx;
  margin-bottom: 24rpx;
}
.overview-card {
  flex: 1;
  text-align: center;
  padding: 28rpx 0;
  border-radius: 12rpx;
  background: #fff;
}
.overview-value { font-size: 40rpx; font-weight: bold; display: block; }
.overview-label { font-size: 24rpx; color: #7f8c8d; margin-top: 4rpx; }
.card-blue .overview-value { color: #4f8cff; }
.card-green .overview-value { color: #18bc37; }
.card-orange .overview-value { color: #f5a623; }

.quick-actions {
  display: flex;
  justify-content: space-around;
  background: #fff;
  border-radius: 12rpx;
  padding: 24rpx 16rpx;
}
.quick-action {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8rpx;
}
.action-icon { font-size: 44rpx; }
.action-text { font-size: 24rpx; color: #2c3e50; }

.recent-list {
  background: #fff;
  border-radius: 12rpx;
  overflow: hidden;
}
.recent-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 24rpx 28rpx;
  border-bottom: 1rpx solid #f0f2f5;
}
.recent-item:last-child { border-bottom: none; }
.recent-name { font-size: 28rpx; font-weight: 500; }
.recent-chapter { font-size: 24rpx; color: #7f8c8d; display: block; margin-top: 4rpx; }
.recent-status { font-size: 24rpx; padding: 4rpx 12rpx; border-radius: 8rpx; }
.recent-status.mastered { background: #e8f8e8; color: #18bc37; }
.recent-status.learning { background: #e8f0ff; color: #4f8cff; }
.recent-status.weak { background: #fff3e0; color: #f5a623; }
.recent-status.not_started { background: #f0f2f5; color: #7f8c8d; }

.empty-hint {
  padding: 40rpx;
  text-align: center;
  color: #7f8c8d;
  font-size: 26rpx;
}
</style>
