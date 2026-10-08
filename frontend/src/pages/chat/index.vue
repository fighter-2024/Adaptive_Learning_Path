<template>
  <view class="page">
    <view class="header">
      <text class="title">{{ kpName ? `${kpName} · 答疑` : 'AI 学习答疑' }}</text>
      <text class="hint">{{ kpId ? '围绕当前知识点讨论，点击卡片可返回学习。' : '输入知识点名称或具体算式，逐步理解解题方法。' }}</text>
      <button size="mini" :disabled="waiting" @click="clearChat">清空本次对话</button>
    </view>
    <view v-if="sessionError" class="error">{{ sessionError }}<button @click="initialize">重试登录校验</button></view>
    <scroll-view class="chat-list" scroll-y :scroll-into-view="scrollToId" scroll-with-animation>
      <view v-if="!messages.length" class="welcome">你好！可以先描述你卡住的步骤。我会结合知识资料帮助你理解。</view>
      <view v-for="(msg, idx) in messages" :key="idx" :id="'msg-' + idx" class="msg-item" :class="msg.role">
        <view class="bubble">
          <rich-text v-if="msg.role === 'assistant'" :nodes="markdownNodes(msg.content)" />
          <text v-else class="content">{{ msg.content }}</text>
          <text v-if="msg.degraded" class="degraded">规则答疑 · {{ msg.degraded_reason }}</text>
          <text v-if="msg.failed" class="error">发送失败，此条未加入历史。可在输入框重试。</text>
          <view v-for="kp in msg.related_knowledge_points || []" :key="kp.id" class="kp-card" @click="goDetail(kp.id)">
            <text>{{ kp.name }}</text><text>查看知识点 →</text>
          </view>
        </view>
      </view>
      <view v-if="waiting" id="typing" class="welcome">AI 正在思考…</view>
    </scroll-view>
    <view class="chat-input">
      <textarea v-model="inputText" class="input-field" placeholder="输入问题（最多2000字）" :maxlength="2000" auto-height :disabled="waiting || !ready" />
      <button class="btn-send" @click="sendMessage" :disabled="!ready || !inputText.trim() || waiting">发送</button>
    </view>
  </view>
</template>

<script setup>
import { ref, nextTick } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { get, post, showRequestError } from '@/utils/request'
import { useUserStore } from '@/store/user'
import { markdownNodes, chatHistory } from '@/utils/aiText'

const userStore = useUserStore()
const inputText = ref(''), messages = ref([]), waiting = ref(false), scrollToId = ref('')
const kpId = ref(''), kpName = ref(''), ready = ref(false), sessionError = ref('')
let storageKey = ''

function persist() {
  try { uni.setStorageSync(storageKey, messages.value.filter(m => !m.failed).slice(-20)) }
  catch (error) { showRequestError(error, '对话本地保存失败') }
}
function clearChat() { messages.value = []; persist() }
function goDetail(id) { uni.navigateTo({ url: `/pages/learning/detail?id=${encodeURIComponent(id)}` }) }
async function initialize() {
  sessionError.value = ''; ready.value = false
  try {
    await userStore.initializeSession()
    if (!userStore.isLoggedIn) { uni.reLaunch({ url: '/pages/auth/login' }); return }
    storageKey = `ai_chat_v2:${userStore.userInfo.userId}:${kpId.value || 'general'}`
    const saved = uni.getStorageSync(storageKey)
    messages.value = Array.isArray(saved) ? saved.filter(m => ['user', 'assistant'].includes(m.role) && typeof m.content === 'string').slice(-20) : []
    if (kpId.value) kpName.value = (await get(`/api/student/knowledge-points/${encodeURIComponent(kpId.value)}`)).name
    ready.value = true
  } catch (error) { sessionError.value = showRequestError(error, '加载答疑失败').message }
}
async function sendMessage() {
  const text = inputText.value.trim()
  if (!ready.value || waiting.value || !text) return
  const history = chatHistory(messages.value)
  const pending = { role: 'user', content: text }
  messages.value.push(pending); inputText.value = ''; waiting.value = true
  await nextTick(); scrollToId.value = 'typing'
  try {
    const data = await post(kpId.value ? '/api/student/chat/knowledge-point' : '/api/student/chat', {
      message: text, history, ...(kpId.value ? { knowledge_point_id: kpId.value } : {})
    }, { timeout: 35000 })
    if (data.knowledge_point_name) kpName.value = data.knowledge_point_name
    messages.value.push({ role: 'assistant', content: data.reply, ...data })
    messages.value = messages.value.slice(-20)
    persist()
  } catch (error) {
    pending.failed = true; inputText.value = text
    showRequestError(error, '发送失败，请重试')
  } finally {
    waiting.value = false; await nextTick(); scrollToId.value = 'msg-' + (messages.value.length - 1)
  }
}
onLoad(options => { kpId.value = options.kpId || options.knowledge_point_id || ''; initialize() })
</script>

<style scoped>
.page{display:flex;flex-direction:column;height:calc(100vh - 44px);background:#f5f7fa}.header{padding:24rpx;background:#fff}.title{font-size:34rpx;font-weight:bold;display:block}.hint{display:block;color:#65748b;font-size:24rpx;margin:12rpx 0}.chat-list{flex:1;min-height:0}.welcome{padding:30rpx;color:#65748b}.msg-item{display:flex;padding:16rpx 24rpx}.user{justify-content:flex-end}.bubble{max-width:85%;background:white;padding:24rpx;border-radius:18rpx;font-size:28rpx}.user .bubble{background:#4f8cff;color:#fff}.content{white-space:pre-wrap;line-height:1.6}.degraded{display:block;font-size:22rpx;color:#8a5800;margin-top:16rpx}.error{display:block;color:#b33737;padding:12rpx;font-size:24rpx}.kp-card{display:flex;justify-content:space-between;gap:16rpx;padding:20rpx;margin-top:12rpx;background:#edf4ff;color:#2861b3;border-radius:12rpx;font-size:24rpx}.chat-input{display:flex;gap:12rpx;padding:20rpx;background:#fff;padding-bottom:calc(20rpx + env(safe-area-inset-bottom))}.input-field{flex:1;background:#f0f2f5;padding:18rpx;border-radius:16rpx;font-size:28rpx;max-height:180rpx}.btn-send{font-size:26rpx;background:#4f8cff;color:#fff}
</style>
