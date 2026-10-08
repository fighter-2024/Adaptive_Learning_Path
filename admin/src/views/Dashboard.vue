<!-- 管理端仪表盘 -->
<template>
  <div class="page-shell dashboard-page">
    <div class="page-heading">
      <div>
        <h2>管理端仪表盘</h2>
        <p>查看当前学生规模、内容资源、本周活跃度和最近诊断。</p>
      </div>
      <el-button :loading="loading" @click="loadSummary">
        <el-icon><Refresh /></el-icon>
        刷新数据
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

    <el-skeleton v-if="loading && !summary" :rows="5" animated />
    <template v-else>
      <div class="stat-grid">
        <el-card v-for="item in statCards" :key="item.key" shadow="never" class="stat-card">
          <div class="stat-icon" :class="`tone-${item.tone}`">
            <el-icon><component :is="item.icon" /></el-icon>
          </div>
          <div class="stat-content">
            <span class="stat-label">{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
            <small>{{ item.hint }}</small>
          </div>
        </el-card>
      </div>

      <el-card shadow="never" class="table-card recent-card">
        <template #header>
          <div class="card-heading">
            <div>
              <strong>最近诊断</strong>
              <span class="muted">按诊断完成时间倒序展示</span>
            </div>
            <el-tag type="info" effect="plain">真实数据库统计</el-tag>
          </div>
        </template>
        <el-table :data="summary?.recent_diagnoses || []" stripe>
          <el-table-column prop="student_name" label="学生" min-width="140">
            <template #default="{ row }">
              <div class="student-cell">
                <el-avatar :size="30">{{ row.student_name?.slice(0, 1) }}</el-avatar>
                <div>
                  <strong>{{ row.student_name }}</strong>
                  <small>{{ row.student_id }}</small>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="diagnosed_at" label="诊断时间" width="190">
            <template #default="{ row }">{{ formatDateTime(row.diagnosed_at) }}</template>
          </el-table-column>
          <el-table-column label="平均掌握度" min-width="180">
            <template #default="{ row }">
              <span v-if="row.average_mastery !== null && row.average_mastery !== undefined" class="mastery-value">
                {{ formatPercent(row.average_mastery) }}
              </span>
              <span v-else class="muted">暂无有效向量</span>
              <el-progress
                v-if="row.average_mastery !== null && row.average_mastery !== undefined"
                :percentage="Math.round(row.average_mastery * 100)"
                :show-text="false"
                :stroke-width="7"
                class="mastery-progress"
              />
            </template>
          </el-table-column>
          <template #empty>
            <el-empty description="暂无诊断记录" :image-size="90" />
          </template>
        </el-table>
      </el-card>

      <div class="dashboard-note">
        本周活跃学生按本周一以来在答题记录或诊断会话中出现的去重学生统计。
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import request, { getRequestErrorInfo } from '@/utils/request'

const loading = ref(false)
const pageError = ref('')
const summary = ref(null)

const statCards = computed(() => {
  const data = summary.value || {}
  return [
    { key: 'students', label: '学生总数', value: data.student_count ?? 0, hint: '有效学生账号', icon: 'User', tone: 'blue' },
    { key: 'questions', label: '题目总数', value: data.question_count ?? 0, hint: '已启用题目', icon: 'EditPen', tone: 'purple' },
    { key: 'knowledge-points', label: '知识点总数', value: data.knowledge_point_count ?? 0, hint: 'Neo4j 图谱节点', icon: 'Share', tone: 'green' },
    { key: 'active', label: '本周活跃学生', value: data.weekly_active_students ?? 0, hint: '答题或诊断过的学生', icon: 'TrendCharts', tone: 'orange' },
  ]
})

function errorMessage(error) {
  return getRequestErrorInfo(error).message || '请稍后重试'
}

function formatDateTime(value) {
  if (!value) return '—'
  return String(value).replace('T', ' ')
}

function formatPercent(value) {
  return `${Math.round(Number(value) * 100)}%`
}

async function loadSummary() {
  loading.value = true
  pageError.value = ''
  try {
    summary.value = await request.get('/api/admin/dashboard/summary')
  } catch (error) {
    pageError.value = `仪表盘数据加载失败：${errorMessage(error)}`
  } finally {
    loading.value = false
  }
}

onMounted(loadSummary)
</script>

<style scoped>
.dashboard-page { max-width: 1440px; margin: 0 auto; }
.stat-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; margin-bottom: 18px; }
.stat-card { display: flex; align-items: center; min-height: 128px; }
.stat-card :deep(.el-card__body) { display: flex; align-items: center; width: 100%; }
.stat-icon { width: 50px; height: 50px; border-radius: 14px; display: grid; place-items: center; margin-right: 14px; font-size: 24px; }
.tone-blue { color: #2563eb; background: #eaf2ff; }
.tone-purple { color: #7c3aed; background: #f1eaff; }
.tone-green { color: #059669; background: #e6f8f1; }
.tone-orange { color: #ea580c; background: #fff1e8; }
.stat-content { display: flex; flex-direction: column; gap: 4px; }
.stat-label { color: #606266; }
.stat-content strong { font-size: 28px; color: #1f2937; line-height: 1.1; }
.stat-content small { color: #909399; }
.card-heading { display: flex; align-items: center; justify-content: space-between; }
.card-heading > div { display: flex; align-items: center; gap: 12px; }
.student-cell { display: flex; align-items: center; gap: 10px; }
.student-cell > div { display: flex; flex-direction: column; gap: 2px; }
.student-cell small { color: #909399; }
.mastery-value { display: inline-block; min-width: 44px; font-weight: 600; }
.mastery-progress { display: inline-flex; width: 110px; margin-left: 12px; vertical-align: middle; }
.dashboard-note { color: #909399; font-size: 12px; padding: 10px 2px; }
.muted { color: #909399; font-size: 12px; }
@media (max-width: 1000px) { .stat-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 560px) { .stat-grid { grid-template-columns: 1fr; } .card-heading { align-items: flex-start; gap: 8px; flex-direction: column; } }
</style>
