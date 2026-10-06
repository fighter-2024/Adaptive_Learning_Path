<template>
  <view class="page">
    <view v-if="loading" class="empty">
      <text>正在加载题目...</text>
    </view>

    <view v-else-if="loadError" class="empty error-state">
      <text>{{ loadError }}</text>
      <button class="btn-retry" @click="loadQuestions">重新加载</button>
    </view>

    <view v-else-if="noQuestions" class="empty">
      <text>当前知识点暂无可作答题目</text>
      <text class="empty-hint">请先让老师在题库中关联题目</text>
      <button class="btn-back" @click="goBack">返回</button>
    </view>

    <!-- 题目区域：题目对象只来自正式取题接口，不包含答案或解析。 -->
    <view v-else-if="currentQuestion" class="quiz-area">
      <view class="quiz-progress">
        <text>{{ currentIndex + 1 }} / {{ totalQuestions }}</text>
        <view class="progress-bar">
          <view class="fill" :style="{ width: ((currentIndex + 1) / totalQuestions * 100) + '%' }"></view>
        </view>
      </view>

      <view class="question-card">
        <text class="question-type">{{ questionTypeLabel }}</text>
        <text class="question-content">{{ currentQuestion.content }}</text>
      </view>

      <view class="options">
        <view v-for="opt in currentQuestion.options" :key="opt.label"
              class="option-item"
              :class="{
                selected: isSelected(opt.label),
                correct: showResult && isCorrectOption(opt.label),
                wrong: showResult && isSelected(opt.label) && !isCorrectOption(opt.label)
              }"
              @click="selectAnswer(opt.label)">
          <text class="option-label">{{ optionMarker(opt.label) }}</text>
          <text class="option-content">{{ opt.content }}</text>
        </view>
      </view>

      <view v-if="showResult" class="explanation-card">
        <text class="explanation-label">{{ submissionResult.correct ? '✅ 回答正确' : '❌ 回答错误' }}</text>
        <text class="correct-answer">正确答案：{{ formatAnswer(submissionResult.correct_answer) }}</text>
        <text class="explanation-text">{{ submissionResult.explanation || '暂无解析' }}</text>
        <text v-if="masterySummary" class="mastery-change">{{ masterySummary }}</text>
      </view>

      <view class="quiz-actions">
        <button v-if="!showResult" class="btn-submit"
                :disabled="!hasSelectedAnswer || submitting" @click="submitAnswer">
          {{ submitting ? '提交中...' : '提交答案' }}
        </button>
        <button v-else-if="currentIndex < totalQuestions - 1" class="btn-next" @click="nextQuestion">
          下一题
        </button>
        <button v-else class="btn-finish" @click="finishQuiz">
          完成答题
        </button>
      </view>
    </view>

    <view v-else-if="quizFinished" class="result-area">
      <text class="result-emoji">🎉</text>
      <text class="result-title">答题完成！</text>
      <text class="result-score">正确率：{{ Math.round(correctCount / totalQuestions * 100) }}%（{{ correctCount }}/{{ totalQuestions }}）</text>
      <button class="btn-back" @click="goBack">返回</button>
    </view>
  </view>
</template>

