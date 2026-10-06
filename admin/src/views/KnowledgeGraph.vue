<template>
  <div class="page-shell knowledge-page">
    <div class="page-heading">
      <div>
        <h2>知识图谱管理</h2>
        <p>管理 Neo4j 中的知识点和前置关系，图谱只展示真实接口数据。</p>
      </div>
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>
        新建知识点
      </el-button>
    </div>

    <el-alert
      v-if="pageError"
      class="page-alert"
      :title="pageError"
      type="error"
      show-icon
      closable
      @close="pageError = ''"
    />

    <div class="knowledge-workspace">
      <el-card class="chapter-card" shadow="never">
        <template #header>
          <div class="card-header-row">
            <span>章节目录</span>
            <el-button text size="small" @click="selectChapter(null)">全部</el-button>
          </div>
        </template>
        <el-skeleton v-if="directoryLoading" :rows="6" animated />
        <el-empty v-else-if="!chapterTree.length" description="暂无章节数据" :image-size="70" />
        <el-tree
          v-else
          node-key="id"
          :data="chapterTree"
          :props="{ label: 'label', children: 'children' }"
          :highlight-current="true"
          :current-node-key="filters.chapter_id"
          @node-click="selectChapter"
        >
          <template #default="{ data }">
            <span class="chapter-node">
              <span>{{ data.label }}</span>
              <el-tag size="small" type="info">{{ data.count }}</el-tag>
            </span>
          </template>
        </el-tree>
      </el-card>

      <el-card class="content-card" shadow="never">
        <div class="filter-toolbar">
          <el-input
            v-model="filters.keyword"
            clearable
            placeholder="搜索知识点名称"
            class="keyword-input"
            @keyup.enter="applyFilters"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-button type="primary" @click="applyFilters">搜索</el-button>
          <el-button @click="resetFilters">重置</el-button>
          <el-divider direction="vertical" />
          <el-radio-group v-model="viewMode" size="small" @change="handleViewChange">
            <el-radio-button label="table">知识点表格</el-radio-button>
            <el-radio-button label="graph">图谱画布</el-radio-button>
          </el-radio-group>
        </div>

        <div v-if="viewMode === 'table'" class="table-wrap">
          <el-table
            v-loading="listLoading"
            :data="knowledgePoints"
            row-key="id"
            stripe
            @row-click="openEdit"
          >
            <el-table-column prop="name" label="知识点" min-width="180" show-overflow-tooltip />
            <el-table-column prop="chapter_name" label="章节" min-width="130">
              <template #default="{ row }">{{ row.chapter_name || row.chapter_id || '未分组' }}</template>
            </el-table-column>
            <el-table-column prop="difficulty" label="难度" width="90">
              <template #default="{ row }">{{ Number(row.difficulty || 0).toFixed(2) }}</template>
            </el-table-column>
            <el-table-column prop="estimated_time" label="预估时长" width="100">
              <template #default="{ row }">{{ row.estimated_time }} 分钟</template>
            </el-table-column>
            <el-table-column prop="prerequisite_count" label="前置" width="75" />
            <el-table-column prop="question_count" label="关联题目" width="95" />
            <el-table-column label="操作" width="150" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click.stop="openEdit(row)">编辑</el-button>
                <el-button link type="danger" @click.stop="confirmDelete(row)">删除</el-button>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty :description="listLoading ? '正在加载' : '暂无知识点数据'" :image-size="90" />
            </template>
          </el-table>
          <div class="pagination-row">
            <span class="result-count">共 {{ total }} 个知识点</span>
            <el-pagination
              v-model:current-page="pagination.page"
              v-model:page-size="pagination.page_size"
              :page-sizes="[10, 20, 50]"
              :total="total"
              layout="sizes, prev, pager, next"
              @size-change="loadList"
              @current-change="loadList"
            />
          </div>
        </div>

        <div v-else class="graph-wrap">
          <div class="graph-toolbar">
            <span class="graph-caption">
              {{ graphData.meta?.returned_nodes || 0 }} 个节点
              <el-tag v-if="graphData.meta?.truncated" size="small" type="warning">正在展示局部图谱</el-tag>
              <span v-if="graphFocusId" class="focus-caption">聚焦：{{ graphFocusId }}</span>
            </span>
            <div>
              <el-button size="small" @click="zoomOut">−</el-button>
              <span class="zoom-value">{{ Math.round(graphZoom * 100) }}%</span>
              <el-button size="small" @click="zoomIn">＋</el-button>
              <el-button size="small" @click="resetGraph">重置视图</el-button>
            </div>
          </div>
          <el-skeleton v-if="graphLoading" :rows="8" animated />
          <el-alert v-else-if="graphError" :title="graphError" type="error" show-icon />
          <el-empty v-else-if="!graphData.nodes.length" description="当前筛选没有图谱节点" :image-size="110" />
          <div v-else class="graph-stage-outer" @wheel.prevent="handleGraphWheel">
            <svg
              class="graph-stage"
              :style="{ transform: `scale(${graphZoom})` }"
              :viewBox="graphViewBox"
              role="img"
              aria-label="知识点关系图"
            >
              <defs>
                <marker id="graph-arrow-prerequisite" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
                  <path d="M0,0 L8,4 L0,8 z" fill="#409eff" />
                </marker>
                <marker id="graph-arrow-belongs" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
                  <path d="M0,0 L8,4 L0,8 z" fill="#a8b4c4" />
                </marker>
              </defs>
              <g v-for="edge in graphEdgeItems" :key="edge.id">
                <line
                  :x1="edge.x1"
                  :y1="edge.y1"
                  :x2="edge.x2"
                  :y2="edge.y2"
                  :class="['graph-edge', `relation-${edge.relation}`, focusEdgeClass(edge)]"
                  :marker-end="edge.relation === 'prerequisite' ? 'url(#graph-arrow-prerequisite)' : 'url(#graph-arrow-belongs)'"
                />
              </g>
              <g
                v-for="node in graphNodeItems"
                :key="node.id"
                class="graph-node"
                :class="[`node-${node.node_type}`, { 'is-focus': node.id === graphFocusId }]"
                tabindex="0"
                @click="focusGraphNode(node)"
                @keydown.enter="focusGraphNode(node)"
              >
                <circle v-if="node.node_type === 'knowledge_point'" :cx="node.x" :cy="node.y" r="28" />
                <rect v-else-if="node.node_type === 'course'" :x="node.x - 46" :y="node.y - 24" width="92" height="48" rx="12" />
                <polygon v-else :points="diamondPoints(node)" />
                <text :x="node.x" :y="node.y + 4" text-anchor="middle">{{ shorten(node.label) }}</text>
                <text :x="node.x" :y="node.y + 48" text-anchor="middle" class="node-id">{{ node.id }}</text>
              </g>
            </svg>
          </div>
          <div class="graph-legend">
            <span><i class="legend-dot" />知识点</span>
            <span><i class="legend-square" />课程</span>
            <span><i class="legend-diamond" />章节</span>
            <span><i class="legend-line prerequisite-line" />前置关系（蓝色实线，箭头指向后继）</span>
            <span><i class="legend-line belongs-line" />归属关系（灰色虚线，知识点/章节指向上级）</span>
            <span><i class="legend-focus" />当前聚焦；橙/紫分别表示前置/后继</span>
          </div>
        </div>
      </el-card>
    </div>

    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="620px" destroy-on-close>
      <el-alert
        v-if="dialogError"
        class="dialog-alert"
        :title="dialogError"
        type="error"
        show-icon
        closable
        @close="dialogError = ''"
      />
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="100px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" maxlength="100" show-word-limit />
        </el-form-item>
        <el-form-item label="所属章节" prop="chapter_id">
          <el-select v-model="form.chapter_id" filterable placeholder="请选择章节" style="width: 100%">
            <el-option v-for="chapter in chapterOptions" :key="chapter.id" :label="chapter.label" :value="chapter.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="难度" prop="difficulty">
          <el-slider v-model="form.difficulty" :min="0" :max="1" :step="0.05" show-input />
        </el-form-item>
        <el-form-item label="预估时长" prop="estimated_time">
          <el-input-number v-model="form.estimated_time" :min="1" :max="600" />
          <span class="unit-hint">分钟</span>
        </el-form-item>
        <el-form-item label="描述" prop="description">
          <el-input v-model="form.description" type="textarea" :rows="3" maxlength="2000" show-word-limit />
        </el-form-item>
        <el-form-item label="前置知识点">
          <el-select
            v-model="relationIds"
            multiple
            filterable
            collapse-tags
            collapse-tags-tooltip
            placeholder="可选；保存时全量替换"
            style="width: 100%"
          >
            <el-option
              v-for="item in prerequisiteOptions"
              :key="item.id"
              :label="`${item.name}（${item.id}）`"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveKnowledgePoint">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request, { getRequestErrorInfo } from '@/utils/request'

