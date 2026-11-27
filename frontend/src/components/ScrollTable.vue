<script setup lang="ts">
import { computed } from 'vue'

// 长表格统一在组件内滚动：高度介于「最少行数」与「最多行数」之间，超出最多行数时在内部滚动，表头吸顶。
// 行高按平均值估算（行内有两行文字时会略高），用于给容器定高，不是逐行精确换算。
const props = withDefaults(defineProps<{
  minRows?: number
  maxRows?: number
  rowHeight?: number
  headHeight?: number
}>(), { minRows: 4, maxRows: 10, rowHeight: 56, headHeight: 44 })

const style = computed(() => ({
  '--st-min': `${props.headHeight + props.rowHeight * props.minRows}px`,
  '--st-max': `${props.headHeight + props.rowHeight * Math.max(props.maxRows, props.minRows)}px`,
}))
</script>

<template>
  <div class="scroll-table" :style="style" tabindex="0" role="region" aria-label="可滚动表格">
    <slot />
  </div>
</template>

<style scoped>
.scroll-table {
  overflow: auto;
  overscroll-behavior: contain;
  min-height: var(--st-min);
  max-height: var(--st-max);
  scrollbar-width: thin;
  scrollbar-color: var(--border) transparent;
}

.scroll-table:focus-visible {
  outline: 2px solid var(--primary-border);
  outline-offset: -2px;
}

.scroll-table :deep(table) {
  width: 100%;
}

.scroll-table :deep(thead th) {
  position: sticky;
  top: 0;
  z-index: 2;
  background-color: var(--bg-card);
  box-shadow: 0 1px 0 var(--border);
}

.scroll-table::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

.scroll-table::-webkit-scrollbar-thumb {
  border-radius: 9999px;
  background: var(--border);
}

.scroll-table::-webkit-scrollbar-thumb:hover {
  background: var(--text-dim);
}
</style>