<script setup>
import { computed, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { get, post, showRequestError } from '@/utils/request'

const knowledgePointId = ref('')
const questions = ref([])
const currentIndex = ref(0)
const currentQuestion = ref(null)
const selectedAnswer = ref('')
const selectedAnswers = ref([])
const submissionResult = ref(null)
const quizFinished = ref(false)
const correctCount = ref(0)
const loading = ref(false)
const submitting = ref(false)
const loadError = ref('')
const noQuestions = ref(false)
const questionStartedAt = ref(0)

const totalQuestions = computed(() => questions.value.length)
const showResult = computed(() => Boolean(submissionResult.value))
const questionTypeLabel = computed(() => ({
  single_choice: '单选题',
  multi_choice: '多选题',
  true_false: '判断题'
}[currentQuestion.value?.type] || '练习题'))
const hasSelectedAnswer = computed(() => currentQuestion.value?.type === 'multi_choice'
  ? selectedAnswers.value.length > 0
  : Boolean(selectedAnswer.value))
const masterySummary = computed(() => {
  const changes = submissionResult.value?.mastery_change || {}
  const entries = Object.values(changes)
  if (!entries.length) return ''
  const before = entries[0].before
  const after = entries[entries.length - 1].after
  return `掌握度：${Math.round(before * 100)}% → ${Math.round(after * 100)}%`
})

function setCurrentQuestion(index) {
  currentIndex.value = index
  currentQuestion.value = questions.value[index] || null
  selectedAnswer.value = ''
  selectedAnswers.value = []
  submissionResult.value = null
  questionStartedAt.value = Date.now()
}

async function loadQuestions() {
  loading.value = true
  loadError.value = ''
  noQuestions.value = false
  quizFinished.value = false
  currentQuestion.value = null
  if (!knowledgePointId.value) {
    loadError.value = '缺少知识点参数，请从知识点详情或学习路径进入答题'
    loading.value = false
    return
  }

  try {
    const data = await get('/api/student/questions', {
      knowledge_point_id: knowledgePointId.value,
      count: 10
    })
    questions.value = data?.list || []
    noQuestions.value = questions.value.length === 0
    if (!noQuestions.value) setCurrentQuestion(0)
  } catch (error) {
    questions.value = []
    loadError.value = error?.message || '题目加载失败，请稍后重试'
    showRequestError(error, loadError.value)
  } finally {
    loading.value = false
  }
}

function optionMarker(label) {
  return currentQuestion.value?.type === 'multi_choice' ? '□' : label
}

function isSelected(label) {
  return currentQuestion.value?.type === 'multi_choice'
    ? selectedAnswers.value.includes(label)
    : selectedAnswer.value === label
}

function selectAnswer(label) {
  if (showResult.value || submitting.value) return
  if (currentQuestion.value?.type === 'multi_choice') {
    selectedAnswers.value = selectedAnswers.value.includes(label)
      ? selectedAnswers.value.filter((item) => item !== label)
      : [...selectedAnswers.value, label]
  } else {
    selectedAnswer.value = label
  }
}

function answerPayload() {
  return currentQuestion.value.type === 'multi_choice'
    ? [...selectedAnswers.value]
    : selectedAnswer.value
}

function isCorrectOption(label) {
  const answer = submissionResult.value?.correct_answer
  if (currentQuestion.value?.type === 'multi_choice') {
    const labels = Array.isArray(answer) ? answer : String(answer || '').split(',')
    return labels.map((item) => String(item).toUpperCase()).includes(label.toUpperCase())
  }
  if (currentQuestion.value?.type === 'true_false') {
    const normalized = String(answer || '').toLowerCase()
    return (normalized === 'true' && (label === '对' || label.toLowerCase() === 'true'))
      || (normalized === 'false' && (label === '错' || label.toLowerCase() === 'false'))
  }
  return String(answer || '').toUpperCase() === String(label).toUpperCase()
}

function formatAnswer(answer) {
  return Array.isArray(answer) ? answer.join('、') : answer
}

async function submitAnswer() {
  if (!hasSelectedAnswer.value || submitting.value || showResult.value) return
  submitting.value = true
  try {
    const result = await post('/api/student/submit-answer', {
      question_id: currentQuestion.value.id,
      student_answer: answerPayload(),
      time_spent: Math.max(0, Math.round((Date.now() - questionStartedAt.value) / 1000))
    })
    submissionResult.value = result
    if (result?.correct) correctCount.value += 1
    // 当前页面无本地知识点缓存；通知详情/路径页在回到前台时重新取数。
    uni.$emit('learning-state-invalidated', { knowledgePointId: knowledgePointId.value })
  } catch (error) {
    // 服务端未确认成功前不展示判题结果，按钮在 finally 后恢复，可安全重试。
    showRequestError(error, '答案提交失败，请稍后重试')
  } finally {
    submitting.value = false
  }
}

function nextQuestion() {
  setCurrentQuestion(currentIndex.value + 1)
}

function finishQuiz() {
  quizFinished.value = true
  currentQuestion.value = null
  uni.$emit('learning-state-invalidated', { knowledgePointId: knowledgePointId.value })
}

function goBack() {
  uni.navigateBack()
}

onLoad((options = {}) => {
  knowledgePointId.value = options.knowledge_point_id || options.kpId || ''
  loadQuestions()
})
</script>

<style lang="scss" scoped>
.page { padding: 20rpx; padding-bottom: 40rpx; }
.quiz-progress { display: flex; align-items: center; gap: 16rpx; margin-bottom: 24rpx; font-size: 24rpx; color: #7f8c8d; }
.progress-bar { flex: 1; height: 8rpx; background: #f0f2f5; border-radius: 4rpx; overflow: hidden; }
.progress-bar .fill { height: 100%; background: #4f8cff; transition: width .3s; }
.question-card { background: #fff; border-radius: 16rpx; padding: 32rpx; margin-bottom: 24rpx; }
.question-type { display: block; color: #4f8cff; font-size: 24rpx; margin-bottom: 12rpx; }
.question-content { font-size: 30rpx; line-height: 1.7; }
.options { display: flex; flex-direction: column; gap: 16rpx; }
.option-item { display: flex; align-items: flex-start; gap: 16rpx; background: #fff; border: 2rpx solid #e8eaed; border-radius: 12rpx; padding: 22rpx 24rpx; transition: all .2s; }
.option-item.selected { border-color: #4f8cff; background: #e8f0ff; }
.option-item.correct { border-color: #18bc37; background: #e8f8e8; }
.option-item.wrong { border-color: #f36b6b; background: #fff0f0; }
.option-label { width: 44rpx; height: 44rpx; border-radius: 50%; background: #f0f2f5; display: flex; align-items: center; justify-content: center; font-size: 24rpx; font-weight: bold; color: #7f8c8d; flex-shrink: 0; }
.option-item.selected .option-label { background: #4f8cff; color: #fff; }
.option-item.correct .option-label { background: #18bc37; color: #fff; }
.option-item.wrong .option-label { background: #f36b6b; color: #fff; }
.option-content { font-size: 28rpx; line-height: 1.5; flex: 1; }
.explanation-card { background: #f8f9fb; border-radius: 12rpx; padding: 24rpx; margin-top: 24rpx; }
.explanation-label { font-size: 28rpx; font-weight: 500; display: block; }
.correct-answer, .explanation-text, .mastery-change { font-size: 26rpx; color: #7f8c8d; margin-top: 8rpx; line-height: 1.6; display: block; }
.quiz-actions { margin-top: 32rpx; }
.btn-submit, .btn-next, .btn-finish, .btn-retry, .btn-back { width: 100%; background: #4f8cff; color: #fff; border: none; border-radius: 12rpx; padding: 24rpx; font-size: 30rpx; }
.btn-submit[disabled] { opacity: .55; }
.result-area { text-align: center; padding: 100rpx 40rpx; }
.result-emoji { font-size: 80rpx; display: block; }
.result-title { font-size: 36rpx; font-weight: bold; margin-top: 16rpx; display: block; }
.result-score { font-size: 28rpx; color: #7f8c8d; margin-top: 12rpx; display: block; }
.btn-back { width: auto; margin-top: 40rpx; padding: 20rpx 60rpx; font-size: 28rpx; }
.empty { text-align: center; padding: 100rpx 40rpx; color: #7f8c8d; }
.empty-hint { display: block; margin-top: 12rpx; color: #bdc3c7; font-size: 24rpx; }
.error-state { color: #f36b6b; }
.btn-retry { width: auto; margin-top: 32rpx; padding: 18rpx 48rpx; font-size: 28rpx; }
</style>
