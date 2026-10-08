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
        <text class="overview-value">{{ masteryPercent === null ? '—' : masteryPercent + '%' }}</text>
        <text class="overview-label">掌握率</text>
        <text class="overview-note">已掌握 / 全部知识点</text>
      </view>
      <view class="overview-card card-green" @click="navigateTo('/pages/learning/index')">
        <text class="overview-value">{{ todayQuestions }}</text>
        <text class="overview-label">今日做题（未接入）</text>
      </view>
      <view class="overview-card card-orange" @click="navigateTo('/pages/social/index')">
        <text class="overview-value">{{ streakDays }}</text>
        <text class="overview-label">连续打卡（未接入）</text>
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
        <view class="quick-action" @click="navigateTo('/pages/chat/index')">
          <text class="action-icon">💬</text>
          <text class="action-text">AI 答疑</text>
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
        <view v-if="statsStatus === 'loading'" class="empty-hint">
          <text>正在读取学习统计…</text>
        </view>
        <view v-else-if="statsStatus === 'error'" class="empty-hint error-hint">
          <text>{{ statsError }}</text>
          <text class="retry-link" @click="loadStats">重试</text>
        </view>
        <view v-else-if="!recentList.length" class="empty-hint">
          <text>最近学习列表暂未接入</text>
          <text class="empty-subhint">此卡片不会用固定数值代替真实记录</text>
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
import { ref, watch } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { useUserStore } from '@/store/user'
import { get, showRequestError } from '@/utils/request'
import { summarizeKnowledgePoints } from '@/utils/learningStats'

const userStore = useUserStore()

const userName = ref('同学')
const todayGoal = ref('完成 5 道题目')
const masteryPercent = ref(null)
const todayQuestions = ref('—')
const streakDays = ref('—')
const statsStatus = ref('idle')
const statsError = ref('学习统计加载失败，请重试')
let statsRequestId = 0

const statusMap = {
  mastered: '已掌握',
  learning: '学习中',
  weak: '薄弱',
  not_started: '未开始'
}

/** 最近学习知识点 */
const recentList = ref([])

function resetStats() {
  masteryPercent.value = null
  todayQuestions.value = '—'
  streakDays.value = '—'
  recentList.value = []
}

watch(() => userStore.userInfo.userId, (userId, previousUserId) => {
  if (userId === previousUserId) return
  // 首次 /auth/me 恢复会话时让当前 loadStats() 继续完成；登录页切换账号时主动启动新账号读取。
  if (!previousUserId && userId && statsStatus.value === 'loading') {
    userName.value = userStore.userInfo.name || '同学'
    return
  }
  statsRequestId += 1
  resetStats()
  statsError.value = '学习统计加载失败，请重试'
  userName.value = userId ? (userStore.userInfo.name || '同学') : '同学'
  statsStatus.value = userId ? 'idle' : 'empty'
  if (userId) loadStats()
})

async function loadStats() {
  if (statsStatus.value === 'loading') return
  const requestId = ++statsRequestId
  resetStats()
  statsStatus.value = 'loading'

  const authenticated = await userStore.ensureAuthenticated(false)
  const userId = userStore.userInfo.userId
  if (!authenticated || !userId) {
    if (requestId !== statsRequestId) return
    statsStatus.value = 'error'
    statsError.value = userStore.sessionError || '当前登录状态无效，请重新登录'
    return
  }

  if (userStore.userInfo.name) {
    userName.value = userStore.userInfo.name
  }

  try {
    const data = await get('/api/student/knowledge-points')
    if (requestId !== statsRequestId || userId !== userStore.userInfo.userId) return

    const summary = summarizeKnowledgePoints(data)
    masteryPercent.value = summary.masteryPercent
    statsStatus.value = summary.hasData ? 'ready' : 'empty'
  } catch (error) {
    if (requestId !== statsRequestId) return
    statsStatus.value = 'error'
    statsError.value = showRequestError(error, '加载学习统计失败').message
  }
}

const TAB_BAR_PATHS = new Set([
  '/pages/index/index',
  '/pages/learning/index',
  '/pages/diagnosis/index',
  '/pages/social/index',
  '/pages/mine/index'
])

function navigateTo(url, params) {
  const path = String(url).split('?')[0]
  if (TAB_BAR_PATHS.has(path)) {
    uni.switchTab({ url: path })
    return
  }
  uni.navigateTo({ url: params ? `${url}?id=${encodeURIComponent(params.id)}` : url })
}

onShow(loadStats)
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
.overview-note { display: block; margin-top: 6rpx; color: #a1aab5; font-size: 18rpx; line-height: 1.2; }
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
.empty-subhint { display: block; margin-top: 10rpx; color: #a7afb8; font-size: 22rpx; }
.error-hint { color: #c45c52; }
.retry-link { display: block; margin-top: 12rpx; color: #4f8cff; }
</style>
