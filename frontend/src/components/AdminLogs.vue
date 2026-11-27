<script setup lang="ts">
import { computed, ref } from 'vue'
import type { CheckinEntry, PracticeTrigger } from '../api'
import AdminIcon from './AdminIcon.vue'
import { fmtTime, rewardStatus } from './adminFormat'

const props = defineProps<{ rewards: CheckinEntry[]; triggers: PracticeTrigger[] }>()

const view = ref<'rewards' | 'triggers'>('rewards')
const keyword = ref('')
const q = computed(() => keyword.value.trim().toLowerCase())

const rewards = computed(() => props.rewards.filter((r) => !q.value || r.username.toLowerCase().includes(q.value) || r.day.includes(q.value)))
const triggers = computed(() => props.triggers.filter((t) => !q.value || t.username.toLowerCase().includes(q.value) || t.day.includes(q.value)))
</script>

<template>
  <div class="adm-card">
    <div class="adm-card-head">
      <div class="adm-seg">
        <button type="button" :class="{ on: view === 'rewards' }" @click="view = 'rewards'">每日奖励 <em>{{ rewards.length }}</em></button>
        <button type="button" :class="{ on: view === 'triggers' }" @click="view = 'triggers'">练习触发 <em>{{ triggers.length }}</em></button>
      </div>
      <div class="adm-search">
        <AdminIcon name="search" />
        <input v-model="keyword" class="adm-input" type="search" placeholder="按用户名或日期筛选" aria-label="筛选记录">
      </div>
    </div>

    <div v-if="view === 'rewards'" class="adm-tablewrap" style="margin-top: 12px; max-height: 640px">
      <table class="adm-table">
        <thead><tr><th>日期 / 名次</th><th>用户</th><th>积分</th><th>状态</th><th>完成时间</th><th>领取时间</th></tr></thead>
        <tbody>
          <tr v-if="!rewards.length"><td colspan="6" class="adm-empty">暂无奖励记录</td></tr>
          <tr v-for="item in rewards" :key="`${item.day}-${item.user_id}`">
            <td class="nowrap">{{ item.day }} · <b>#{{ item.rank }}</b></td>
            <td>@{{ item.username }}</td>
            <td class="nowrap">{{ item.amount }} 分</td>
            <td><span class="adm-tag" :class="rewardStatus[item.reward_status]?.tone">{{ rewardStatus[item.reward_status]?.label ?? item.reward_status }}</span></td>
            <td class="nowrap muted">{{ fmtTime(item.completed_at) }}</td>
            <td class="nowrap muted">{{ fmtTime(item.claimed_at) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-else class="adm-tablewrap" style="margin-top: 12px; max-height: 640px">
      <table class="adm-table">
        <thead><tr><th>用户</th><th>第几次</th><th>触发时间</th><th>本轮标识</th></tr></thead>
        <tbody>
          <tr v-if="!triggers.length"><td colspan="4" class="adm-empty">暂无练习触发记录（仅保留最近 200 条）</td></tr>
          <tr v-for="item in triggers" :key="`${item.user_id}-${item.created_at}`">
            <td>@{{ item.username }}</td>
            <td>第 {{ item.group_no }} 次</td>
            <td class="nowrap muted">{{ fmtTime(item.created_at) }}</td>
            <td class="mono muted">{{ item.flow_id ? `${item.flow_id.slice(0, 10)}…` : '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
