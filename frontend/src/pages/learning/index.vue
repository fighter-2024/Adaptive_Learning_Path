<template>
  <view class="page">
    <!-- 顶部筛选 -->
    <view class="filter-bar">
      <uni-search-bar v-model="keyword" placeholder="搜索知识点" @confirm="onSearch" />
      <uni-segmented-control :values="filterOptions" :current="currentFilter"
                             @clickItem="onFilterChange" styleType="button" />
    </view>

    <!-- 知识点列表 -->
    <uni-list>
      <uni-list-item v-for="item in list" :key="item.id" :title="item.name"
                     :note="item.chapter_name"
                     :rightText="statusText(item.status)"
                     :thumb="statusIcon(item.status)"
                     thumb-size="sm"
                     @click="goDetail(item.id)">
      </uni-list-item>
    </uni-list>

    <!-- 空状态 -->
    <view v-if="!list.length" class="empty">
      <text class="empty-text">暂无知识点数据</text>
      <text class="empty-hint">TODO: 对接 GET /api/student/knowledge-points</text>
    </view>

    <!-- 加载更多 -->
    <uni-load-more :status="loadMoreStatus" />
  </view>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { get, showRequestError } from '@/utils/request'

const keyword = ref('')
const list = ref([])
const loadMoreStatus = ref('more')
const currentFilter = ref(0)
const filterOptions = ['全部', '薄弱', '已掌握']
const page = ref(1)
const total = ref(0)

const statusMap = {
  mastered: '已掌握',
  learning: '学习中',
  weak: '薄弱',
  not_started: '未开始'
}

const statusIconMap = {
  mastered: '✅',
  learning: '📖',
  weak: '⚠️',
  not_started: '⬜'
}

function statusText(status) {
  return statusMap[status] || ''
}

function statusIcon(status) {
  return statusIconMap[status] || ''
}

async function loadData() {
  loadMoreStatus.value = 'loading'
  try {
    const data = await get('/api/student/knowledge-points', {
      page: page.value,
      page_size: 20,
      keyword: keyword.value || undefined
    })
    list.value = data.list || []
    total.value = data.total || 0
    loadMoreStatus.value = list.value.length < total.value ? 'more' : 'noMore'
  } catch (error) {
    showRequestError(error, '加载知识点失败')
    loadMoreStatus.value = 'more'
  }
}

function onSearch() {
  page.value = 1
  loadData()
}

function onFilterChange(e) {
  currentFilter.value = e.currentIndex
  // TODO: 根据薄弱/已掌握筛选
  page.value = 1
  loadData()
}

function goDetail(id) {
  uni.navigateTo({ url: `/pages/learning/detail?id=${id}` })
}

onMounted(() => {
  loadData()
})
</script>

<style lang="scss" scoped>
.page { padding-bottom: 40rpx; }
.filter-bar { position: sticky; top: 0; z-index: 10; background: #fff; }
.empty { padding: 80rpx 0; text-align: center; }
.empty-text { font-size: 28rpx; color: #7f8c8d; display: block; }
.empty-hint { font-size: 24rpx; color: #bdc3c7; margin-top: 12rpx; display: block; }
</style>
