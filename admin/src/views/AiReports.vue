<template>
  <section>
    <h2>AI 学习周报</h2>
    <p class="muted">查看学生已生成的周报。统计来自作答记录和诊断快照，读取时复核缓存。</p>
    <el-form inline @submit.prevent="search">
      <el-form-item label="学生"><el-select v-model="studentId" clearable filterable remote :remote-method="searchStudents" :loading="studentsLoading" placeholder="搜索姓名或账号" style="width:240px"><el-option v-for="s in students" :key="s.student_id" :value="s.student_id" :label="`${s.name}（${s.username}）`" /></el-select></el-form-item>
      <el-form-item label="周一日期"><el-date-picker v-model="weekStart" type="date" value-format="YYYY-MM-DD" :disabled-date="disabledDate" clearable /></el-form-item>
      <el-form-item><el-button type="primary" :loading="loading" @click="search">查询</el-button></el-form-item>
    </el-form>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <el-table v-loading="loading" :data="rows" empty-text="暂无已生成周报，请由学生打开学习周报生成">
      <el-table-column prop="student_name" label="学生" />
      <el-table-column label="周范围" min-width="210"><template #default="{row}">{{ row.week_start }} ～ {{ row.week_end }}</template></el-table-column>
      <el-table-column prop="questions_done" label="作答次数" />
      <el-table-column label="正确率"><template #default="{row}">{{ Math.round(row.correct_rate*100) }}%</template></el-table-column>
      <el-table-column prop="study_time_minutes" label="作答分钟" />
      <el-table-column label="总结来源"><template #default="{row}"><el-tag :type="row.degraded ? 'warning' : 'success'">{{ row.degraded ? '规则降级' : 'AI' }}</el-tag></template></el-table-column>
      <el-table-column label="操作"><template #default="{row}"><el-button link type="primary" @click="selected=row">查看</el-button></template></el-table-column>
    </el-table>
    <el-pagination class="pagination" v-model:current-page="page" :page-size="10" :total="total" layout="prev,pager,next,total" @current-change="load" />
    <el-drawer :model-value="Boolean(selected)" title="学习周报" size="min(640px,100%)" @close="selected=null">
      <template v-if="selected">
        <h3>{{ selected.student_name }} · {{ selected.week_start }} ～ {{ selected.week_end }}</h3>
        <div class="stats"><el-statistic title="作答次数" :value="selected.questions_done" /><el-statistic title="正确率 %" :value="Math.round(selected.correct_rate*100)" /><el-statistic title="作答分钟" :value="selected.study_time_minutes" /></div>
        <h4>本周新掌握</h4><el-tag v-for="kp in selected.new_mastered" :key="kp.id" type="success">{{ kp.name }}</el-tag><p v-if="!selected.new_mastered.length" class="muted">暂无已记录的新掌握知识点</p>
        <h4>仍需加强</h4><el-tag v-for="kp in selected.still_weak" :key="kp.id" type="warning">{{ kp.name }}</el-tag><p v-if="!selected.still_weak.length" class="muted">暂无已记录的薄弱知识点</p>
        <h4>{{ selected.degraded ? '规则总结' : 'AI 总结' }}</h4>
        <el-alert v-if="selected.degraded" type="warning" :title="selected.degraded_reason" :closable="false" />
        <p class="summary">{{ selected.ai_summary }}</p><p class="muted">生成于 {{ selected.generated_at }} · {{ selected.cached ? '缓存命中' : '已更新' }}</p>
      </template>
    </el-drawer>
  </section>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import request from '@/utils/request'
const rows=ref([]), students=ref([]), total=ref(0), page=ref(1), loading=ref(false), studentsLoading=ref(false), error=ref(''), studentId=ref(''), weekStart=ref(''), selected=ref(null)
let searchVersion=0
function disabledDate(d) { return d.getDay() !== 1 || d > new Date() }
async function searchStudents(keyword='') {
  const version=++searchVersion; studentsLoading.value=true
  try { const result=await request.get('/api/admin/students', { keyword, page_size:20 }); if(version===searchVersion) students.value=result.list }
  catch(e) { error.value=e.message }
  finally { if(version===searchVersion) studentsLoading.value=false }
}
async function load() {
  if(loading.value) return
  loading.value=true; error.value=''; rows.value=[]; selected.value=null
  try { const result=await request.get('/api/admin/ai-reports/weekly', { page:page.value, page_size:10, student_id:studentId.value || undefined, week_start:weekStart.value || undefined }); rows.value=result.list; total.value=result.total }
  catch(e) { error.value=e.message; total.value=0 }
  finally { loading.value=false }
}
function search() { page.value=1; load() }
onMounted(() => { load(); searchStudents() })
</script>
<style scoped>
.muted{color:#66758b;font-size:14px}.pagination{margin-top:24px}.stats{display:flex;justify-content:space-between;margin:24px 0}.summary{white-space:pre-wrap;line-height:1.8}.el-tag{margin:4px}
</style>