const viewMode = ref('table')
const pageError = ref('')
const listLoading = ref(false)
const directoryLoading = ref(false)
const graphLoading = ref(false)
const allKnowledgePoints = ref([])
const knowledgePoints = ref([])
const total = ref(0)
const filters = reactive({ keyword: '', chapter_id: null })
const pagination = reactive({ page: 1, page_size: 10 })
const graphData = reactive({ nodes: [], edges: [], meta: {} })
const graphFocusId = ref(null)
const graphZoom = ref(1)

const dialogVisible = ref(false)
const dialogMode = ref('create')
const dialogError = ref('')
const saving = ref(false)
const formRef = ref(null)
const relationIds = ref([])
const form = reactive({
  id: null,
  name: '',
  description: '',
  chapter_id: '',
  difficulty: 0.5,
  estimated_time: 30,
})

const formRules = {
  name: [{ required: true, message: '请输入知识点名称', trigger: 'blur' }],
  chapter_id: [{ required: true, message: '请选择所属章节', trigger: 'change' }],
  difficulty: [{ required: true, message: '请输入难度', trigger: 'change' }],
  estimated_time: [{ required: true, message: '请输入预估时长', trigger: 'change' }],
}

const chapterOptions = computed(() => {
  const unique = new Map()
  allKnowledgePoints.value.forEach((item) => {
    if (item.chapter_id && !unique.has(item.chapter_id)) {
      unique.set(item.chapter_id, {
        id: item.chapter_id,
        label: item.chapter_name || item.chapter_id,
      })
    }
  })
  return [...unique.values()].sort((a, b) => a.id.localeCompare(b.id))
})

