<template>
  <div class="page-shell questions-page">
    <div class="page-heading">
      <div>
        <h2>题库管理</h2>
        <p>维护题目、正确答案、解析和 Q 矩阵关联；所有写入均通过管理端 API 完成。</p>
      </div>
      <div class="heading-actions">
        <el-button @click="batchDialogVisible = true">
          <el-icon><Upload /></el-icon>
          批量导入
        </el-button>
        <el-button type="primary" @click="openCreate">
          <el-icon><Plus /></el-icon>
          新建题目
        </el-button>
      </div>
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
        <el-input v-model="filters.keyword" clearable placeholder="搜索题干关键词" class="keyword-input" @keyup.enter="applyFilters">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-select v-model="filters.knowledge_point_id" clearable filterable placeholder="知识点" class="filter-select">
          <el-option v-for="item in knowledgePointOptions" :key="item.id" :label="item.name" :value="item.id" />
        </el-select>
        <el-select v-model="filters.type" clearable placeholder="题型" class="filter-select">
          <el-option v-for="item in questionTypes" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-input-number v-model="filters.difficulty_min" :min="0" :max="1" :step="0.05" :precision="2" controls-position="right" placeholder="难度下限" class="difficulty-input" />
        <span class="range-separator">至</span>
        <el-input-number v-model="filters.difficulty_max" :min="0" :max="1" :step="0.05" :precision="2" controls-position="right" placeholder="难度上限" class="difficulty-input" />
        <el-button type="primary" @click="applyFilters">筛选</el-button>
        <el-button @click="resetFilters">重置</el-button>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table v-loading="listLoading" :data="questions" stripe row-key="id" @row-click="openEdit">
        <el-table-column prop="content" label="题干" min-width="300" show-overflow-tooltip />
        <el-table-column prop="type" label="题型" width="100">
          <template #default="{ row }">{{ questionTypeLabel(row.type) }}</template>
        </el-table-column>
        <el-table-column prop="difficulty" label="难度" width="90">
          <template #default="{ row }">{{ Number(row.difficulty || 0).toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="关联知识点" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">
            <el-tag v-for="(name, index) in row.knowledge_point_names" :key="`${row.id}-${index}`" size="small" class="kp-tag">
              {{ name || row.knowledge_point_ids[index] }}
            </el-tag>
            <span v-if="!row.knowledge_point_ids?.length" class="muted">未关联</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="170" />
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click.stop="openEdit(row)">编辑</el-button>
            <el-button link type="danger" @click.stop="confirmDelete(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty :description="listLoading ? '正在加载' : '暂无题目数据'" :image-size="100" />
        </template>
      </el-table>
      <div class="pagination-row">
        <span class="muted">共 {{ total }} 道题目</span>
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
    </el-card>

    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="760px" destroy-on-close>
      <el-alert v-if="dialogError" class="dialog-alert" :title="dialogError" type="error" show-icon closable @close="dialogError = ''" />
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="100px">
        <el-form-item label="题型" prop="type">
          <el-radio-group v-model="form.type" @change="handleTypeChange">
            <el-radio v-for="item in questionTypes" :key="item.value" :label="item.value">{{ item.label }}</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="题干" prop="content">
          <el-input v-model="form.content" type="textarea" :rows="4" maxlength="2000" show-word-limit placeholder="请输入题目内容" />
        </el-form-item>
        <template v-if="form.type !== 'true_false'">
          <el-form-item label="选项" prop="options">
            <div class="options-editor">
              <div v-for="(option, index) in form.options" :key="option.key" class="option-row">
                <el-input v-model="option.label" class="option-label" maxlength="10" placeholder="标签" />
                <el-input v-model="option.content" maxlength="500" placeholder="选项内容" />
                <el-button v-if="form.options.length > 2" text type="danger" @click="removeOption(index)">移除</el-button>
              </div>
              <el-button text type="primary" @click="addOption">+ 添加选项</el-button>
            </div>
          </el-form-item>
          <el-form-item label="正确答案" prop="answer">
            <el-select v-if="form.type === 'single_choice'" v-model="form.answer" placeholder="选择正确选项" style="width: 100%">
              <el-option v-for="option in form.options" :key="option.key" :label="`${option.label}：${option.content}`" :value="option.label" />
            </el-select>
            <el-checkbox-group v-else v-model="form.answerOptions">
              <el-checkbox v-for="option in form.options" :key="option.key" :label="option.label">{{ option.label }}</el-checkbox>
            </el-checkbox-group>
          </el-form-item>
        </template>
        <el-form-item v-else label="正确答案" prop="answer">
          <el-radio-group v-model="form.answer">
            <el-radio label="true">正确</el-radio>
            <el-radio label="false">错误</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="难度" prop="difficulty">
          <el-slider v-model="form.difficulty" :min="0" :max="1" :step="0.05" show-input />
        </el-form-item>
        <el-form-item label="解析" prop="explanation">
          <el-input v-model="form.explanation" type="textarea" :rows="3" maxlength="1000" show-word-limit />
        </el-form-item>
        <el-form-item label="关联知识点" prop="knowledge_point_ids">
          <el-select v-model="form.knowledge_point_ids" multiple filterable collapse-tags collapse-tags-tooltip placeholder="至少关联一个知识点" style="width: 100%">
            <el-option v-for="item in knowledgePointOptions" :key="item.id" :label="`${item.name}（${item.id}）`" :value="item.id" />
          </el-select>
          <div class="form-tip">保存时会在同一后端事务中同步更新 Q 矩阵。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveQuestion">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="batchDialogVisible" title="批量导入题目" width="760px" destroy-on-close>
      <el-alert class="import-help" type="info" show-icon :closable="false">
        <template #default>粘贴 JSON 数组，或粘贴 <code>{ questions: [...] }</code>。每行结构与新建题目相同；服务端会逐行校验并返回失败原因。</template>
      </el-alert>
      <el-input v-model="importText" type="textarea" :rows="12" placeholder="[{&quot;content&quot;:&quot;...&quot;,&quot;type&quot;:&quot;single_choice&quot;,...}]" />
      <el-alert v-if="importError" class="dialog-alert" :title="importError" type="error" show-icon />
      <div v-if="importResult" class="import-result">
        <div class="import-summary">
          <el-tag type="success">成功 {{ importResult.success_count }} 行</el-tag>
          <el-tag type="danger">失败 {{ importResult.fail_count }} 行</el-tag>
        </div>
        <el-table v-if="importResult.errors?.length" :data="importResult.errors" size="small" border>
          <el-table-column prop="row" label="行号" width="80" />
          <el-table-column prop="message" label="失败原因" />
        </el-table>
        <el-empty v-else description="没有失败记录" :image-size="70" />
      </div>
      <template #footer>
        <el-button @click="batchDialogVisible = false">关闭</el-button>
        <el-button type="primary" :loading="importing" @click="runBatchImport">开始导入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request, { getRequestErrorInfo } from '@/utils/request'

