<template>
  <view class="page">
    <view class="page-header">
      <view>
        <text class="eyebrow">ADAPTIVE LEARNING</text>
        <text class="page-title">学习空间</text>
        <text class="page-subtitle">看懂自己的下一步，也看懂知识之间的关系</text>
      </view>
      <text class="refresh" @click="reloadActiveView">↻</text>
    </view>

    <view class="view-tabs">
      <view v-for="item in viewOptions" :key="item.key" class="view-tab"
            :class="{ active: activeView === item.key }" @click="switchView(item.key)">
        <text class="tab-icon">{{ item.icon }}</text>
        <text>{{ item.label }}</text>
      </view>
    </view>

    <view v-if="errorMessage" class="error-card">
      <text class="error-title">{{ errorMessage }}</text>
      <text class="error-hint">数据没有加载成功，当前页面不会展示伪造的学习结果。</text>
      <button class="retry-button" @click="reloadActiveView">重试</button>
    </view>

    <view v-if="loading" class="loading-card">
      <view class="loading-pulse loading-title"></view>
      <view class="loading-pulse loading-line"></view>
      <view class="loading-pulse loading-line short"></view>
      <text class="loading-text">正在读取你的学习数据…</text>
    </view>

    <template v-else-if="!errorMessage">
      <view v-if="activeView === 'personalized'" class="personalized-view">
        <view class="path-banner">
          <view>
            <text class="banner-label">MY NEXT STEP</text>
            <text class="banner-title">{{ target ? '通往「' + target.name + '」' : '为你安排的学习顺序' }}</text>
            <text class="banner-subtitle">路径顺序来自图谱前置关系与当前掌握度</text>
          </view>
          <view class="banner-count">
            <text class="count-number">{{ steps.length }}</text>
            <text class="count-label">个步骤</text>
          </view>
        </view>

        <view v-if="steps.length" class="path-list">
          <view v-for="(step, index) in steps" :key="step.knowledge_point.id" class="path-step"
                :class="stepClass(step, index)" @click="openPathStep(step)">
            <view class="step-rail">
              <view class="step-number" :class="statusClass(step)">
                <text>{{ step.order || index + 1 }}</text>
              </view>
              <view v-if="index < steps.length - 1" class="step-connector"></view>
            </view>
            <view class="step-card">
              <view class="step-topline">
                <text class="step-kicker">{{ stepBadge(step, index) }}</text>
                <text class="status-pill" :class="statusClass(step)">{{ statusLabel(step) }}</text>
              </view>
              <text class="step-name">{{ step.knowledge_point.name }}</text>
              <view class="mastery-row">
                <text class="mastery-label">掌握率 {{ masteryText(step) }}</text>
                <view class="mastery-track">
                  <view class="mastery-fill" :class="statusClass(step)"
                        :style="{ width: masteryPercent(step) + '%' }"></view>
                </view>
              </view>
              <text class="step-reason">{{ step.reason || '根据当前学习状态推荐' }}</text>
              <view class="step-meta">
                <text>难度 {{ difficultyText(step.difficulty) }}</text>
                <text>{{ step.estimated_time || 0 }} 分钟</text>
                <text class="step-action">查看详情 ›</text>
              </view>
            </view>
          </view>
        </view>

        <view v-else class="empty-card">
          <text class="empty-icon">◌</text>
          <text class="empty-title">暂时没有可推荐的步骤</text>
          <text class="empty-hint">完成一轮答题或刷新诊断后，系统会重新计算下一步。</text>
        </view>

        <view v-if="explanation" class="explain-card">
          <view class="explain-heading"><text class="explain-icon">✦</text><text>为什么这样安排？</text></view>
          <text class="explain-text">{{ explanation }}</text>
        </view>
      </view>

      <view v-else-if="activeView === 'tree'" class="graph-view">
        <view class="graph-toolbar">
          <view class="search-box">
            <text class="search-icon">⌕</text>
            <input v-model="searchKeyword" class="search-input" placeholder="搜索知识点" confirm-type="search" />
          </view>
          <view class="tool-buttons">
            <text class="tool-button" @click="zoomCanvas(-0.1)">−</text>
            <text class="tool-button" @click="zoomCanvas(0.1)">＋</text>
            <text class="tool-button" @click="resetCanvas">复位</text>
            <text class="tool-button" @click="fitCanvas">适应</text>
          </view>
        </view>
        <view class="legend-card">
          <text class="legend-title">图例</text>
          <view class="legend-items">
            <view class="legend-item"><view class="legend-color mastered"></view><text>已掌握</text></view>
            <view class="legend-item"><view class="legend-color learning"></view><text>学习中</text></view>
            <view class="legend-item"><view class="legend-color weak"></view><text>待巩固</text></view>
            <view class="legend-item"><view class="legend-color not_started"></view><text>未开始</text></view>
            <view class="legend-item"><view class="legend-shape course"></view><text>课程</text></view>
            <view class="legend-item"><view class="legend-shape chapter"></view><text>章节</text></view>
            <view class="legend-item"><view class="legend-shape knowledge_point"></view><text>知识点</text></view>
          </view>
        </view>
        <view v-if="graphData.meta && graphData.meta.truncated" class="local-tip">
          当前为局部图谱（{{ graphData.meta.returned_nodes }}/{{ graphData.meta.total_nodes }} 个节点），展开章节查看已加载内容。
        </view>
        <scroll-view scroll-x scroll-y class="graph-viewport">
          <view class="graph-stage tree-stage" :style="stageStyle" @touchstart.stop="beginPan"
                @touchmove.stop.prevent="movePan" @touchend.stop="endPan">
            <view v-if="courseNode" class="course-row">
              <view class="node-shape course-shape"><text>课</text></view>
              <text class="course-title">{{ courseNode.label }}</text>
              <text class="course-hint">课程根节点</text>
            </view>
            <view v-for="chapter in filteredChapters" :key="chapter.id" class="chapter-group">
              <view class="chapter-row" @click="toggleChapter(chapter.id)">
                <view class="node-shape chapter-shape"><text>章</text></view>
                <text class="chapter-title">{{ chapter.label }}</text>
                <text class="chapter-count">{{ chapter.children.length }} 个知识点</text>
                <text class="chapter-toggle">{{ isChapterOpen(chapter.id) ? '⌄' : '›' }}</text>
              </view>
              <view v-if="isChapterOpen(chapter.id)" class="knowledge-list">
                <view v-for="node in chapter.children" :key="node.id" class="tree-node-row"
                      @click="selectNode(node)">
                  <view class="tree-branch"></view>
                  <view class="node-card" :class="nodeClass(node)">
                    <view class="node-shape knowledge-shape"><text>知</text></view>
                    <view class="node-copy">
                      <text class="node-label">{{ node.label }}</text>
                      <text class="node-subtitle">{{ node.locked ? '前置条件未满足' : statusLabel(node) }}</text>
                    </view>
                    <text v-if="node.recommend_order" class="recommend-order">{{ node.recommend_order }}</text>
                    <text class="node-chevron">›</text>
                  </view>
                </view>
              </view>
            </view>
            <view v-if="!filteredChapters.length" class="graph-empty"><text>没有匹配的知识点</text></view>
          </view>
        </scroll-view>
        <view v-if="knowledgeNodes.length > 40" class="mini-map">
          <text class="mini-map-title">缩略导航</text>
          <view class="mini-map-bars"><view v-for="n in miniMapBars" :key="n" class="mini-bar"></view></view>
          <text class="mini-map-hint">共 {{ knowledgeNodes.length }} 个节点，已按章节分层展示</text>
        </view>
      </view>

      <view v-else class="graph-view network-view">
        <view class="network-heading">
          <text class="section-title">局部关系探索</text>
          <text class="section-subtitle">以当前知识点为中心，查看 1～2 层前置与后继</text>
        </view>
        <view v-if="networkCandidates.length" class="focus-picker">
          <text class="picker-label">切换焦点</text>
          <scroll-view scroll-x class="focus-scroll">
            <view v-for="node in networkCandidates" :key="node.id" class="focus-chip"
                  :class="{ active: node.id === currentFocusId }" @click="switchNetwork(node.id)">
              <text>{{ node.label }}</text>
            </view>
          </scroll-view>
        </view>
        <view class="graph-toolbar">
          <view class="search-box">
            <text class="search-icon">⌕</text>
            <input v-model="searchKeyword" class="search-input" placeholder="在已加载节点中搜索" confirm-type="search" />
          </view>
          <view class="tool-buttons">
            <text class="tool-button" @click="zoomCanvas(-0.1)">−</text>
            <text class="tool-button" @click="zoomCanvas(0.1)">＋</text>
            <text class="tool-button" @click="resetCanvas">复位</text>
            <text class="tool-button" @click="fitCanvas">适应</text>
          </view>
        </view>
        <view class="legend-card compact-legend">
          <view class="legend-item"><view class="legend-color mastered"></view><text>掌握状态</text></view>
          <view class="legend-item"><view class="legend-shape knowledge_point"></view><text>知识点</text></view>
          <text class="relation-legend">→ 前置 / 后继关系</text>
        </view>
        <view v-if="graphData.meta && graphData.meta.truncated" class="local-tip">
          当前关系网已截断，点击上方节点可重新加载其局部邻居。
        </view>
        <scroll-view scroll-x scroll-y class="graph-viewport network-viewport">
          <view class="graph-stage network-stage" :style="stageStyle" @touchstart.stop="beginPan"
                @touchmove.stop.prevent="movePan" @touchend.stop="endPan">
            <view v-if="focusNode" class="network-focus node-card selected" @click="selectNode(focusNode)">
              <view class="node-shape knowledge-shape"><text>焦</text></view>
              <view class="node-copy"><text class="node-label">{{ focusNode.label }}</text><text class="node-subtitle">当前焦点</text></view>
            </view>
            <view v-if="focusNode && visibleNetworkNodes.length" class="relation-lines">
              <view v-for="node in visibleNetworkNodes" :key="node.id" class="relation-row" @click="selectNode(node)">
                <view class="relation-line"></view>
                <text class="relation-label">{{ relationLabel(node.id) }}</text>
                <view class="node-card" :class="nodeClass(node)">
                  <view class="node-shape knowledge-shape"><text>知</text></view>
                  <view class="node-copy"><text class="node-label">{{ node.label }}</text><text class="node-subtitle">{{ statusLabel(node) }}</text></view>
                  <text class="node-chevron">›</text>
                </view>
              </view>
            </view>
            <view v-else class="graph-empty"><text>暂无可探索的邻居</text></view>
          </view>
        </scroll-view>
      </view>
    </template>

    <view v-if="selectedNode" class="detail-sheet">
      <view class="sheet-handle"></view>
      <view class="sheet-header">
        <view>
          <text class="sheet-eyebrow">KNOWLEDGE POINT</text>
          <text class="sheet-title">{{ selectedNode.label }}</text>
        </view>
        <text class="sheet-close" @click="selectedNode = null">×</text>
      </view>
      <view class="sheet-metrics">
        <view class="sheet-metric"><text>掌握概率</text><text class="metric-value">{{ masteryText(selectedNode) }}</text></view>
        <view class="sheet-metric"><text>难度</text><text class="metric-value">{{ difficultyText(selectedNode.difficulty) }}</text></view>
        <view class="sheet-metric"><text>预计用时</text><text class="metric-value">{{ selectedNode.estimated_time || 0 }} 分钟</text></view>
      </view>
      <view class="sheet-progress"><view :class="['mastery-fill', statusClass(selectedNode)]" :style="{ width: masteryPercent(selectedNode) + '%' }"></view></view>
      <text v-if="selectedNode.reason" class="sheet-reason">推荐理由：{{ selectedNode.reason }}</text>
      <text v-else class="sheet-reason">当前节点来自真实课程图谱，可从详情页查看前置依赖。</text>
      <view class="sheet-actions">
        <button class="sheet-button primary" @click="goDetail(selectedNode.id)">知识点详情</button>
        <button class="sheet-button secondary" @click="startQuiz(selectedNode.id)">开始答题</button>
      </view>
    </view>
  </view>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { get, showRequestError } from '@/utils/request'