const chapterTree = computed(() => chapterOptions.value.map((chapter) => ({
  ...chapter,
  count: allKnowledgePoints.value.filter((item) => item.chapter_id === chapter.id).length,
})))

const prerequisiteOptions = computed(() => allKnowledgePoints.value.filter((item) => item.id !== form.id))
const dialogTitle = computed(() => dialogMode.value === 'create' ? '新建知识点' : '编辑知识点与前置关系')

const graphNodeItems = computed(() => {
  const nodes = graphData.nodes || []
  const nodeById = Object.fromEntries(nodes.map((node) => [node.id, node]))
  const chapters = nodes.filter((node) => node.node_type === 'chapter')
  const course = nodes.find((node) => node.node_type === 'course')
  const knowledgePoints = nodes.filter((node) => node.node_type === 'knowledge_point')
  const prerequisiteEdges = (graphData.edges || []).filter((edge) => edge.relation === 'prerequisite')
  const depthMemo = new Map()
  const visiting = new Set()
  function depthOf(id) {
    if (depthMemo.has(id)) return depthMemo.get(id)
    if (visiting.has(id)) return 0
    visiting.add(id)
    const incoming = prerequisiteEdges.filter((edge) => edge.target === id && nodeById[edge.source])
    const depth = incoming.length ? Math.max(...incoming.map((edge) => depthOf(edge.source) + 1)) : 0
    visiting.delete(id)
    depthMemo.set(id, depth)
    return depth
  }
  const byDepth = new Map()
  knowledgePoints.forEach((node) => {
    const depth = depthOf(node.id)
    if (!byDepth.has(depth)) byDepth.set(depth, [])
    byDepth.get(depth).push(node)
  })
  const maxRow = Math.max(chapters.length, ...[...byDepth.values()].map((row) => row.length), 1)
  const width = Math.max(900, maxRow * 190 + 100)
  const positions = new Map()
  if (course) positions.set(course.id, { x: width / 2, y: 70 })
  chapters.forEach((node, index) => {
    positions.set(node.id, { x: width / 2 + (index - (chapters.length - 1) / 2) * 190, y: 180 })
  })
  ;[...byDepth.entries()].sort(([left], [right]) => left - right).forEach(([depth, row]) => {
    row.sort((left, right) => left.id.localeCompare(right.id)).forEach((node, index) => {
      positions.set(node.id, {
        x: width / 2 + (index - (row.length - 1) / 2) * 190,
        y: 320 + depth * 125,
      })
    })
  })
  return nodes.map((node) => ({ ...node, ...(positions.get(node.id) || { x: width / 2, y: 70 }) }))
})

