<template>
  <view class="page">
    <uni-section title="🏆 我的成就" type="line">
      <view class="achievements">
        <view v-for="ach in list" :key="ach.id" class="achievement-item" :class="{ locked: !ach.unlocked }">
          <view class="ach-icon">
            <text>{{ ach.unlocked ? ach.icon || '🏅' : '🔒' }}</text>
          </view>
          <view class="ach-info">
            <text class="ach-name">{{ ach.name }}</text>
            <text class="ach-desc">{{ ach.description }}</text>
            <text v-if="!ach.unlocked && ach.progress" class="ach-progress">
              进度：{{ ach.progress }}
            </text>
            <text v-if="ach.unlocked" class="ach-time">
              解锁于：{{ ach.unlocked_at }}
            </text>
          </view>
        </view>
      </view>
    </uni-section>

    <view v-if="!list.length" class="empty">
      <text>暂无成就数据</text>
      <text class="empty-hint">TODO: 对接 GET /api/student/social/achievements</text>
    </view>
  </view>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { get, showRequestError } from '@/utils/request'

const list = ref([])

async function loadAchievements() {
  try {
    const data = await get('/api/student/social/achievements')
    list.value = data.achievements || []
  } catch (error) {
    showRequestError(error, '加载成就失败')
  }
}

onMounted(() => {
  loadAchievements()
})
</script>

<style lang="scss" scoped>
.page { padding: 20rpx; padding-bottom: 40rpx; }

.achievements { display: flex; flex-direction: column; gap: 16rpx; }
.achievement-item {
  display: flex;
  align-items: flex-start;
  gap: 20rpx;
  background: #fff;
  border-radius: 12rpx;
  padding: 24rpx;
}
.achievement-item.locked { opacity: 0.6; }
.ach-icon { font-size: 44rpx; width: 60rpx; text-align: center; }
.ach-info { flex: 1; }
.ach-name { font-size: 28rpx; font-weight: 500; display: block; }
.ach-desc { font-size: 24rpx; color: #7f8c8d; margin-top: 4rpx; display: block; }
.ach-progress { font-size: 22rpx; color: #f5a623; margin-top: 4rpx; display: block; }
.ach-time { font-size: 22rpx; color: #18bc37; margin-top: 4rpx; display: block; }

.empty { padding: 80rpx 0; text-align: center; color: #7f8c8d; }
.empty-hint { font-size: 24rpx; color: #bdc3c7; margin-top: 12rpx; display: block; }
</style>