const viewOptions = [
  { key: 'personalized', label: '我的路径', icon: '↗' },
  { key: 'tree', label: '课程图谱', icon: '⌘' },
  { key: 'network', label: '关系探索', icon: '◎' }
]
const activeView = ref('personalized')
const loading = ref(false)
const errorMessage = ref('')
const target = ref(null)
const steps = ref([])
const explanation = ref('')
const graphData = ref({ nodes: [], edges: [], meta: {} })
const searchKeyword = ref('')
const selectedNode = ref(null)
const currentFocusId = ref('')
const treeOpen = reactive({})
const pan = reactive({ x: 0, y: 0 })
const zoom = ref(1)
const touchState = reactive({ active: false, x: 0, y: 0, originX: 0, originY: 0 })

const knowledgeNodes = computed(() => graphData.value.nodes.filter((node) => node.node_type === 'knowledge_point'))
const filteredKnowledgeNodes = computed(() => {
  const keyword = searchKeyword.value.trim().toLowerCase()
  if (!keyword) return knowledgeNodes.value
  return knowledgeNodes.value.filter((node) => String(node.label || '').toLowerCase().includes(keyword))
})
const filteredChapters = computed(() => {
  const chapters = graphData.value.nodes.filter((node) => node.node_type === 'chapter')
  return chapters.map((chapter) => ({
    ...chapter,
    children: filteredKnowledgeNodes.value.filter((node) => node.chapter_id === chapter.id)
  })).filter((chapter) => chapter.children.length || !searchKeyword.value.trim())
})
const courseNode = computed(() => graphData.value.nodes.find((node) => node.node_type === 'course') || null)
const networkCandidates = computed(() => knowledgeNodes.value.slice(0, 30))
const focusNode = computed(() => graphData.value.nodes.find((node) => node.id === currentFocusId.value) || null)
const visibleNetworkNodes = computed(() => filteredKnowledgeNodes.value.filter((node) => node.id !== currentFocusId.value))
const miniMapBars = computed(() => Array.from({ length: Math.min(16, Math.max(4, Math.ceil(knowledgeNodes.value.length / 5))) }, (_, index) => index))
const stageStyle = computed(() => ({ transform: 'translate(' + pan.x + 'px, ' + pan.y + 'px) scale(' + zoom.value + ')' }))

