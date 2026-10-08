<!-- 学生数据看板 -->
<template>
  <div class="page-shell students-page">
    <div class="page-heading">
      <div>
        <h2>学生数据看板</h2>
        <p>查询学生作答、掌握度、诊断会话和当前推荐路径。</p>
      </div>
      <el-button :loading="listLoading" @click="loadList">
        <el-icon><Refresh /></el-icon>
        刷新列表
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

    <el-card shadow="never" class="filter-card">
      <div class="filter-toolbar">
        <el-input
          v-model="filters.keyword"
          clearable
          class="keyword-input"
          placeholder="搜索学生 ID、账号或姓名"
          @keyup.enter="applyFilters"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-button type="primary" @click="applyFilters">搜索</el-button>
        <el-button @click="resetFilters">重置</el-button>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table v-loading="listLoading" :data="students" stripe row-key="student_id" @row-click="openDetail">
        <el-table-column label="学生" min-width="180">
          <template #default="{ row }">
            <div class="student-cell">
              <el-avatar :size="34">{{ row.name?.slice(0, 1) }}</el-avatar>
              <div>
                <strong>{{ row.name }}</strong>
                <small>{{ row.username }} · {{ row.student_id }}</small>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="total_questions_done" label="已答题" width="100" />
        <el-table-column label="掌握知识点" width="140">
          <template #default="{ row }">{{ row.mastered_kp_count }} / {{ row.total_kp_count }}</template>
        </el-table-column>
        <el-table-column label="平均掌握度" width="150">
          <template #default="{ row }">
            <span v-if="row.average_mastery !== null && row.average_mastery !== undefined">
              {{ formatPercent(row.average_mastery) }}
            </span>
            <span v-else class="muted">暂无数据</span>
          </template>
        </el-table-column>
        <el-table-column prop="last_active" label="最近活跃" width="180">
          <template #default="{ row }">{{ formatDateTime(row.last_active) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click.stop="openDetail(row)">查看详情</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty :description="listLoading ? '正在加载' : (filters.keyword ? '没有匹配的学生' : '暂无学生数据')" :image-size="100" />
        </template>
      </el-table>
      <div class="pagination-row">
        <span class="muted">共 {{ total }} 名学生</span>
        <el-pagination
          v-model:current-page="pagination.page"
          v-model:page-size="pagination.page_size"
          :page-sizes="[10, 20, 50]"
          :total="total"
          layout="sizes, prev, pager, next"
          @size-change="handlePageSizeChange"
          @current-change="loadList"
        />
      </div>
    </el-card>

    <el-drawer v-model="detailVisible" title="学生详情" size="min(960px, 92vw)" destroy-on-close>
      <el-skeleton v-if="detailLoading" :rows="10" animated />
      <el-alert v-else-if="detailError" :title="detailError" type="error" show-icon />
      <template v-else-if="detail">
        <div class="detail-header">
          <el-avatar :size="56">{{ detail.name?.slice(0, 1) }}</el-avatar>
          <div>
            <h3>{{ detail.name }}</h3>
            <p>{{ detail.username }} · {{ detail.student_id }}</p>
            <small>注册于 {{ formatDateTime(detail.created_at) }}<span v-if="detail.last_login_at">，最后登录 {{ formatDateTime(detail.last_login_at) }}</span></small>
          </div>
        </div>

        <div class="detail-stats">
          <div><span>掌握记录</span><strong>{{ detail.learning_history?.length || 0 }}</strong></div>
          <div><span>最近诊断</span><strong>{{ detail.diagnosis_history?.length || 0 }}</strong></div>
          <div><span>答题记录</span><strong>{{ detail.answer_history?.length || 0 }}<small>（最近 {{ detail.meta?.answer_history_limit || 50 }} 条）</small></strong></div>
        </div>

        <el-tabs v-model="activeTab" class="detail-tabs">
          <el-tab-pane label="掌握度" name="mastery">
            <div class="section-toolbar">
              <span class="muted">默认按掌握概率从低到高展示，避免大量知识点挤成不可读图表。</span>
              <el-radio-group v-model="masteryFilter" size="small">
                <el-radio-button label="weak">薄弱项</el-radio-button>
                <el-radio-button label="all">全部</el-radio-button>
              </el-radio-group>
            </div>
            <el-table :data="visibleLearningHistory" stripe max-height="390">
              <el-table-column prop="knowledge_point_name" label="知识点" min-width="210" show-overflow-tooltip />
              <el-table-column label="掌握概率" width="180">
                <template #default="{ row }">
                  <span :class="masteryClass(row.mastery_probability)">{{ formatPercent(row.mastery_probability) }}</span>
                  <el-progress :percentage="Math.round(Number(row.mastery_probability || 0) * 100)" :show-text="false" :stroke-width="6" class="inline-progress" />
                </template>
              </el-table-column>
              <el-table-column label="作答" width="100">
                <template #default="{ row }">{{ row.questions_done }} 次</template>
              </el-table-column>
              <el-table-column label="正确率" width="100">
                <template #default="{ row }">{{ formatPercent(row.correct_rate) }}</template>
              </el-table-column>
              <el-table-column prop="updated_at" label="更新时间" width="175">
                <template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template>
              </el-table-column>
              <template #empty><el-empty description="暂无掌握度记录" :image-size="80" /></template>
            </el-table>
          </el-tab-pane>

          <el-tab-pane label="诊断会话" name="diagnosis">
            <el-table :data="detail.diagnosis_history || []" stripe>
              <el-table-column prop="diagnosed_at" label="诊断时间" width="180">
                <template #default="{ row }">{{ formatDateTime(row.diagnosed_at) }}</template>
              </el-table-column>
              <el-table-column prop="question_count" label="题数" width="80" />
              <el-table-column label="平均掌握度" width="130">
                <template #default="{ row }">{{ formatPercent(row.average_mastery) }}</template>
              </el-table-column>
              <el-table-column label="算法 / 收敛" min-width="170">
                <template #default="{ row }">{{ row.algorithm_version || '—' }} · {{ row.converged === null ? '—' : (row.converged ? '已收敛' : '未收敛') }}</template>
              </el-table-column>
              <el-table-column label="答题范围" min-width="260">
                <template #default="{ row }">{{ formatDateTime(row.answer_time_from) }} — {{ formatDateTime(row.answer_time_to) }}</template>
              </el-table-column>
              <template #empty><el-empty description="暂无诊断会话" :image-size="80" /></template>
            </el-table>
            <p class="table-note">已展示最近 {{ detail.meta?.diagnosis_history_limit || 10 }} 次诊断会话。</p>
          </el-tab-pane>

          <el-tab-pane label="答题时间线" name="answers">
            <el-timeline v-if="detail.answer_history?.length">
              <el-timeline-item v-for="item in detail.answer_history" :key="item.record_id" :timestamp="formatDateTime(item.created_at)" :type="item.is_correct ? 'success' : 'danger'">
                <div class="answer-item">
                  <strong>{{ item.is_correct ? '答对' : '答错' }} · {{ item.question_id }}</strong>
                  <span>{{ item.question_content || '题目内容不可用' }}</span>
                  <small>提交答案：{{ item.student_answer }}<span v-if="item.time_spent !== null"> · 用时 {{ item.time_spent }} 秒</span></small>
                </div>
              </el-timeline-item>
            </el-timeline>
            <el-empty v-else description="暂无答题记录" :image-size="80" />
            <p v-if="detail.answer_history?.length" class="table-note">已展示最近 {{ detail.meta?.answer_history_limit || 50 }} 条答题记录。</p>
          </el-tab-pane>

          <el-tab-pane label="推荐路径" name="path">
            <el-alert v-if="!detail.recommended_path?.length" title="当前没有新的推荐知识点" type="success" show-icon :closable="false" />
            <el-steps v-else direction="vertical" :active="0" class="path-steps">
              <el-step v-for="step in detail.recommended_path" :key="step.order" :title="`${step.order}. ${step.knowledge_point?.name || '知识点'}`" :description="`${step.reason || '暂无推荐理由'} · 预计 ${step.estimated_time || 0} 分钟`" />
            </el-steps>
          </el-tab-pane>
        </el-tabs>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import request, { getRequestErrorInfo } from '@/utils/request'

