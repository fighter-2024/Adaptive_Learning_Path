<template>
  <view class="page">
    <!-- 排行榜切换 -->
    <uni-segmented-control :values="rankTypes" :current="currentRank" @clickItem="onRankChange"
                           styleType="button" />

    <!-- 排行榜 -->
    <view class="leaderboard">
      <view v-for="item in rankList" :key="item.rank" class="rank-item" :class="{ 'is-me': item.is_me }">
        <view class="rank-num">
          <text v-if="item.rank <= 3" class="rank-medal">{{ ['🥇','🥈','🥉'][item.rank - 1] }}</text>
          <text v-else class="rank-index">{{ item.rank }}</text>
        </view>
        <text class="rank-name">{{ item.student_name }}</text>
        <text class="rank-score">{{ formatScore(item.score) }}</text>
      </view>
    </view>

    <!-- 我的排名 -->
    <view class="my-rank" v-if="myRank > 0">
      <text>我的排名：第 {{ myRank }} 名</text>
    </view>

    <!-- 打卡区域 -->
    <view class="checkin-card">
      <view class="checkin-header">
        <text class="checkin-title">每日打卡</text>
        <text class="checkin-streak">已连续 {{ streakDays }} 天 🔥</text>
      </view>
      <button class="checkin-btn" @click="doCheckIn" :disabled="checkedIn">
        {{ checkedIn ? '今日已打卡 ✅' : '打卡' }}
      </button>
    </view>

    <!-- 成就入口 -->
    <view class="achievement-entry" @click="goAchievements">
      <text class="entry-icon">🏆</text>
      <text class="entry-text">查看我的成就</text>
      <text class="entry-arrow">›</text>
    </view>
  </view>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { get, post, showRequestError } from '@/utils/request'

const rankTypes = ['掌握率', '连续打卡', '积分']
const typeMap = ['mastery', 'streak', 'points']
const currentRank = ref(0)
const rankList = ref([])
const myRank = ref(0)

const streakDays = ref(0)
const checkedIn = ref(false)

function formatScore(score) {
  if (typeof score === 'number' && score <= 1) return `${Math.round(score * 100)}%`
  return String(score)
}

async function loadRank(type) {
  try {
    const data = await get('/api/student/social/leaderboard', { type, period: 'week' })
    rankList.value = data.list || []
    myRank.value = data.my_rank || 0
  } catch (error) {
    showRequestError(error, '加载排行榜失败')
  }
}

function onRankChange(e) {
  currentRank.value = e.currentIndex
  loadRank(typeMap[e.currentIndex])
}

async function doCheckIn() {
  try {
    const data = await post('/api/student/social/check-in')
    streakDays.value = data.streak_days || 0
    checkedIn.value = data.checked_in || false
  } catch (error) {
    showRequestError(error, '打卡失败，请稍后重试')
  }
}

function goAchievements() {
  uni.navigateTo({ url: '/pages/social/achievements' })
}

onMounted(() => {
  loadRank(typeMap[0])
})
</script>

<style lang="scss" scoped>
.page { padding: 20rpx; padding-bottom: 40rpx; }

.leaderboard {
  background: #fff;
  border-radius: 12rpx;
  overflow: hidden;
  margin-top: 20rpx;
  margin-bottom: 24rpx;
}
.rank-item {
  display: flex;
  align-items: center;
  padding: 20rpx 28rpx;
  border-bottom: 1rpx solid #f0f2f5;
}
.rank-item:last-child { border-bottom: none; }
.rank-item.is-me { background: #e8f0ff; }
.rank-num { width: 60rpx; text-align: center; }
.rank-medal { font-size: 36rpx; }
.rank-index { font-size: 28rpx; color: #7f8c8d; font-weight: bold; }
.rank-name { flex: 1; font-size: 28rpx; margin-left: 12rpx; }
.rank-score { font-size: 28rpx; font-weight: 500; color: #4f8cff; }
.my-rank { text-align: center; padding: 16rpx; font-size: 26rpx; color: #7f8c8d; }

.checkin-card {
  background: linear-gradient(135deg, #fff8e1, #fff3cd);
  border-radius: 16rpx;
  padding: 28rpx 32rpx;
  margin-bottom: 20rpx;
}
.checkin-header { display: flex; justify-content: space-between; align-items: center; }
.checkin-title { font-size: 30rpx; font-weight: bold; }
.checkin-streak { font-size: 24rpx; color: #f5a623; }
.checkin-btn {
  margin-top: 20rpx;
  width: 100%;
  background: #f5a623;
  color: #fff;
  border: none;
  border-radius: 12rpx;
  padding: 20rpx;
  font-size: 28rpx;
}

.achievement-entry {
  display: flex;
  align-items: center;
  background: #fff;
  border-radius: 12rpx;
  padding: 24rpx 28rpx;
  gap: 12rpx;
}
.entry-icon { font-size: 36rpx; }
.entry-text { flex: 1; font-size: 28rpx; }
.entry-arrow { font-size: 32rpx; color: #bdc3c7; }
</style>