function normalizeGraph(data) {
  return { nodes: Array.isArray(data?.nodes) ? data.nodes : [], edges: Array.isArray(data?.edges) ? data.edges : [], meta: data?.meta || {} }
}
function setLoadedGraph(data) {
  graphData.value = normalizeGraph(data)
  if (!currentFocusId.value) currentFocusId.value = knowledgeNodes.value[0]?.id || ''
  resetCanvas()
}
async function loadPath() {
  const data = await get('/api/student/path', { count: 5 })
  target.value = data?.target || null
  steps.value = Array.isArray(data?.steps) ? data.steps : []
  if (steps.value[0]?.knowledge_point?.id) currentFocusId.value = steps.value[0].knowledge_point.id
  try {
    const explainData = await get('/api/student/path/explain', { count: 5 })
    explanation.value = explainData?.explanation || ''
  } catch (error) {
    explanation.value = ''
  }
}
async function loadTree() {
  const data = await get('/api/student/graph', { view: 'tree', depth: 2, max_nodes: 80, include_mastered: true })
  setLoadedGraph(data)
}
async function loadNetwork(focusId = currentFocusId.value) {
  if (!focusId) {
    const fallback = steps.value[0]?.knowledge_point?.id || knowledgeNodes.value[0]?.id
    if (!fallback) {
      await loadTree()
      focusId = knowledgeNodes.value[0]?.id
    } else focusId = fallback
  }
  if (!focusId) throw new Error('当前没有可探索的知识点')
  const data = await get('/api/student/graph/' + encodeURIComponent(focusId) + '/neighbors', { direction: 'both', depth: 2, max_nodes: 30 })
  currentFocusId.value = focusId
  setLoadedGraph(data)
}
async function switchNetwork(focusId) {
  loading.value = true
  errorMessage.value = ''
  try {
    await loadNetwork(focusId)
  } catch (error) {
    errorMessage.value = error?.message || '关系网加载失败，请重试'
    showRequestError(error, '关系网加载失败，请重试')
  } finally {
    loading.value = false
  }
}
async function loadActiveView() {
  loading.value = true
  errorMessage.value = ''
  selectedNode.value = null
  try {
    if (activeView.value === 'personalized') await loadPath()
    if (activeView.value === 'tree') await loadTree()
    if (activeView.value === 'network') await loadNetwork()
  } catch (error) {
    errorMessage.value = error?.message || '学习数据加载失败，请重试'
    showRequestError(error, '学习数据加载失败，请重试')
  } finally {
    loading.value = false
  }
}
function reloadActiveView() { loadActiveView() }
function switchView(view) {
  if (activeView.value === view && !errorMessage.value) return
  activeView.value = view
  searchKeyword.value = ''
  loadActiveView()
}
function statusFromNode(node) {
  if (node?.status) return node.status
  const probability = node?.mastery_probability
  if (probability === null || probability === undefined) return 'not_started'
  if (probability >= 0.8) return 'mastered'
  if (probability >= 0.4) return 'learning'
  return 'weak'
}
function statusClass(item) { return statusFromNode(item) }
function statusLabel(item) {
  const labels = { mastered: '已掌握', learning: '学习中', weak: '待巩固', not_started: '未开始' }
  if (item?.locked) return '已锁定'
  return labels[statusFromNode(item)] || '未开始'
}
function masteryPercent(item) {
  const probability = Number(item?.mastery_probability)
  return Number.isFinite(probability) ? Math.max(0, Math.min(100, Math.round(probability * 100))) : 0
}
function masteryText(item) {
  return item?.mastery_probability === null || item?.mastery_probability === undefined ? '暂无数据' : masteryPercent(item) + '%'
}
function difficultyText(value) {
  const difficulty = Number(value)
  return Number.isFinite(difficulty) ? Math.round(difficulty * 5) + '/5' : '—'
}
function stepClass(step, index) { return { current: index === 0, next: index === 1, locked: step.locked } }
function stepBadge(step, index) {
  if (index === 0) return 'CURRENT'
  if (index === 1) return 'NEXT UP'
  return 'STEP ' + (step.order || index + 1)
}
function nodeClass(node) {
  return [statusClass(node), node.node_type, { locked: node.locked, selected: node.id === currentFocusId.value }]
}
function isChapterOpen(id) { return treeOpen[id] !== false }
function toggleChapter(id) { treeOpen[id] = !isChapterOpen(id) }
function selectNode(node) {
  if (!node || node.node_type !== 'knowledge_point') return
  selectedNode.value = node
  currentFocusId.value = node.id
}
function openPathStep(step) {
  selectNode({
    id: step.knowledge_point.id, label: step.knowledge_point.name, node_type: 'knowledge_point',
    difficulty: step.difficulty, estimated_time: step.estimated_time, mastery_probability: step.mastery_probability,
    status: step.status, locked: step.locked, reason: step.reason
  })
}
function relationLabel(nodeId) {
  const edge = graphData.value.edges.find((item) =>
    (item.source === currentFocusId.value && item.target === nodeId) ||
    (item.target === currentFocusId.value && item.source === nodeId))
  if (!edge) return '相关'
  return edge.relation === 'prerequisite' ? (edge.target === currentFocusId.value ? '前置' : '后继') : '相关'
}
function goDetail(id) { uni.navigateTo({ url: '/pages/learning/detail?id=' + encodeURIComponent(id) }) }
function startQuiz(id) { uni.navigateTo({ url: '/pages/quiz/quiz?kpId=' + encodeURIComponent(id) }) }
function resetCanvas() { pan.x = 0; pan.y = 0; zoom.value = 1 }
function fitCanvas() { pan.x = 0; pan.y = 0; zoom.value = knowledgeNodes.value.length > 40 ? 0.82 : 0.94 }
function zoomCanvas(delta) { zoom.value = Math.max(0.65, Math.min(1.5, Number((zoom.value + delta).toFixed(2)))) }
function beginPan(event) {
  const touch = event.touches?.[0]
  if (!touch) return
  touchState.active = true
  touchState.x = touch.pageX
  touchState.y = touch.pageY
  touchState.originX = pan.x
  touchState.originY = pan.y
}
function movePan(event) {
  if (!touchState.active) return
  const touch = event.touches?.[0]
  if (!touch) return
  pan.x = touchState.originX + touch.pageX - touchState.x
  pan.y = touchState.originY + touch.pageY - touchState.y
}
function endPan() { touchState.active = false }
// 诊断页成功后返回这里时重新读取真实掌握度和路径，避免继续展示旧快照。
onShow(() => { loadActiveView() })
</script>