const questionTypes = [
  { value: 'single_choice', label: '单选题' },
  { value: 'multi_choice', label: '多选题' },
  { value: 'true_false', label: '判断题' },
]
const pageError = ref('')
const listLoading = ref(false)
const saving = ref(false)
const importing = ref(false)
const questions = ref([])
const total = ref(0)
const knowledgePointOptions = ref([])
const filters = reactive({ keyword: '', knowledge_point_id: null, type: null, difficulty_min: null, difficulty_max: null })
const pagination = reactive({ page: 1, page_size: 10 })
const dialogVisible = ref(false)
const dialogMode = ref('create')
const dialogError = ref('')
const formRef = ref(null)
const form = reactive({
  id: null,
  content: '',
  type: 'single_choice',
  difficulty: 0.5,
  options: [],
  answer: '',
  answerOptions: [],
  explanation: '',
  knowledge_point_ids: [],
})
const batchDialogVisible = ref(false)
const importText = ref('')
const importError = ref('')
const importResult = ref(null)

const dialogTitle = computed(() => dialogMode.value === 'create' ? '新建题目' : '编辑题目')
const formRules = {
  type: [{ required: true, message: '请选择题型', trigger: 'change' }],
  content: [{ required: true, message: '请输入题干', trigger: 'blur' }],
  difficulty: [{ required: true, message: '请输入难度', trigger: 'change' }],
  knowledge_point_ids: [{ type: 'array', required: true, min: 1, message: '至少关联一个知识点', trigger: 'change' }],
}

function errorMessage(error, fallback) {
  return getRequestErrorInfo(error).message || fallback
}

function questionTypeLabel(type) {
  return questionTypes.find((item) => item.value === type)?.label || type
}

