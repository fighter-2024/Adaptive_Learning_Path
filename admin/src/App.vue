<!-- 根组件 -->
<template>
  <component :is="layout">
    <router-view />
  </component>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import MainLayout from '@/layouts/MainLayout.vue'

const route = useRoute()

/** 登录页不使用 MainLayout，其他页面使用 */
const layout = computed(() => {
  return route.path === '/login' ? 'div' : MainLayout
})
</script>