<style lang="scss" scoped>
.page { min-height: 100vh; padding: 28rpx 24rpx 180rpx; box-sizing: border-box; background: #f5f7fb; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 24rpx; }
.eyebrow, .banner-label, .sheet-eyebrow { display: block; font-size: 19rpx; letter-spacing: 3rpx; color: #8a96aa; font-weight: 700; }
.page-title { display: block; margin-top: 8rpx; font-size: 46rpx; line-height: 1.2; font-weight: 800; color: #1c2940; }
.page-subtitle { display: block; margin-top: 10rpx; font-size: 23rpx; color: #8290a5; }
.refresh { width: 66rpx; height: 66rpx; line-height: 62rpx; text-align: center; border-radius: 22rpx; background: #fff; color: #436ff2; font-size: 40rpx; box-shadow: 0 8rpx 24rpx rgba(43, 69, 125, .08); }
.view-tabs { display: flex; padding: 8rpx; margin-bottom: 24rpx; border-radius: 20rpx; background: #e9eef8; }
.view-tab { flex: 1; display: flex; justify-content: center; align-items: center; gap: 8rpx; padding: 18rpx 4rpx; border-radius: 15rpx; color: #7c8ba3; font-size: 23rpx; }
.view-tab.active { background: #fff; color: #315ed8; font-weight: 700; box-shadow: 0 5rpx 16rpx rgba(50, 88, 166, .1); }
.tab-icon { font-size: 28rpx; }
.loading-card, .error-card, .empty-card { padding: 48rpx 30rpx; border-radius: 22rpx; background: #fff; text-align: center; }
.loading-card { min-height: 280rpx; }
.loading-pulse { margin: 0 auto 20rpx; border-radius: 14rpx; background: #edf1f7; animation: pulse 1.3s ease-in-out infinite; }
.loading-title { width: 64%; height: 42rpx; margin-top: 20rpx; }
.loading-line { width: 86%; height: 22rpx; }
.loading-line.short { width: 60%; }
.loading-text { display: block; margin-top: 36rpx; color: #8996a9; font-size: 24rpx; }
@keyframes pulse { 0%, 100% { opacity: .55; } 50% { opacity: 1; } }
.error-card { border: 1rpx solid #ffd9d4; background: #fff9f8; }
.error-title { display: block; color: #d6574a; font-size: 28rpx; font-weight: 700; }
.error-hint { display: block; margin: 14rpx 0 24rpx; color: #a9807b; font-size: 23rpx; line-height: 1.5; }
.retry-button { width: 190rpx; height: 68rpx; line-height: 68rpx; border-radius: 14rpx; background: #ee6f60; color: #fff; font-size: 25rpx; }
.path-banner { display: flex; justify-content: space-between; align-items: center; padding: 30rpx; border-radius: 24rpx; background: linear-gradient(135deg, #274fc5, #5d83f5); color: #fff; box-shadow: 0 14rpx 30rpx rgba(52, 91, 204, .2); }
.path-banner .banner-label { color: rgba(255,255,255,.7); }
.banner-title { display: block; margin-top: 10rpx; font-size: 32rpx; font-weight: 700; }
.banner-subtitle { display: block; margin-top: 10rpx; font-size: 22rpx; color: rgba(255,255,255,.76); }
.banner-count { min-width: 112rpx; text-align: center; padding-left: 18rpx; border-left: 1rpx solid rgba(255,255,255,.25); }
.count-number { display: block; font-size: 48rpx; font-weight: 800; }
.count-label { display: block; margin-top: 2rpx; font-size: 21rpx; color: rgba(255,255,255,.72); }
.path-list { margin-top: 30rpx; }
.path-step { display: flex; align-items: stretch; min-height: 220rpx; }
.step-rail { width: 70rpx; display: flex; flex-direction: column; align-items: center; }
.step-number { z-index: 1; width: 54rpx; height: 54rpx; line-height: 54rpx; text-align: center; border-radius: 18rpx; background: #e1e6f0; color: #758198; font-size: 24rpx; font-weight: 700; }
.step-number.current, .step-number.learning { background: #436ff2; color: #fff; }
.step-number.mastered { background: #40b985; color: #fff; }
.step-number.weak { background: #ed9b4e; color: #fff; }
.step-connector { width: 2rpx; flex: 1; background: #dbe2ee; }
.step-card { flex: 1; margin: 0 0 22rpx 18rpx; padding: 24rpx; border-radius: 21rpx; background: #fff; box-shadow: 0 7rpx 20rpx rgba(37, 58, 102, .06); border: 1rpx solid transparent; }
.path-step.current .step-card { border-color: #b9caff; box-shadow: 0 9rpx 26rpx rgba(55, 95, 212, .12); }
.path-step.next .step-card { border-color: #e3c68e; }
.step-topline, .step-meta, .mastery-row { display: flex; align-items: center; }
.step-topline { justify-content: space-between; }
.step-kicker { font-size: 19rpx; letter-spacing: 2rpx; color: #6c7c9b; font-weight: 700; }
.status-pill { padding: 5rpx 12rpx; border-radius: 10rpx; font-size: 19rpx; background: #eff2f7; color: #8591a5; }
.status-pill.mastered { background: #e3f7ef; color: #258b67; }
.status-pill.learning { background: #e6edff; color: #315ed8; }
.status-pill.weak { background: #fff0df; color: #bb6e21; }
.step-name { display: block; margin-top: 12rpx; color: #202e45; font-size: 30rpx; font-weight: 700; }
.mastery-row { gap: 14rpx; margin-top: 18rpx; }
.mastery-label { width: 160rpx; color: #8190a7; font-size: 22rpx; }
.mastery-track, .sheet-progress { height: 10rpx; flex: 1; overflow: hidden; border-radius: 8rpx; background: #edf0f5; }
.mastery-fill { height: 100%; border-radius: inherit; background: #bfc8d6; transition: width .25s; }
.mastery-fill.mastered { background: #40b985; }
.mastery-fill.learning { background: #436ff2; }
.mastery-fill.weak { background: #ed9b4e; }
.step-reason { display: block; margin-top: 16rpx; color: #596a85; font-size: 24rpx; line-height: 1.5; }
.step-meta { gap: 18rpx; margin-top: 18rpx; color: #98a3b3; font-size: 21rpx; }
.step-action { margin-left: auto; color: #436ff2; }
.explain-card { margin-top: 24rpx; padding: 26rpx; border-radius: 21rpx; background: #edf3ff; }
.explain-heading { display: flex; align-items: center; gap: 10rpx; color: #315ed8; font-weight: 700; font-size: 25rpx; }
.explain-icon { font-size: 30rpx; }
.explain-text { display: block; margin-top: 12rpx; color: #526789; font-size: 24rpx; line-height: 1.65; }
.empty-icon { display: block; color: #a6b3c8; font-size: 70rpx; }
.empty-title { display: block; margin-top: 12rpx; color: #57677f; font-size: 29rpx; font-weight: 700; }
.empty-hint { display: block; margin-top: 12rpx; color: #9aa7b9; font-size: 23rpx; line-height: 1.5; }
.graph-toolbar { display: flex; align-items: center; gap: 12rpx; margin-bottom: 16rpx; }
.search-box { flex: 1; display: flex; align-items: center; min-height: 72rpx; padding: 0 18rpx; border-radius: 16rpx; background: #fff; }
.search-icon { margin-right: 10rpx; color: #8b98ae; font-size: 34rpx; }
.search-input { flex: 1; height: 72rpx; color: #31415d; font-size: 24rpx; }
.tool-buttons { display: flex; gap: 8rpx; }
.tool-button { padding: 16rpx 12rpx; border-radius: 12rpx; background: #e9eef8; color: #4866a1; font-size: 21rpx; }
.legend-card { padding: 18rpx 20rpx; margin-bottom: 16rpx; border-radius: 16rpx; background: #fff; }
.legend-title { display: block; margin-bottom: 12rpx; color: #65738a; font-size: 21rpx; font-weight: 700; }
.legend-items { display: flex; flex-wrap: wrap; gap: 12rpx 18rpx; }
.legend-item { display: flex; align-items: center; gap: 7rpx; color: #8190a5; font-size: 20rpx; }
.legend-color { width: 18rpx; height: 18rpx; border-radius: 6rpx; background: #bfc8d6; }
.legend-color.mastered { background: #40b985; }
.legend-color.learning { background: #436ff2; }
.legend-color.weak { background: #ed9b4e; }
.legend-shape { width: 20rpx; height: 20rpx; border: 3rpx solid #8190a5; background: #fff; }
.legend-shape.course { border-radius: 50%; }
.legend-shape.chapter { border-radius: 6rpx; }
.legend-shape.knowledge_point { transform: rotate(45deg); border-radius: 4rpx; }
.local-tip { margin-bottom: 16rpx; padding: 16rpx 20rpx; border-radius: 14rpx; background: #fff5df; color: #9a6b25; font-size: 22rpx; line-height: 1.45; }
.graph-viewport { height: 820rpx; border-radius: 22rpx; background: #fff; }
.graph-stage { min-width: 1300rpx; min-height: 100%; padding: 30rpx; box-sizing: border-box; transform-origin: top left; transition: transform .2s ease; }
.tree-stage { min-height: 800rpx; }
.course-row { display: flex; align-items: center; min-width: 650rpx; margin-bottom: 24rpx; padding: 22rpx 24rpx; border-radius: 18rpx; background: #273f82; color: #fff; }
.course-shape { width: 48rpx; height: 48rpx; border-radius: 50%; background: #fff; color: #315ed8; }
.course-title { margin-left: 16rpx; font-size: 29rpx; font-weight: 700; }
.course-hint { margin-left: auto; color: rgba(255,255,255,.7); font-size: 21rpx; }
.chapter-group { margin-bottom: 22rpx; }
.chapter-row { display: flex; align-items: center; min-width: 650rpx; padding: 20rpx 24rpx; border-radius: 17rpx; background: #f1f5ff; }
.node-shape { flex: 0 0 auto; display: flex; justify-content: center; align-items: center; font-size: 18rpx; font-weight: 700; }
.chapter-shape { width: 52rpx; height: 40rpx; border-radius: 12rpx; background: #6384da; color: #fff; }
.chapter-title { margin-left: 14rpx; color: #2f4268; font-size: 27rpx; font-weight: 700; }
.chapter-count { margin-left: 14rpx; color: #8998b1; font-size: 21rpx; }
.chapter-toggle { margin-left: auto; color: #4866a1; font-size: 36rpx; }
.knowledge-list { padding: 14rpx 0 4rpx 44rpx; border-left: 2rpx dashed #d9e1ef; }
.tree-node-row { display: flex; align-items: center; margin: 10rpx 0; }
.tree-branch { width: 34rpx; height: 2rpx; background: #d9e1ef; }
.node-card { display: flex; align-items: center; min-width: 570rpx; padding: 18rpx 20rpx; border: 2rpx solid #e2e7ef; border-radius: 16rpx; background: #fff; }
.node-card.mastered { border-color: #bfe8d7; }
.node-card.learning { border-color: #becdfb; }
.node-card.weak { border-color: #f6d6ac; }
.node-card.selected { box-shadow: 0 0 0 4rpx rgba(67,111,242,.15); }
.node-card.locked { border-style: dashed; opacity: .72; }
.knowledge-shape { width: 44rpx; height: 44rpx; transform: rotate(45deg); border-radius: 10rpx; background: #bfc8d6; color: #fff; }
.knowledge-shape text { transform: rotate(-45deg); }
.node-card.mastered .knowledge-shape, .mastered .knowledge-shape { background: #40b985; }
.node-card.learning .knowledge-shape, .learning .knowledge-shape { background: #436ff2; }
.node-card.weak .knowledge-shape, .weak .knowledge-shape { background: #ed9b4e; }
.node-copy { min-width: 0; flex: 1; margin-left: 18rpx; }
.node-label { display: block; overflow: hidden; color: #2d3b53; font-size: 25rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.node-subtitle { display: block; margin-top: 6rpx; color: #8d9aaf; font-size: 20rpx; }
.recommend-order { width: 38rpx; height: 38rpx; line-height: 38rpx; margin-right: 14rpx; text-align: center; border-radius: 50%; background: #e6edff; color: #315ed8; font-size: 19rpx; }
.node-chevron { color: #a2adbd; font-size: 34rpx; }
.graph-empty { padding: 100rpx 0; text-align: center; color: #91a0b5; font-size: 25rpx; }
.mini-map { margin-top: 16rpx; padding: 18rpx 20rpx; border-radius: 16rpx; background: #eef2f8; }
.mini-map-title { display: block; color: #67758b; font-size: 21rpx; font-weight: 700; }
.mini-map-bars { display: flex; align-items: flex-end; gap: 5rpx; height: 38rpx; margin-top: 10rpx; }
.mini-bar { width: 13rpx; height: 22rpx; border-radius: 4rpx; background: #b9c7df; }
.mini-bar:nth-child(3n) { height: 34rpx; background: #7f9be4; }
.mini-map-hint { display: block; margin-top: 8rpx; color: #8c99ad; font-size: 20rpx; }
.network-heading { margin-bottom: 20rpx; }
.section-title { display: block; color: #273852; font-size: 30rpx; font-weight: 700; }
.section-subtitle { display: block; margin-top: 8rpx; color: #8997aa; font-size: 22rpx; }
.focus-picker { display: flex; align-items: center; margin-bottom: 16rpx; }
.picker-label { width: 110rpx; color: #718099; font-size: 21rpx; }
.focus-scroll { flex: 1; white-space: nowrap; }
.focus-chip { display: inline-block; max-width: 260rpx; overflow: hidden; margin-right: 10rpx; padding: 12rpx 18rpx; border-radius: 22rpx; background: #fff; color: #718099; font-size: 21rpx; text-overflow: ellipsis; white-space: nowrap; }
.focus-chip.active { background: #436ff2; color: #fff; }
.compact-legend { display: flex; align-items: center; gap: 20rpx; }
.relation-legend { margin-left: auto; color: #8997aa; font-size: 20rpx; }
.network-viewport { height: 900rpx; }
.network-stage { min-width: 1000rpx; padding: 50rpx 30rpx; }
.network-focus { width: 520rpx; margin: 0 auto 34rpx; border: 3rpx solid #436ff2; background: #f1f5ff; }
.relation-lines { display: flex; flex-direction: column; align-items: center; }
.relation-row { display: flex; align-items: center; width: 800rpx; margin-bottom: 20rpx; }
.relation-line { width: 90rpx; height: 2rpx; background: #cbd5e5; }
.relation-label { width: 100rpx; text-align: center; color: #7990c8; font-size: 20rpx; }
.relation-row .node-card { flex: 1; min-width: 0; }
.detail-sheet { position: fixed; z-index: 30; left: 18rpx; right: 18rpx; bottom: 18rpx; padding: 22rpx 26rpx 26rpx; border-radius: 26rpx; background: #fff; box-shadow: 0 -4rpx 36rpx rgba(24, 42, 84, .18); }
.sheet-handle { width: 64rpx; height: 7rpx; margin: 0 auto 18rpx; border-radius: 8rpx; background: #d9e0ea; }
.sheet-header { display: flex; align-items: flex-start; justify-content: space-between; }
.sheet-eyebrow { color: #8b99ae; }
.sheet-title { display: block; max-width: 600rpx; margin-top: 8rpx; color: #253650; font-size: 31rpx; font-weight: 700; }
.sheet-close { color: #93a0b2; font-size: 42rpx; line-height: 38rpx; }
.sheet-metrics { display: flex; gap: 42rpx; margin-top: 22rpx; }
.sheet-metric { display: flex; flex-direction: column; color: #8a98aa; font-size: 21rpx; }
.metric-value { margin-top: 7rpx; color: #344662; font-size: 25rpx; font-weight: 700; }
.sheet-progress { margin-top: 20rpx; }
.sheet-reason { display: block; margin-top: 17rpx; color: #63748f; font-size: 23rpx; line-height: 1.5; }
.sheet-actions { display: flex; gap: 14rpx; margin-top: 20rpx; }
.sheet-button { flex: 1; height: 72rpx; line-height: 72rpx; border-radius: 14rpx; font-size: 25rpx; }
.sheet-button.primary { background: #436ff2; color: #fff; }
.sheet-button.secondary { border: 1rpx solid #b9c8ee; background: #f4f7ff; color: #315ed8; }
</style>