async function loadKnowledgePoints() {
  try {
    const first = await request.get('/api/admin/knowledge-points', { page: 1, page_size: 100 })
    const result = [...(first.list || [])]
    const pages = Math.ceil((first.total || result.length) / 100)
    for (let page = 2; page <= pages; page += 1) {
      const next = await request.get('/api/admin/knowledge-points', { page, page_size: 100 })
      result.push(...(next.list || []))
    }
    knowledgePointOptions.value = result
  } catch (error) {
    pageError.value = `知识点选项加载失败：${errorMessage(error, '请稍后重试')}`
  }
}

async function loadList() {
  listLoading.value = true
  try {
    const data = await request.get('/api/admin/questions', {
      page: pagination.page,
      page_size: pagination.page_size,
      knowledge_point_id: filters.knowledge_point_id || undefined,
      type: filters.type || undefined,
      difficulty_min: filters.difficulty_min ?? undefined,
      difficulty_max: filters.difficulty_max ?? undefined,
      keyword: filters.keyword.trim() || undefined,
    })
    questions.value = data.list || []
    total.value = data.total || 0
  } catch (error) {
    pageError.value = `题目列表加载失败：${errorMessage(error, '请稍后重试')}`
  } finally {
    listLoading.value = false
  }
}

function applyFilters() {
  if (filters.difficulty_min !== null && filters.difficulty_max !== null && filters.difficulty_min > filters.difficulty_max) {
    pageError.value = '筛选失败：难度下限不能大于难度上限'
    return
  }
  pagination.page = 1
  loadList()
}

function resetFilters() {
  Object.assign(filters, { keyword: '', knowledge_point_id: null, type: null, difficulty_min: null, difficulty_max: null })
  applyFilters()
}

function makeOption(label = '') {
  return { key: `${Date.now()}-${Math.random()}`, label, content: '' }
}

function defaultOptions() {
  return [makeOption('A'), makeOption('B'), makeOption('C'), makeOption('D')]
}

function resetForm() {
  Object.assign(form, {
    id: null,
    content: '',
    type: 'single_choice',
    difficulty: 0.5,
    options: defaultOptions(),
    answer: 'A',
    answerOptions: [],
    explanation: '',
    knowledge_point_ids: [],
  })
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
    const detail = await request.get(`/api/admin/questions/${row.id}`)
    Object.assign(form, {
      id: detail.id,
      content: detail.content,
      type: detail.type,
      difficulty: detail.difficulty,
      options: (detail.options || []).map((item) => ({ ...item, key: `${Date.now()}-${Math.random()}` })),
      answer: detail.type === 'multi_choice' ? '' : detail.answer,
      answerOptions: detail.type === 'multi_choice' ? detail.answer.split(',').filter(Boolean) : [],
      explanation: detail.explanation || '',
      knowledge_point_ids: detail.knowledge_point_ids || [],
    })
    if (form.type === 'true_false' && !form.options.length) form.options = [makeOption('对'), makeOption('错')]
  } catch (error) {
    dialogError.value = `题目详情加载失败：${errorMessage(error, '请稍后重试')}`
  }
}

function handleTypeChange(type) {
  if (type === 'true_false') {
    form.options = [makeOption('对'), makeOption('错')]
    form.answer = 'true'
    form.answerOptions = []
  } else {
    if (form.options.length < 2 || form.options[0]?.label === '对') form.options = defaultOptions()
    form.answer = form.options[0]?.label || 'A'
    form.answerOptions = []
  }
}

function addOption() {
  const labels = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
  const label = labels[form.options.length] || ''
  form.options.push(makeOption(label))
}

function removeOption(index) {
  const removed = form.options[index]?.label
  form.options.splice(index, 1)
  if (form.type === 'multi_choice') form.answerOptions = form.answerOptions.filter((item) => item !== removed)
  else if (form.answer === removed) form.answer = form.options[0]?.label || ''
}

function buildPayload() {
  return {
    content: form.content.trim(),
    type: form.type,
    difficulty: form.difficulty,
    options: form.type === 'true_false'
      ? [{ label: '对', content: '正确' }, { label: '错', content: '错误' }]
      : form.options.map(({ label, content }) => ({ label: label.trim(), content: content.trim() })),
    answer: form.type === 'multi_choice' ? form.answerOptions.join(',') : form.answer,
    explanation: form.explanation,
    knowledge_point_ids: form.knowledge_point_ids,
  }
}