const students = ref([])
const total = ref(0)
const listLoading = ref(false)
const pageError = ref('')
const filters = reactive({ keyword: '' })
const pagination = reactive({ page: 1, page_size: 10 })
const detailVisible = ref(false)
const detailLoading = ref(false)
const detailError = ref('')
const detail = ref(null)
const activeTab = ref('mastery')
const masteryFilter = ref('weak')

const visibleLearningHistory = computed(() => {
  const items = detail.value?.learning_history || []
  if (masteryFilter.value === 'all') return items
  const weak = items.filter((item) => item.mastery_probability === null || Number(item.mastery_probability) < 0.8)
  return weak.length ? weak : items.slice(0, 10)
})

function errorMessage(error) {
  return getRequestErrorInfo(error).message || '请稍后重试'
}

function formatDateTime(value) {
  if (!value) return '—'
  return String(value).replace('T', ' ')
}

function formatPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—'
  return `${Math.round(Number(value) * 100)}%`
}

function masteryClass(value) {
  if (value === null || value === undefined) return 'muted'
  if (Number(value) >= 0.8) return 'mastery-good'
  if (Number(value) >= 0.4) return 'mastery-mid'
  return 'mastery-weak'
}

async function loadList() {
  listLoading.value = true
  pageError.value = ''
  try {
    const data = await request.get('/api/admin/students', {
      page: pagination.page,
      page_size: pagination.page_size,
      keyword: filters.keyword.trim() || undefined,
    })
    students.value = data.list || []
    total.value = data.total || 0
  } catch (error) {
    pageError.value = `学生列表加载失败：${errorMessage(error)}`
  } finally {
    listLoading.value = false
  }
}

