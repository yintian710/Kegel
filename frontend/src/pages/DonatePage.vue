<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ApiError, donations, loginUrl, type DonationPayment, type DonationsData } from '../api'
import { useBodyAttributes } from '../composables/useBodyAttributes'
import { useIdentity } from '../composables/useIdentity'
import { ft } from '../composables/usePreferences'

useBodyAttributes({})
const identity = useIdentity()
const data = ref<DonationsData | null>(null)
const loading = ref(false)
const creating = ref(false)
const amount = ref('')
const notice = ref('')
const form = ref<HTMLFormElement | null>(null)
const chips = ['1.00', '5.00', '10.00', '50.00', '100.00']
let noticeTimer: number | undefined
let pendingTimer: number | undefined
const normalizedAmount = computed(() => amount.value === '' || !Number.isFinite(Number(amount.value)) ? '' : Number(amount.value).toFixed(2))

function notify(message: string): void { notice.value = message; window.clearTimeout(noticeTimer); noticeTimer = window.setTimeout(() => { notice.value = '' }, 4000) }
function messageOf(error: unknown): string { return error instanceof Error ? error.message : String(error) }
function displayTime(value: string | null): string { if (!value) return '—'; const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false }) }
function selectAmount(value: string): void { amount.value = value }
function submitPayment(payment: DonationPayment): void {
  const action = new URL(payment.action)
  const localHttp = action.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(action.hostname)
  if ((action.protocol !== 'https:' && !localHttp) || action.username || action.password) throw new Error('支付入口无效，请稍后重试。')
  const fields = Object.entries(payment.fields)
  if (!fields.length || fields.some(([, value]) => typeof value !== 'string')) throw new Error('支付信息无法读取，请刷新订单状态后重试。')
  const paymentForm = document.createElement('form')
  paymentForm.method = 'post'; paymentForm.action = action.href; paymentForm.hidden = true
  for (const [name, value] of fields) { const input = document.createElement('input'); input.type = 'hidden'; input.name = name; input.value = value; paymentForm.append(input) }
  document.body.append(paymentForm)
  try { HTMLFormElement.prototype.submit.call(paymentForm) } finally { paymentForm.remove() }
}
async function refresh(): Promise<void> {
  if (loading.value) return
  loading.value = true
  window.clearTimeout(pendingTimer)
  try {
    data.value = await donations.get({ headers: { 'Cache-Control': 'no-cache' } })
    if (!document.hidden && data.value.user && data.value.donation_orders.some(order => order.status === 'created')) pendingTimer = window.setTimeout(() => { void refresh() }, 15000)
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) { window.location.assign(loginUrl('/donate')); return }
    notify(`数据更新失败：${messageOf(error)}`)
  } finally { loading.value = false }
}
async function createDonation(): Promise<void> {
  if (creating.value || !form.value?.reportValidity()) return
  if (!data.value?.user) { window.location.assign(loginUrl('/donate')); return }
  creating.value = true
  try {
    const result = await donations.create(Number(amount.value).toFixed(2))
    submitPayment(result.payment)
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) { window.location.assign(loginUrl('/donate')); return }
    notify(`发起赞助失败：${messageOf(error)}`)
  } finally { creating.value = false }
}
function onVisibility(): void { if (document.hidden) window.clearTimeout(pendingTimer); else void refresh() }
onMounted(async () => {
  document.addEventListener('visibilitychange', onVisibility)
  if (new URLSearchParams(location.search).has('donation')) notify('已返回本站，赞助订单仍需支付平台回调确认，请稍后查看到账状态。')
  if (await identity.requireLogin('/donate')) await refresh()
})
onBeforeUnmount(() => { document.removeEventListener('visibilitychange', onVisibility); window.clearTimeout(noticeTimer); window.clearTimeout(pendingTimer) })
</script>