const graphPositions = computed(() => Object.fromEntries(graphNodeItems.value.map((node) => [node.id, node])))
const graphEdgeItems = computed(() => (graphData.edges || []).map((edge) => ({
  ...edge,
  x1: graphPositions.value[edge.source]?.x || 0,
  y1: graphPositions.value[edge.source]?.y || 0,
  x2: graphPositions.value[edge.target]?.x || 0,
  y2: graphPositions.value[edge.target]?.y || 0,
})))
const graphViewBox = computed(() => {
  const nodes = graphNodeItems.value
  const minX = Math.min(0, ...nodes.map((node) => node.x))
  const minY = Math.min(0, ...nodes.map((node) => node.y))
  const maxX = Math.max(700, ...nodes.map((node) => node.x))
  const maxY = Math.max(260, ...nodes.map((node) => node.y))
  const padding = 110
  return `${minX - padding} ${minY - padding} ${maxX - minX + padding * 2} ${maxY - minY + padding * 2}`
})

function errorMessage(error, fallback) {
  const info = getRequestErrorInfo(error)
  return info.message || fallback
}

async function loadAllKnowledgePoints() {
  directoryLoading.value = true
  try {
    const first = await request.get('/api/admin/knowledge-points', { page: 1, page_size: 100 })
    const result = [...(first.list || [])]
    const pages = Math.ceil((first.total || result.length) / 100)
    for (let page = 2; page <= pages; page += 1) {
      const next = await request.get('/api/admin/knowledge-points', { page, page_size: 100 })
      result.push(...(next.list || []))
    }
    allKnowledgePoints.value = result
  } catch (error) {
    pageError.value = `章节目录加载失败：${errorMessage(error, '请稍后重试')}`
  } finally {
    directoryLoading.value = false
  }
}

async function loadList() {
  listLoading.value = true
  try {
    const data = await request.get('/api/admin/knowledge-points', {
      page: pagination.page,
      page_size: pagination.page_size,
      chapter_id: filters.chapter_id || undefined,
      keyword: filters.keyword.trim() || undefined,
    })
    knowledgePoints.value = data.list || []
    total.value = data.total || 0
  } catch (error) {
    pageError.value = `知识点列表加载失败：${errorMessage(error, '请稍后重试')}`
  } finally {
    listLoading.value = false
  }
}

async function loadGraph() {
  graphLoading.value = true
  graphError.value = ''
  try {
    const data = await request.get('/api/admin/graph', {
      chapter_id: filters.chapter_id || undefined,
      keyword: filters.keyword.trim() || undefined,
      focus_id: graphFocusId.value || undefined,
      depth: 2,
      max_nodes: 200,
    })
    graphData.nodes = data.nodes || []
    graphData.edges = data.edges || []
    graphData.meta = data.meta || {}
  } catch (error) {
    graphError.value = errorMessage(error, '图谱加载失败')
  } finally {
    graphLoading.value = false
  }
}

const graphError = ref('')

function applyFilters() {
  pagination.page = 1
  graphFocusId.value = null
  loadList()
  if (viewMode.value === 'graph') loadGraph()
}

function resetFilters() {
  filters.keyword = ''
  filters.chapter_id = null
  applyFilters()
}

function selectChapter(data) {
  filters.chapter_id = data?.id || null
  pagination.page = 1
  graphFocusId.value = null
  loadList()
  if (viewMode.value === 'graph') loadGraph()
}

function handleViewChange(mode) {
  if (mode === 'graph') loadGraph()
}

function resetForm() {
  Object.assign(form, {
    id: null,
    name: '',
    description: '',
    chapter_id: chapterOptions.value[0]?.id || '',
    difficulty: 0.5,
    estimated_time: 30,
  })
  relationIds.value = []
  dialogError.value = ''
}

function openCreate() {
  dialogMode.value = 'create'
  resetForm()
  dialogVisible.value = true
}

