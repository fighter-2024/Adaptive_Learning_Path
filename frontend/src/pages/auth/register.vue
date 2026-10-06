<template>
  <view class="page">
    <view class="header">
      <text class="title">创建学生账号</text>
      <text class="hint">注册后即可保存你的学习进度</text>
    </view>

    <view class="form-card">
      <view class="field">
        <text class="field-label">姓名</text>
        <input v-model="form.name" class="field-input" maxlength="50" placeholder="请输入姓名" />
      </view>

      <view class="field">
        <text class="field-label">用户名</text>
        <input v-model="form.username" class="field-input" maxlength="50" placeholder="3～50 个字符" />
      </view>

      <view class="field">
        <text class="field-label">密码</text>
        <input v-model="form.password" class="field-input" password maxlength="100" placeholder="至少 6 个字符" />
      </view>

      <view class="field">
        <text class="field-label">确认密码</text>
        <input v-model="form.confirmPassword" class="field-input" password maxlength="100" placeholder="请再次输入密码" />
      </view>

      <button class="submit-button" :loading="loading" @click="handleRegister">注册</button>
      <button class="link-button" @click="goLogin">已有账号？返回登录</button>
    </view>
  </view>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { showRequestError } from '@/utils/request'
import { useUserStore } from '@/store/user'

const userStore = useUserStore()
const loading = ref(false)
const form = reactive({ name: '', username: '', password: '', confirmPassword: '' })

async function handleRegister() {
  if (!form.name.trim() || !form.username.trim() || !form.password) {
    uni.showToast({ title: '请填写完整注册信息', icon: 'none' })
    return
  }
  if (form.password.length < 6) {
    uni.showToast({ title: '密码至少需要 6 个字符', icon: 'none' })
    return
  }
  if (form.password !== form.confirmPassword) {
    uni.showToast({ title: '两次输入的密码不一致', icon: 'none' })
    return
  }

  loading.value = true
  try {
    await userStore.register({
      name: form.name.trim(),
      username: form.username.trim(),
      password: form.password
    })
    uni.showToast({
      title: '注册成功，请登录',
      icon: 'success',
      duration: 1000,
      complete: () => uni.redirectTo({ url: '/pages/auth/login' })
    })
  } catch (error) {
    showRequestError(error, '注册失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

function goLogin() {
  uni.redirectTo({ url: '/pages/auth/login' })
}
</script>

<style lang="scss" scoped>
.page { min-height: 100vh; padding: 100rpx 40rpx 40rpx; box-sizing: border-box; background: #f5f7fa; }
.header { margin-bottom: 40rpx; text-align: center; }
.title { display: block; color: #2c3e50; font-size: 42rpx; font-weight: bold; }
.hint { display: block; margin-top: 12rpx; color: #7f8c8d; font-size: 26rpx; }
.form-card { padding: 40rpx 32rpx 32rpx; border-radius: 20rpx; background: #fff; }
.field { margin-bottom: 26rpx; }
.field-label { display: block; margin-bottom: 12rpx; color: #606266; font-size: 24rpx; }
.field-input { height: 84rpx; padding: 0 24rpx; border: 1rpx solid #e8eaed; border-radius: 12rpx; box-sizing: border-box; font-size: 28rpx; }
.submit-button { margin-top: 18rpx; color: #fff; background: #4f8cff; border-radius: 12rpx; font-size: 30rpx; }
.link-button { margin-top: 18rpx; color: #4f8cff; background: transparent; font-size: 26rpx; }
</style>
