<template>
  <div class="config-page">
    <div class="page-heading">
      <div>
        <h2>系统配置</h2>
        <p>调整学习路径排序权重，变更会在下一次推荐请求中生效。</p>
      </div>
      <el-button type="primary" :loading="saving" @click="saveConfig">保存配置</el-button>
    </div>

    <el-alert v-if="config.degraded" type="warning" show-icon title="当前配置存在降级状态" />

    <el-card v-loading="loading" class="config-card">
      <template #header><span>学习路径权重</span></template>
      <el-form label-width="180px">
        <el-form-item label="掌握度缺口权重">
          <el-input-number v-model="form.path_weight_mastery" :min="0" :max="1" :step="0.05" />
        </el-form-item>
        <el-form-item label="目标距离权重">
          <el-input-number v-model="form.path_weight_target_distance" :min="0" :max="1" :step="0.05" />
        </el-form-item>
        <el-form-item label="难度权重">
          <el-input-number v-model="form.path_weight_difficulty" :min="0" :max="1" :step="0.05" />
        </el-form-item>
        <el-form-item label="预计时间权重">
          <el-input-number v-model="form.path_weight_time_cost" :min="0" :max="1" :step="0.05" />
        </el-form-item>
        <el-form-item label="权重总和">
          <el-tag :type="weightTotal === 1 ? 'success' : 'danger'">{{ weightTotal.toFixed(4) }}</el-tag>
          <span class="form-hint">必须等于 1，允许误差 0.0001</span>
        </el-form-item>
        <el-form-item label="Profile 版本">
          <el-input v-model="form.path_weight_profile" maxlength="64" />
        </el-form-item>
      </el-form>
    </el-card>

    <el-card v-loading="loading" class="config-card">
      <template #header><span>DINA 与 AI 配置</span></template>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="EM 最大迭代">{{ config.dina_em_max_iterations }}</el-descriptions-item>
        <el-descriptions-item label="收敛阈值">{{ config.dina_em_convergence_threshold }}</el-descriptions-item>
        <el-descriptions-item label="失误率初值">{{ config.dina_s_initial }}</el-descriptions-item>
        <el-descriptions-item label="猜测率初值">{{ config.dina_g_initial }}</el-descriptions-item>
        <el-descriptions-item label="LLM Provider">{{ config.llm_provider }}</el-descriptions-item>
        <el-descriptions-item label="LLM Model">{{ config.llm_model }}</el-descriptions-item>
        <el-descriptions-item label="API Key">{{ config.llm_api_key_configured ? config.llm_api_key_masked : '未配置' }}</el-descriptions-item>
        <el-descriptions-item label="超时（秒）">{{ config.llm_timeout }}</el-descriptions-item>
      </el-descriptions>
      <el-form label-width="180px" class="api-key-form">
        <el-form-item label="替换 API Key">
          <el-input v-model="form.llm_api_key" type="password" show-password placeholder="留空表示不修改" />
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import request from '@/utils/request'
import { ElMessage } from 'element-plus'

const loading = ref(false)
const saving = ref(false)
const config = reactive({})
const form = reactive({
  path_weight_mastery: 0.4,
  path_weight_target_distance: 0.3,
  path_weight_difficulty: 0.2,
  path_weight_time_cost: 0.1,
  path_weight_profile: 'default-v1',
  llm_api_key: ''
})

const weightTotal = computed(() => [
  form.path_weight_mastery,
  form.path_weight_target_distance,
  form.path_weight_difficulty,
  form.path_weight_time_cost
].reduce((total, value) => total + Number(value || 0), 0))

function applyConfig(data) {
  Object.assign(config, data || {})
  for (const key of Object.keys(form)) {
    if (key !== 'llm_api_key' && data?.[key] !== undefined) form[key] = data[key]
  }
}

async function loadConfig() {
  loading.value = true
  try {
    applyConfig(await request.get('/api/admin/config'))
  } finally {
    loading.value = false
  }
}

async function saveConfig() {
  if (Math.abs(weightTotal.value - 1) > 0.0001) {
    ElMessage.warning('四项路径权重总和必须为 1')
    return
  }
  saving.value = true
  try {
    const data = await request.put('/api/admin/config', { ...form })
    applyConfig(data)
    form.llm_api_key = ''
    ElMessage.success('配置已更新')
  } finally {
    saving.value = false
  }
}

onMounted(loadConfig)
</script>

<style scoped>
.config-page { padding: 24px; }
.page-heading { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 20px; }
.page-heading h2 { margin: 0; }
.page-heading p { margin: 8px 0 0; color: #7b8495; }
.config-card { max-width: 900px; margin-bottom: 20px; }
.form-hint { margin-left: 12px; color: #8791a3; }
.api-key-form { margin-top: 20px; }
</style>
