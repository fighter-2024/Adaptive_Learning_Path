<template>
  <view class="page">
    <view class="brand">
      <text class="brand-title">自适应学习</text>
      <text class="brand-subtitle">登录后继续你的学习路径</text>
    </view>

    <view class="form-card">
      <text class="form-title">学生登录</text>

      <view class="field">
        <text class="field-label">用户名</text>
        <input v-model="form.username" class="field-input" maxlength="50" placeholder="请输入用户名" />
      </view>

      <view class="field">
        <text class="field-label">密码</text>
        <input v-model="form.password" class="field-input" password maxlength="100" placeholder="请输入密码" />
      </view>

      <button class="submit-button" :loading="loading" @click="handleLogin">登录</button>
      <button class="link-button" @click="goRegister">没有账号？去注册</button>
    </view>
  </view>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { showRequestError } from '@/utils/request'
import { useUserStore } from '@/store/user'

const userStore = useUserStore()
const loading = ref(false)
const form = reactive({ username: '', password: '' })

onShow(() => {
  if (userStore.isLoggedIn) uni.switchTab({ url: '/pages/index/index' })
})

async function handleLogin() {
  if (!form.username.trim() || !form.password) {
    uni.showToast({ title: '请输入用户名和密码', icon: 'none' })
    return
  }

  loading.value = true
  try {
    await userStore.login(form.username.trim(), form.password)
    uni.showToast({
      title: '登录成功',
      icon: 'success',
      duration: 800,
      complete: () => uni.switchTab({ url: '/pages/index/index' })
    })
  } catch (error) {
    showRequestError(error, '登录失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

function goRegister() {
  uni.navigateTo({ url: '/pages/auth/register' })
}
</script>

<style lang="scss" scoped>
.page {
  min-height: 100vh;
  padding: 120rpx 40rpx 40rpx;
  box-sizing: border-box;
  background: linear-gradient(180deg, #eef4ff 0%, #f5f7fa 55%);
}

.brand { text-align: center; margin-bottom: 56rpx; }
.brand-title { display: block; color: #4f8cff; font-size: 52rpx; font-weight: bold; }
.brand-subtitle { display: block; margin-top: 12rpx; color: #7f8c8d; font-size: 26rpx; }

.form-card { padding: 40rpx 32rpx 32rpx; border-radius: 20rpx; background: #fff; box-shadow: 0 12rpx 40rpx rgba(79, 140, 255, .08); }
.form-title { display: block; margin-bottom: 34rpx; color: #2c3e50; font-size: 36rpx; font-weight: bold; }
.field { margin-bottom: 26rpx; }
.field-label { display: block; margin-bottom: 12rpx; color: #606266; font-size: 24rpx; }
.field-input { height: 84rpx; padding: 0 24rpx; border: 1rpx solid #e8eaed; border-radius: 12rpx; box-sizing: border-box; font-size: 28rpx; }
.submit-button { margin-top: 18rpx; color: #fff; background: #4f8cff; border-radius: 12rpx; font-size: 30rpx; }
.link-button { margin-top: 18rpx; color: #4f8cff; background: transparent; font-size: 26rpx; }
</style>