async function openEdit(row) {
  dialogMode.value = 'edit'
  dialogError.value = ''
  dialogVisible.value = true
  try {
    const detail = await request.get(`/api/admin/knowledge-points/${row.id}`)
    Object.assign(form, {
      id: detail.id,
      name: detail.name,
      description: detail.description || '',
      chapter_id: detail.chapter_id,
      difficulty: detail.difficulty ?? 0,
      estimated_time: detail.estimated_time || 1,
    })
    relationIds.value = (detail.prerequisites || []).map((item) => item.id)
  } catch (error) {
    dialogError.value = `详情加载失败：${errorMessage(error, '请稍后重试')}`
  }
}

async function saveKnowledgePoint() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  const prerequisiteSummary = relationIds.value.length
    ? relationIds.value.join('、')
    : '无（清空现有前置关系）'
  try {
    await ElMessageBox.confirm(
      `将保存知识点“${form.name.trim()}”并全量设置前置关系：${prerequisiteSummary}。\n\n节点字段和关系会在同一 Neo4j 事务中提交，确定继续吗？`,
      '确认保存知识点',
      { type: 'warning', confirmButtonText: '确认保存', cancelButtonText: '取消' },
    )
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    return
  }
  saving.value = true
  dialogError.value = ''
  try {
    const payload = {
      name: form.name.trim(),
      description: form.description,
      chapter_id: form.chapter_id,
      difficulty: form.difficulty,
      estimated_time: form.estimated_time,
      prerequisite_ids: relationIds.value,
    }
    const saved = dialogMode.value === 'create'
      ? await request.post('/api/admin/knowledge-points', payload)
      : await request.put(`/api/admin/knowledge-points/${form.id}`, payload)
    ElMessage.success(dialogMode.value === 'create' ? '知识点创建成功' : '知识点更新成功')
    dialogVisible.value = false
    await Promise.all([loadAllKnowledgePoints(), loadList()])
    if (viewMode.value === 'graph') await loadGraph()
  } catch (error) {
    dialogError.value = `保存失败：${errorMessage(error, '请检查数据后重试')}`
  } finally {
    saving.value = false
  }
}

async function confirmDelete(row) {
  let detail
  try {
    detail = await request.get(`/api/admin/knowledge-points/${row.id}`)
  } catch (error) {
    pageError.value = `无法读取删除影响：${errorMessage(error, '请稍后重试')}`
    return
  }
  const dependents = detail.dependents || []
  const impact = dependents.length
    ? `\n\n该知识点是 ${dependents.length} 个知识点的前置：${dependents.map((item) => item.name).join('、')}。服务端会拒绝此次删除。`
    : '\n\n删除后该节点及其前置关系将从图谱中移除。'
  try {
    await ElMessageBox.confirm(`确定删除“${detail.name}”吗？${impact}`, '删除确认', {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
    })
    await request.delete(`/api/admin/knowledge-points/${row.id}`)
    ElMessage.success('知识点已删除')
    await Promise.all([loadAllKnowledgePoints(), loadList()])
    if (viewMode.value === 'graph') await loadGraph()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    pageError.value = `删除失败：${errorMessage(error, '服务端拒绝了删除请求')}`
  }
}

function focusGraphNode(node) {
  if (node.node_type !== 'knowledge_point') return
  graphFocusId.value = node.id
  loadGraph()
}

function focusEdgeClass(edge) {
  if (!graphFocusId.value || edge.relation !== 'prerequisite') return ''
  if (edge.target === graphFocusId.value) return 'is-focus-prerequisite'
  if (edge.source === graphFocusId.value) return 'is-focus-dependent'
  return ''
}

function diamondPoints(node) {
  return `${node.x},${node.y - 34} ${node.x + 48},${node.y} ${node.x},${node.y + 34} ${node.x - 48},${node.y}`
}

function resetGraph() {
  graphFocusId.value = null
  graphZoom.value = 1
  loadGraph()
}

function zoomIn() {
  graphZoom.value = Math.min(1.8, Number((graphZoom.value + 0.1).toFixed(2)))
}

function zoomOut() {
  graphZoom.value = Math.max(0.5, Number((graphZoom.value - 0.1).toFixed(2)))
}

function handleGraphWheel(event) {
  if (event.deltaY < 0) zoomIn()
  else zoomOut()
}

function shorten(label) {
  return label && label.length > 9 ? `${label.slice(0, 8)}…` : label
}

onMounted(async () => {
  await Promise.all([loadAllKnowledgePoints(), loadList()])
})
</script>

