<script setup lang="ts">
export type AdminIconName =
  | 'dashboard' | 'rules' | 'shop' | 'users' | 'logs' | 'refresh' | 'search'
  | 'plus' | 'check' | 'home' | 'edit' | 'alert' | 'bolt'

defineProps<{ name: AdminIconName }>()

// 线性图标（24x24 viewBox，stroke 绘制）
const paths: Record<AdminIconName, string> = {
  dashboard: 'M3 3h8v10H3zM13 3h8v6h-8zM13 11h8v10h-8zM3 15h8v6H3z',
  rules: 'M4 6h10M18 6h2M4 12h2M10 12h10M4 18h12M20 18h0M14 4v4M8 10v4M18 16v4',
  shop: 'M3 9l1.5-5h15L21 9M3 9v11h18V9M3 9h18M9 20v-6h6v6',
  users: 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8M22 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8',
  logs: 'M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01',
  refresh: 'M21 12a9 9 0 1 1-3-6.7M21 4v5h-5',
  search: 'M21 21l-4.3-4.3M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14',
  plus: 'M12 5v14M5 12h14',
  check: 'M20 6L9 17l-5-5',
  home: 'M3 11l9-8 9 8M5 10v10h14V10',
  edit: 'M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z',
  alert: 'M12 9v4M12 17h.01M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z',
  bolt: 'M13 2L3 14h9l-1 8 10-12h-9z',
}
</script>

<template>
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path :d="paths[name]" />
  </svg>
</template>