<template>
  <main id="donateMain" class="page-wrap">
    <div class="page-hero"><h1>LDC 赞助与感谢</h1><p>感谢每一份支持本站运行与持续改进的社区力量。</p></div>
    <div class="shop-columns">
      <div>
        <div class="card" style="margin-bottom:24px"><div class="card-header-line"><h2 class="card-title">支持本站</h2><span class="card-subtitle" :style="{ color: data?.donation_ready ? 'var(--emerald)' : 'var(--text-dim)' }">{{ data ? (data.donation_ready ? '安全支付 · 实时到账' : 'LDC 赞助接口暂未配置') : '' }}</span></div><p style="font-size:14px;color:var(--text-muted);line-height:1.6;margin-top:0">{{ ft('如果你喜欢提肛打卡，并希望它能稳定持续发展，欢迎通过 LINUX DO Credit 赞助支持我们。你的赞助将用于服务器日常运行。') }}</p>
          <form ref="form" @submit.prevent="createDonation"><label class="form-label" for="donationAmount">自定义赞助金额 (LDC)</label><div style="display:flex;gap:12px;align-items:center"><input id="donationAmount" v-model="amount" class="input-text" type="number" min="0.01" max="10000" step="0.01" placeholder="输入金额" inputmode="decimal" required aria-describedby="donationAmountHelp" style="font-size:18px;font-weight:700;max-width:200px"><button class="btn-primary" type="submit" :disabled="creating || !data?.donation_ready">{{ creating ? '正在创建订单…' : '赞助 LDC →' }}</button></div><p id="donationAmountHelp" style="font-size:12px;color:var(--text-muted)">可自行输入 0.01–10000.00 LDC，最多两位小数；下方金额仅供快捷选择。</p><div class="amount-chips"><button v-for="chip in chips" :key="chip" type="button" class="amount-chip" :class="{ selected: normalizedAmount === chip }" @click="selectAmount(chip)">{{ Number(chip) }} LDC</button></div><div class="notice-box"><span style="font-size:18px">💡</span><div><strong>赞助不会增加站内积分</strong><br>赞助是对本站志愿维护的支持行为，不会增加任何站内积分，也不影响每日打卡奖励。</div></div></form>
        </div>
        <details class="card card-collapse" open><summary class="collapse-summary"><h2 class="card-title">我的赞助记录 <span class="card-subtitle">登录后查看个人赞助订单</span></h2><span class="collapse-chevron">⌄</span></summary><div class="collapse-body"><div class="table-wrap" style="max-height:380px"><table class="data-table"><thead><tr><th>时间</th><th>赞助金额</th><th>状态</th><th>订单号</th></tr></thead><tbody><tr v-if="!data || !data.user"><td colspan="4" class="empty-cell">登录 LINUX DO 后可查看自己的赞助订单。</td></tr><tr v-else-if="!data.donation_orders.length"><td colspan="4" class="empty-cell">你还没有赞助订单。赞助不会增加站内积分。</td></tr><tr v-for="order in data?.donation_orders ?? []" :key="order.order_no"><td>{{ displayTime(order.created_at) }}</td><td style="font-weight:600">{{ order.amount }} LDC</td><td><span class="status-pill" :class="{ credited: order.status === 'paid' }">{{ order.status === 'paid' ? '已确认到账' : '待确认到账' }}</span></td><td style="font-family:monospace;font-size:12px">{{ order.order_no.slice(0, 14) }}…</td></tr></tbody></table></div></div></details>
      </div>
      <div><details class="card card-collapse" open><summary class="collapse-summary"><div style="display:flex;align-items:baseline;gap:8px"><h2 class="card-title">LDC 赞助榜</h2><span class="card-subtitle">按已确认到账总额排序</span></div><div style="display:flex;align-items:center;gap:10px"><button class="btn-secondary" type="button" style="padding:5px 12px;font-size:12px" :disabled="loading" @click.stop="refresh">刷新榜单</button><span class="collapse-chevron">⌄</span></div></summary><div class="collapse-body"><div class="table-wrap" style="max-height:600px"><table class="rank-table"><thead><tr><th>排名</th><th>用户名</th><th>赞助总额</th><th>次数</th></tr></thead><tbody><tr v-if="!data"><td colspan="4" class="board-empty">正在读取赞助榜…</td></tr><tr v-else-if="!data.donation_leaderboard.length"><td colspan="4" class="board-empty">还没有已确认到账的 LDC 赞助。赞助经核验到账后会显示在这里。</td></tr><tr v-for="entry in data?.donation_leaderboard ?? []" :key="entry.rank"><td><span v-if="entry.rank <= 3" class="rank-badge" :class="`rank-${entry.rank}`">{{ entry.rank }}</span><template v-else>{{ entry.rank }}</template></td><td>@{{ entry.username }}</td><td style="color:var(--primary);font-weight:700">{{ entry.amount }} LDC</td><td style="text-align:right">{{ entry.count }} 次</td></tr></tbody></table></div></div></details></div>
    </div>
  </main>
  <div v-if="notice" class="toast-notice" role="status" aria-live="polite">{{ notice }}</div>
</template>

<style scoped>
.empty-cell{text-align:center;color:var(--text-dim);padding:24px}.board-empty{text-align:center;color:var(--text-dim);padding:32px 16px}
</style>