<style scoped>
.page-shell { padding: 4px; }
.page-heading { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 18px; }
.page-heading h2 { margin: 0 0 6px; color: #1f2d3d; font-size: 22px; }
.page-heading p { margin: 0; color: #8492a6; }
.page-alert, .dialog-alert { margin-bottom: 14px; }
.knowledge-workspace { display: grid; grid-template-columns: 240px minmax(0, 1fr); gap: 16px; min-height: 680px; }
.chapter-card, .content-card { min-width: 0; }
.card-header-row, .filter-toolbar, .graph-toolbar, .pagination-row, .chapter-node { display: flex; align-items: center; }
.card-header-row, .graph-toolbar, .pagination-row { justify-content: space-between; }
.chapter-node { justify-content: space-between; width: 100%; padding-right: 8px; }
.filter-toolbar { gap: 10px; flex-wrap: wrap; margin-bottom: 16px; }
.keyword-input { width: 260px; }
.table-wrap { min-height: 590px; }
.pagination-row { margin-top: 16px; gap: 12px; }
.result-count, .unit-hint, .zoom-value { color: #8492a6; }
.graph-wrap { min-height: 590px; }
.graph-toolbar { margin-bottom: 10px; color: #52606d; }
.graph-caption { display: flex; align-items: center; gap: 8px; }
.focus-caption { color: #409eff; }
.graph-stage-outer { min-height: 500px; overflow: auto; border: 1px solid #e8edf3; border-radius: 6px; background: #fbfcfe; display: flex; align-items: flex-start; justify-content: center; padding: 18px; }
.graph-stage { min-width: 600px; transform-origin: top center; transition: transform .15s ease; overflow: visible; }
.graph-edge { stroke-width: 1.8; opacity: .85; transition: stroke .15s, stroke-width .15s; }
.graph-edge.relation-prerequisite { stroke: #409eff; }
.graph-edge.relation-belongs_to { stroke: #a8b4c4; stroke-dasharray: 6 4; }
.graph-edge.is-focus-prerequisite { stroke: #f56c6c; stroke-width: 3.4; }
.graph-edge.is-focus-dependent { stroke: #9b59b6; stroke-width: 3.4; }
.graph-node { cursor: pointer; outline: none; }
.graph-node circle { fill: #eaf3ff; stroke: #409eff; stroke-width: 2; transition: fill .15s, stroke .15s; }
.graph-node rect { fill: #f3e8ff; stroke: #8e44ad; stroke-width: 2; transition: fill .15s, stroke .15s; }
.graph-node polygon { fill: #eef6e8; stroke: #67c23a; stroke-width: 2; transition: fill .15s, stroke .15s; }
.graph-node:hover circle, .graph-node:focus circle,
.graph-node:hover rect, .graph-node:focus rect,
.graph-node:hover polygon, .graph-node:focus polygon { filter: brightness(.97); }
.graph-node.is-focus circle, .graph-node.is-focus rect, .graph-node.is-focus polygon { fill: #409eff; stroke: #1d5fa7; stroke-width: 3; }
.graph-node text { fill: #234; font-size: 12px; pointer-events: none; }
.graph-node.is-focus text { fill: #fff; font-weight: 600; }
.graph-node .node-id { fill: #8492a6; font-size: 10px; }
.graph-node.is-focus .node-id { fill: #409eff; }
.graph-legend { display: flex; flex-wrap: wrap; gap: 20px; padding-top: 12px; color: #8492a6; font-size: 12px; }
.legend-dot, .legend-focus, .legend-square, .legend-diamond { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 5px; background: #eaf3ff; border: 2px solid #409eff; vertical-align: -1px; }
.legend-square { border-radius: 3px; background: #f3e8ff; border-color: #8e44ad; }
.legend-diamond { border-radius: 0; transform: rotate(45deg); background: #eef6e8; border-color: #67c23a; }
.legend-focus { background: #409eff; border-color: #1d5fa7; }
.legend-line { display: inline-block; width: 18px; border-top: 2px solid #409eff; margin: 0 5px 3px 0; }
.belongs-line { border-top-color: #a8b4c4; border-top-style: dashed; }
@media (max-width: 900px) {
  .knowledge-workspace { grid-template-columns: 1fr; }
  .chapter-card { min-height: 160px; }
  .keyword-input { width: min(100%, 260px); }
}
</style>
