<script setup lang="ts">
import type { StatusData, Settings } from '../api'

const props = defineProps<{ status: StatusData; settings: Settings; busy: boolean }>()
const emit = defineEmits<{ open: []; refresh: [] }>()
</script>

<template>
  <section id="sec-overview" style="margin-bottom:32px">
    <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:20px">
      <div><h1 style="font-size:26px;font-weight:800;margin:0 0 6px">管理后台</h1><p style="font-size:13px;color:var(--text-muted);margin:0">{{ props.status.day }} (北京时间) · 今日已有 {{ props.status.total }} 人完成打卡</p></div>
      <button class="btn-secondary" type="button" :disabled="busy" @click="emit('refresh')">刷新全部数据</button>
    </div>
    <div class="metrics-row">
      <div class="metric-card"><span class="metric-label">今日开放状态</span><div class="metric-val" :style="{color:status.is_open?'var(--emerald)':'var(--text-dim)'}">{{ status.is_open?'已开启':'待开启' }}</div><div style="display:flex;justify-content:space-between;align-items:center"><span class="metric-sub">{{ status.is_open ? `开放方式: ${status.open_reason || '系统'}` : '今日正常打卡尚未开放' }}</span><button class="btn-primary" type="button" style="padding:6px 14px;font-size:12px" :disabled="busy||status.is_open" @click="emit('open')">{{ status.is_open?'已开放':'手动开启' }}</button></div></div>
      <div class="metric-card"><span class="metric-label">最晚开启时间</span><div class="metric-val">{{ settings.deadline }}</div><span class="metric-sub">每日超过该时间将自动开放</span></div>
      <div class="metric-card"><span class="metric-label">每次时长</span><div class="metric-val">{{ settings.min_step_seconds }} 秒</div><span class="metric-sub">每次练习需满足的最短时间</span></div>
      <div class="metric-card"><span class="metric-label">全站每日 LDC 兑换额度</span><div class="metric-val">{{ status.quota.limit }} LDC</div><span class="metric-sub">已兑换 {{ status.quota.used }} LDC · 剩余 {{ status.quota.remaining }} LDC</span></div>
    </div>
  </section>
</template>
