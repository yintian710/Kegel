<script setup lang="ts">
import { computed } from 'vue'
import type { AdminOverviewData, AdminVisit, Purchase } from '../api'
import AdminIcon from './AdminIcon.vue'
import { fmtTime, purchaseStatus, rewardStatus, type AdminTab } from './adminFormat'

const props = defineProps<{ data: AdminOverviewData; uncertain: Purchase[]; flagged: AdminVisit[]; busy: boolean }>()
const emit = defineEmits<{ open: []; goto: [tab: AdminTab] }>()

const status = computed(() => props.data.status)
const quotaPercent = computed(() => {
  const limit = parseFloat(status.value.quota.limit)
  const used = parseFloat(status.value.quota.used)
  if (!limit) return 0
  return Math.min(100, Math.round((used / limit) * 100))
})
const recentOrders = computed(() => props.data.purchases.slice(0, 6))
const recentRewards = computed(() => props.data.rewards.slice(0, 6))
</script>

<template>
  <div class="adm-grid c4">
    <div class="adm-card adm-stat">
      <span class="label">今日打卡</span>
      <span class="value" :style="{ color: status.is_open ? 'var(--adm-ok)' : 'var(--text-dim)' }">
        {{ status.is_open ? '已开放' : '未开放' }}
      </span>
      <span class="hint">
        {{ status.is_open ? `开放方式：${status.open_reason || '系统'}` : `最晚 ${data.settings.deadline} 自动开放` }}
      </span>
      <button v-if="!status.is_open" class="adm-btn primary sm" type="button" style="align-self: flex-start; margin-top: 6px" :disabled="busy" @click="emit('open')">
        <AdminIcon name="bolt" /> 立即开放
      </button>
    </div>

    <div class="adm-card adm-stat">
      <span class="label">今日完成人数</span>
      <span class="value">{{ status.total.toLocaleString() }}</span>
      <span class="hint">{{ status.day }}（北京时间）</span>
    </div>

    <div class="adm-card adm-stat">
      <span class="label">全站 LDC 兑换额度</span>
      <span class="value">{{ status.quota.remaining }} <small style="font-size: 13px; font-weight: 600; color: var(--text-muted)">LDC 剩余</small></span>
      <div class="adm-bar" :class="{ warn: quotaPercent >= 80 }"><i :style="{ width: quotaPercent + '%' }" /></div>
      <span class="hint">已用 {{ status.quota.used }} / {{ status.quota.limit }}（{{ quotaPercent }}%）</span>
    </div>

    <div class="adm-card adm-stat">
      <span class="label">打卡规则</span>
      <span class="value">{{ data.settings.min_step_seconds }} 秒<small style="font-size: 13px; font-weight: 600; color: var(--text-muted)"> / 次</small></span>
      <span class="hint">{{ data.settings.reward_tiers.length }} 档名次奖励 · 不发货名单 {{ data.settings.no_payout_user_ids?.length ?? 0 }} 人</span>
    </div>
  </div>

  <div class="adm-card">
    <div class="adm-card-head">
      <div>
        <h3>待处理事项</h3>
        <p class="sub">需要你介入的订单与访问异常</p>
      </div>
    </div>
    <div class="adm-todo" style="margin-top: 8px">
      <div v-for="order in uncertain" :key="order.order_no" class="adm-todo-row">
        <span class="dot danger" />
        <div class="txt">
          <b>订单待人工核对</b> · @{{ order.username }} 兑换 {{ order.ldc_amount }} LDC
          <span>{{ order.order_no }} · {{ fmtTime(order.created_at) }}</span>
        </div>
        <button class="adm-btn sm" type="button" @click="emit('goto', 'shop')">去处理</button>
      </div>
      <div v-for="visit in flagged" :key="visit.user_id" class="adm-todo-row">
        <span class="dot" />
        <div class="txt">
          <b>访问异常待审核</b> · {{ visit.username ? '@' + visit.username : '匿名访客' }}（{{ visit.count }} 次）
          <span>{{ visit.reason }}</span>
        </div>
        <button class="adm-btn sm" type="button" @click="emit('goto', 'rules')">去审核</button>
      </div>
      <div v-if="!uncertain.length && !flagged.length" class="adm-allclear">
        <AdminIcon name="check" /> 一切正常，暂无待处理事项。
      </div>
    </div>
  </div>

  <div class="adm-grid c2">
    <div class="adm-card">
      <div class="adm-card-head">
        <h3>最近兑换</h3>
        <button class="adm-btn sm ghost" type="button" @click="emit('goto', 'shop')">查看全部</button>
      </div>
      <div class="adm-tablewrap" style="margin-top: 12px; max-height: 320px">
        <table class="adm-table">
          <tbody>
            <tr v-if="!recentOrders.length"><td class="adm-empty">暂无兑换记录</td></tr>
            <tr v-for="item in recentOrders" :key="item.order_no" :class="{ flag: item.no_payout }">
              <td><b>@{{ item.username }}</b><div class="muted" style="font-size: 12px">{{ fmtTime(item.created_at) }}</div></td>
              <td>{{ item.ldc_amount }} LDC</td>
              <td class="r"><span class="adm-tag" :class="purchaseStatus[item.status]?.tone">{{ purchaseStatus[item.status]?.label ?? item.status }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="adm-card">
      <div class="adm-card-head">
        <h3>最近奖励</h3>
        <button class="adm-btn sm ghost" type="button" @click="emit('goto', 'logs')">查看全部</button>
      </div>
      <div class="adm-tablewrap" style="margin-top: 12px; max-height: 320px">
        <table class="adm-table">
          <tbody>
            <tr v-if="!recentRewards.length"><td class="adm-empty">暂无奖励记录</td></tr>
            <tr v-for="item in recentRewards" :key="`${item.day}-${item.user_id}`">
              <td><b>@{{ item.username }}</b><div class="muted" style="font-size: 12px">{{ item.day }} · 第 {{ item.rank }} 名</div></td>
              <td>{{ item.amount }} 分</td>
              <td class="r"><span class="adm-tag" :class="rewardStatus[item.reward_status]?.tone">{{ rewardStatus[item.reward_status]?.label ?? item.reward_status }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
