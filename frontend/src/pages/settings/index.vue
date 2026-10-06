<template>
  <view class="page">
    <uni-section title="通知设置" type="line">
      <uni-list>
        <uni-list-item title="学习提醒" showSwitch :switchChecked="switches.reminder"
                       @switchChange="(e) => toggle('reminder', e)" />
        <uni-list-item title="打卡提醒" showSwitch :switchChecked="switches.checkin"
                       @switchChange="(e) => toggle('checkin', e)" />
        <uni-list-item title="周报推送" showSwitch :switchChecked="switches.weeklyReport"
                       @switchChange="(e) => toggle('weeklyReport', e)" />
      </uni-list>
    </uni-section>

    <uni-section title="数据" type="line">
      <uni-list>
        <uni-list-item title="清除缓存" showArrow @click="clearCache" />
        <uni-list-item title="重新诊断" showArrow @click="reDiagnosis" />
      </uni-list>
    </uni-section>

    <uni-section title="关于" type="line">
      <uni-list>
        <uni-list-item title="版本" :rightText="'v1.0.0'" />
        <uni-list-item title="项目说明" showArrow />
      </uni-list>
    </uni-section>
  </view>
</template>

<script setup>
import { ref } from 'vue'

const switches = ref({
  reminder: true,
  checkin: true,
  weeklyReport: true
})

function toggle(key, e) {
  switches.value[key] = e.value
  // TODO: 持久化设置
  uni.setStorageSync(`setting_${key}`, e.value)
}

function clearCache() {
  uni.showModal({
    title: '提示',
    content: '确定清除本地缓存？',
    success: (res) => {
      if (res.confirm) {
        uni.clearStorageSync()
        uni.showToast({ title: '缓存已清除', icon: 'success' })
      }
    }
  })
}

function reDiagnosis() {
  uni.showModal({
    title: '提示',
    content: '将根据全部答题记录重新进行认知诊断，是否继续？',
    success: (res) => {
      if (res.confirm) {
        uni.navigateTo({ url: '/pages/diagnosis/index' })
      }
    }
  })
}
</script>

<style lang="scss" scoped>
.page { padding-bottom: 40rpx; }
</style>
