<template>
  <view class="page">
    <!-- 用户信息卡片 -->
    <view class="user-card">
      <view class="avatar" @click="editProfile">
        <text class="avatar-text">{{ avatarInitial }}</text>
      </view>
      <view class="user-info">
        <text class="user-name">{{ userStore.userInfo.name || '未登录' }}</text>
        <text class="user-id">ID: {{ userStore.userInfo.userId || '—' }}</text>
      </view>
    </view>

    <!-- 学习统计 -->
    <view class="stats-row">
      <view class="stat-item">
        <text class="stat-val">{{ totalQuestions }}</text>
        <text class="stat-lbl">总做题数</text>
      </view>
      <view class="stat-item">
        <text class="stat-val">{{ masteredKp }}</text>
        <text class="stat-lbl">已掌握</text>
      </view>
      <view class="stat-item">
        <text class="stat-val">{{ streakDays }}天</text>
        <text class="stat-lbl">连续打卡</text>
      </view>
    </view>

    <!-- 功能菜单 -->
    <uni-section title="学习" type="line">
      <uni-list>
        <uni-list-item title="我的成就" showArrow @click="goPage('/pages/social/achievements')" />
        <uni-list-item title="学习周报" showArrow @click="goPage('/pages/report/report')" />
        <uni-list-item title="AI 答疑" showArrow @click="goPage('/pages/chat/index')" />
      </uni-list>
    </uni-section>

    <uni-section title="设置" type="line">
      <uni-list>
        <uni-list-item title="系统设置" showArrow @click="goPage('/pages/settings/index')" />
        <uni-list-item title="关于我们" showArrow />
      </uni-list>
    </uni-section>

    <!-- 退出登录 -->
    <button class="logout-btn" @click="handleLogout">退出登录</button>
  </view>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useUserStore } from '@/store/user'

const userStore = useUserStore()

const totalQuestions = ref(0)
const masteredKp = ref(0)
const streakDays = ref(0)

const avatarInitial = computed(() => {
  const name = userStore.userInfo.name
  return name ? name.charAt(0) : '?'
})

function goPage(url) {
  uni.navigateTo({ url })
}

function editProfile() {
  uni.showToast({ title: '个人信息编辑（TODO）', icon: 'none' })
}

function handleLogout() {
  uni.showModal({
    title: '提示',
    content: '确定退出登录？',
    success: (res) => {
      if (res.confirm) {
        userStore.logout()
        uni.showToast({ title: '已退出', icon: 'success' })
      }
    }
  })
}
</script>

<style lang="scss" scoped>
.page { padding-bottom: 40rpx; }

.user-card {
  display: flex;
  align-items: center;
  gap: 24rpx;
  background: linear-gradient(135deg, #4f8cff, #6ba0ff);
  padding: 40rpx 32rpx;
  margin-bottom: 20rpx;
}
.avatar {
  width: 100rpx;
  height: 100rpx;
  border-radius: 50%;
  background: rgba(255,255,255,.25);
  display: flex;
  align-items: center;
  justify-content: center;
}
.avatar-text { font-size: 44rpx; font-weight: bold; color: #fff; }
.user-info { flex: 1; }
.user-name { font-size: 34rpx; font-weight: bold; color: #fff; display: block; }
.user-id { font-size: 24rpx; color: rgba(255,255,255,.7); margin-top: 4rpx; display: block; }

.stats-row {
  display: flex;
  background: #fff;
  border-radius: 12rpx;
  padding: 24rpx 0;
  margin: 0 20rpx 24rpx;
}
.stat-item { flex: 1; text-align: center; }
.stat-val { font-size: 32rpx; font-weight: bold; color: #2c3e50; display: block; }
.stat-lbl { font-size: 22rpx; color: #7f8c8d; margin-top: 4rpx; display: block; }

.logout-btn {
  margin: 40rpx 20rpx;
  width: auto;
  background: #fff;
  color: #f36b6b;
  border: 1rpx solid #f36b6b;
  border-radius: 12rpx;
  padding: 20rpx;
  font-size: 28rpx;
}
</style>
