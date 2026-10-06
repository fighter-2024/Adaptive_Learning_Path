<template>
  <view class="page">
    <!-- 对话列表 -->
    <scroll-view class="chat-list" scroll-y :scroll-into-view="scrollToId" scroll-with-animation>
      <view v-for="(msg, idx) in messages" :key="idx" :id="'msg-' + idx"
            class="msg-item" :class="msg.role === 'user' ? 'msg-user' : 'msg-ai'">
        <view class="msg-bubble">
          <text class="msg-text">{{ msg.content }}</text>
        </view>
      </view>
      <!-- 加载中 -->
      <view v-if="waiting" class="msg-item msg-ai">
        <view class="msg-bubble">
          <text class="msg-text typing">AI 正在思考...</text>
        </view>
      </view>
    </scroll-view>

    <!-- 输入区 -->
    <view class="chat-input">
      <input class="input-field" v-model="inputText" placeholder="输入你的问题..."
             confirm-type="send" @confirm="sendMessage" :disabled="waiting" />
      <button class="btn-send" @click="sendMessage" :disabled="!inputText.trim() || waiting">
        发送
      </button>
    </view>
  </view>
</template>

<script setup>
import { ref, nextTick, onMounted } from 'vue'
import { post, showRequestError } from '@/utils/request'

const inputText = ref('')
const messages = ref([])
const waiting = ref(false)
const scrollToId = ref('')

// 对话历史（最近 10 轮）
const history = ref([])

function addMessage(role, content) {
  messages.value.push({ role, content })
  history.value.push({ role, content })
  // 只保留最近 10 轮
  if (history.value.length > 20) {
    history.value = history.value.slice(-20)
  }
  nextTick(() => {
    scrollToId.value = 'msg-' + (messages.value.length - 1)
  })
}

async function sendMessage() {
  const text = inputText.value.trim()
  if (!text || waiting.value) return

  addMessage('user', text)
  inputText.value = ''
  waiting.value = true

  try {
    // 判断是否从知识点页进入
    const data = await post('/api/student/chat', {
      message: text,
      history: history.value.slice(0, -1) // 不包含刚发的这条
    })
    addMessage('assistant', data.reply || '抱歉，我暂时无法回答这个问题。')
  } catch (error) {
    showRequestError(error, '发送失败，请稍后重试')
    addMessage('assistant', '网络连接失败，请稍后重试。')
  } finally {
    waiting.value = false
  }
}

onMounted(() => {
  // 欢迎消息
  addMessage('assistant', '你好！我是你的专属 AI 学习助手。有什么学习上的问题可以问我~')
})
</script>

<style lang="scss" scoped>
.page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #f5f7fa;
}

.chat-list {
  flex: 1;
  padding: 20rpx;
  overflow-y: auto;
}

.msg-item {
  margin-bottom: 24rpx;
  display: flex;
}
.msg-user { justify-content: flex-end; }
.msg-ai { justify-content: flex-start; }

.msg-bubble {
  max-width: 75%;
  padding: 18rpx 24rpx;
  border-radius: 16rpx;
}
.msg-user .msg-bubble {
  background: #4f8cff;
  color: #fff;
  border-bottom-right-radius: 4rpx;
}
.msg-ai .msg-bubble {
  background: #fff;
  border-bottom-left-radius: 4rpx;
}
.msg-text { font-size: 28rpx; line-height: 1.6; }
.msg-ai .msg-text { color: #2c3e50; }
.msg-user .msg-text { color: #fff; }
.msg-text.typing { color: #7f8c8d; font-style: italic; }

.chat-input {
  display: flex;
  align-items: center;
  gap: 12rpx;
  padding: 16rpx 20rpx;
  background: #fff;
  border-top: 1rpx solid #e8eaed;
  padding-bottom: env(safe-area-inset-bottom);
}
.input-field {
  flex: 1;
  height: 72rpx;
  background: #f0f2f5;
  border-radius: 36rpx;
  padding: 0 24rpx;
  font-size: 28rpx;
}
.btn-send {
  width: 120rpx;
  height: 72rpx;
  background: #4f8cff;
  color: #fff;
  border: none;
  border-radius: 36rpx;
  font-size: 26rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
}
</style>