function applyFilters() {
  pagination.page = 1
  loadList()
}

function resetFilters() {
  filters.keyword = ''
  applyFilters()
}

function handlePageSizeChange(size) {
  pagination.page_size = size
  pagination.page = 1
  loadList()
}

async function openDetail(row) {
  detailVisible.value = true
  detailLoading.value = true
  detailError.value = ''
  detail.value = null
  activeTab.value = 'mastery'
  masteryFilter.value = 'weak'
  try {
    detail.value = await request.get(`/api/admin/students/${encodeURIComponent(row.student_id)}`)
  } catch (error) {
    detailError.value = `学生详情加载失败：${errorMessage(error)}`
  } finally {
    detailLoading.value = false
  }
}

watch(detailVisible, (visible) => {
  if (!visible) {
    detail.value = null
    detailError.value = ''
  }
})

onMounted(loadList)
</script>

<style scoped>
.students-page { max-width: 1440px; margin: 0 auto; }
.student-cell { display: flex; align-items: center; gap: 10px; }
.student-cell > div { display: flex; flex-direction: column; gap: 3px; }
.student-cell small { color: #909399; }
.muted { color: #909399; }
.detail-header { display: flex; align-items: center; gap: 14px; padding: 2px 0 18px; border-bottom: 1px solid #ebeef5; }
.detail-header h3 { font-size: 20px; margin-bottom: 4px; }
.detail-header p, .detail-header small { color: #909399; }
.detail-header p { margin-bottom: 5px; }
.detail-stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 16px 0; }
.detail-stats > div { background: #f7f8fa; border-radius: 8px; padding: 12px; display: flex; flex-direction: column; gap: 6px; }
.detail-stats span { color: #909399; font-size: 12px; }
.detail-stats strong { font-size: 22px; }
.detail-stats small { font-size: 11px; color: #909399; font-weight: normal; }
.section-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 12px; }
.inline-progress { display: inline-flex; width: 84px; margin-left: 8px; vertical-align: middle; }
.mastery-good { color: #059669; font-weight: 600; }
.mastery-mid { color: #2563eb; font-weight: 600; }
.mastery-weak { color: #ea580c; font-weight: 600; }
.table-note { color: #909399; font-size: 12px; margin-top: 10px; }
.answer-item { display: flex; flex-direction: column; gap: 4px; padding-bottom: 3px; }
.answer-item span { color: #606266; line-height: 1.5; }
.answer-item small { color: #909399; }
.path-steps { padding: 6px 10px; }
@media (max-width: 700px) { .detail-stats { grid-template-columns: 1fr; } .section-toolbar { align-items: flex-start; flex-direction: column; } }
</style>