async function saveQuestion() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  if (form.type !== 'true_false' && form.options.some((option) => !option.label.trim() || !option.content.trim())) {
    dialogError.value = '保存失败：每个选项都需要填写标签和内容'
    return
  }
  if (form.type !== 'multi_choice' && !form.answer) {
    dialogError.value = '保存失败：请选择正确答案'
    return
  }
  if (form.type === 'multi_choice' && !form.answerOptions.length) {
    dialogError.value = '保存失败：多选题至少选择一个正确答案'
    return
  }
  const answerSummary = form.type === 'multi_choice'
    ? form.answerOptions.join('、')
    : form.answer
  const questionSummary = `题型：${questionTypeLabel(form.type)}；答案：${answerSummary || '未设置'}；关联知识点：${form.knowledge_point_ids.length} 个`
  try {
    await ElMessageBox.confirm(
      `将保存题目并同步 Q 矩阵。\n\n${questionSummary}\n\n确定继续吗？`,
      '确认保存题目',
      { type: 'warning', confirmButtonText: '确认保存', cancelButtonText: '取消' },
    )
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    return
  }
  saving.value = true
  dialogError.value = ''
  try {
    const payload = buildPayload()
    if (dialogMode.value === 'create') await request.post('/api/admin/questions', payload)
    else await request.put(`/api/admin/questions/${form.id}`, payload)
    ElMessage.success(dialogMode.value === 'create' ? '题目创建成功，Q 矩阵已同步' : '题目更新成功，Q 矩阵已同步')
    dialogVisible.value = false
    await Promise.all([loadList(), loadKnowledgePoints()])
  } catch (error) {
    dialogError.value = `保存失败：${errorMessage(error, '请检查题目和知识点关联')}`
  } finally {
    saving.value = false
  }
}

async function confirmDelete(row) {
  try {
    await ElMessageBox.confirm(`确定删除这道题吗？删除会同时移除它的 Q 矩阵关联。\n\n${row.content}`, '删除确认', {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
    })
    await request.delete(`/api/admin/questions/${row.id}`)
    ElMessage.success('题目已删除')
    await Promise.all([loadList(), loadKnowledgePoints()])
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    pageError.value = `删除失败：${errorMessage(error, '服务端拒绝了删除请求')}`
  }
}

async function runBatchImport() {
  importError.value = ''
  importResult.value = null
  let parsed
  try {
    parsed = JSON.parse(importText.value)
  } catch {
    importError.value = '导入失败：JSON 格式不正确'
    return
  }
  const items = Array.isArray(parsed) ? parsed : parsed?.questions
  if (!Array.isArray(items) || !items.length) {
    importError.value = '导入失败：请提供非空的题目数组'
    return
  }
  importing.value = true
  try {
    importResult.value = await request.post('/api/admin/questions/batch-import', { questions: items })
    await Promise.all([loadList(), loadKnowledgePoints()])
  } catch (error) {
    importError.value = `导入请求失败：${errorMessage(error, '请稍后重试')}`
  } finally {
    importing.value = false
  }
}

onMounted(() => {
  loadKnowledgePoints()
  loadList()
})
</script>

<style scoped>
.page-shell { padding: 4px; }
.page-heading { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 18px; }
.page-heading h2 { margin: 0 0 6px; color: #1f2d3d; font-size: 22px; }
.page-heading p { margin: 0; color: #8492a6; }
.heading-actions { display: flex; gap: 10px; }
.page-alert, .dialog-alert { margin-bottom: 14px; }
.filter-card { margin-bottom: 16px; }
.filter-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.keyword-input { width: 240px; }
.filter-select { width: 155px; }
.difficulty-input { width: 140px; }
.range-separator { color: #8492a6; }
.table-card { min-height: 590px; }
.pagination-row { display: flex; align-items: center; justify-content: space-between; margin-top: 16px; }
.kp-tag { margin: 2px 4px 2px 0; }
.muted, .form-tip { color: #8492a6; }
.options-editor { width: 100%; }
.option-row { display: flex; gap: 8px; margin-bottom: 8px; }
.option-label { width: 100px; }
.form-tip { font-size: 12px; line-height: 1.5; margin-top: 5px; }
.import-help { margin-bottom: 12px; }
.import-result { margin-top: 16px; }
.import-summary { display: flex; gap: 8px; margin-bottom: 10px; }
code { color: #d14; }
@media (max-width: 900px) {
  .page-heading { gap: 12px; flex-direction: column; }
  .keyword-input, .filter-select { width: min(100%, 240px); }
}
</style>
