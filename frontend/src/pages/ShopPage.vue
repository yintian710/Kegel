<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { ApiError, loginUrl, shop, titles as titlesApi, type Product, type Purchase, type ShopData } from '../api'
import { useBodyAttributes } from '../composables/useBodyAttributes'
import { useIdentity } from '../composables/useIdentity'

useBodyAttributes({})
const identity = useIdentity()
const data = ref<ShopData | null>(null)
const loading = ref(false)
const purchasing = ref(false)
const selectedProduct = ref<Product | null>(null)
const purchaseDialog = ref<HTMLDialogElement | null>(null)
const notice = ref('')
let noticeTimer: number | undefined

const statusMap: Record<Purchase['status'], { text: string; color: string }> = {
  success: { text: '自动发货成功', color: 'var(--emerald)' },
  simulated: { text: '模拟发货成功', color: 'var(--emerald)' },
  pending: { text: '转账处理中', color: '#d97706' },
  failed: { text: '失败(已退还积分)', color: '#dc2626' },
  uncertain: { text: '待核对流水', color: '#d97706' },
}
const kindMap: Record<string, string> = {
  checkin: '每日打卡奖励', admin_credit: '管理员增加积分', shop_purchase: '商品兑换扣除', shop_refund: '发货失败退款',
}

function notify(message: string): void {
  notice.value = message
  window.clearTimeout(noticeTimer)
  noticeTimer = window.setTimeout(() => { notice.value = '' }, 4000)
}
function messageOf(error: unknown): string { return error instanceof Error ? error.message : String(error) }
function isTicket(item: Product): boolean { return item.category === 'TICKET' }
const hasDiscount = computed(() => Number(data.value?.discount?.bp ?? 10000) < 10000)
function discountedPrice(item: Product): number {
  const special = item.special_discount_bp
  if (special !== null && special !== undefined && special < 10000) {
    const desired = item.points_price - Math.ceil((item.points_price * special) / 10000)
    return item.points_price - desired
  }
  const discount = data.value?.discount
  if (item.discount_eligible === 0 || !discount || discount.bp >= 10000) return item.points_price
  const desired = item.points_price - Math.ceil((item.points_price * discount.bp) / 10000)
  return item.points_price - Math.min(desired, discount.remaining)
}
function displayTime(value: string | number | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false })
}
function buttonState(item: Product): { text: string; disabled: boolean } {
  if (!data.value?.user) return { text: '登录后兑换', disabled: false }
  if (isTicket(item)) {
    if (Number(data.value.wallet?.balance ?? 0) < discountedPrice(item)) return { text: '积分不足', disabled: true }
    return { text: '购买抽卡券', disabled: false }
  }
  const remaining = Number(data.value.quota?.remaining ?? 0)
  if (Number(item.ldc_amount) > remaining) return { text: remaining <= 0 ? '今日兑换已停止' : 'LDC 额度不足', disabled: true }
  if (item.user_daily_limit > 0 && Number(item.user_remaining) <= 0) return { text: '今日已达限购', disabled: true }
  if (item.total_daily_limit > 0 && Number(item.total_remaining) <= 0) return { text: '今日已抢光', disabled: true }
  if (Number(data.value.wallet?.balance ?? 0) < discountedPrice(item)) return { text: '积分不足', disabled: true }
  return { text: '立即兑换', disabled: false }
}
function chooseProduct(item: Product): void {
  if (!data.value?.user) { window.location.assign(loginUrl('/shop')); return }
  if (buttonState(item).disabled) return
  selectedProduct.value = item
  purchaseDialog.value?.showModal()
}
async function purchase(): Promise<void> {
  const product = selectedProduct.value
  const user = data.value?.user
  if (purchasing.value || !product || !user) return
  purchasing.value = true
  const ticketProduct = isTicket(product)
  const requestKey = `${ticketProduct ? 'ticket-purchase' : 'ldc-purchase'}:${user.id}:${product.id}`
  try {
    let requestId = sessionStorage.getItem(requestKey)
    if (!requestId) {
      requestId = crypto.randomUUID()
      sessionStorage.setItem(requestKey, requestId)
    }
    if (ticketProduct) {
      await titlesApi.buyTicket({ product_id: product.id, request_id: requestId })
      sessionStorage.removeItem(requestKey)
      purchaseDialog.value?.close()
      notify(`🎟️ 已购买${product.name}（${product.draw_count ?? 0} 抽），可前往「称号」页抽卡`)
      await refresh()
      return
    }
    const result = await shop.purchase({ product_id: product.id, request_id: requestId })
    if (result.status !== 'pending' && result.status !== 'uncertain') sessionStorage.removeItem(requestKey)
    purchaseDialog.value?.close()
    if (result.status === 'success' || result.status === 'simulated') notify(`🎉 兑换成功！${product.ldc_amount} LDC 已自动发货${result.trade_no ? `（流水号: ${result.trade_no}）` : ''}`)
    else if (result.status === 'failed') notify(`自动发货失败：${result.error || '未知原因'}，消耗积分已全额自动退还。`)
    else notify(`转账请求已提交，结果待核对：${result.error || '请稍后查看状态'}`)
    await refresh()
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) { window.location.assign(loginUrl('/shop')); return }
    notify(`${ticketProduct ? '购买' : '兑换'}失败：${messageOf(error)}`)
  } finally { purchasing.value = false }
}
async function refresh(): Promise<void> {
  if (loading.value) return
  loading.value = true
  try {
    data.value = await shop.get({ headers: { 'Cache-Control': 'no-cache' } })
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) { window.location.assign(loginUrl('/shop')); return }
    notify(`无法读取数据：${messageOf(error)}`)
  } finally { loading.value = false }
}
function onVisibility(): void { if (!document.hidden) void refresh() }
onMounted(async () => {
  document.addEventListener('visibilitychange', onVisibility)
  if (await identity.requireLogin('/shop')) await refresh()
})
onBeforeUnmount(() => { document.removeEventListener('visibilitychange', onVisibility); window.clearTimeout(noticeTimer) })
</script>

<template>
  <main id="shopMain" class="page-wrap">
    <div class="page-hero"><div style="display:flex;justify-content:space-between;align-items:flex-end;flex-wrap:wrap;gap:16px"><div><h1>商店与积分</h1><p>使用站内积分兑换 LDC，购买后系统通过官方接口自动转账发货至你的 Linux DO 账户。</p></div><RouterLink class="btn-primary" to="/donate" style="background:#fff;color:var(--primary);border:1px solid var(--primary-border);box-shadow:var(--shadow-sm)">赞助 LDC <span aria-hidden="true">↗</span></RouterLink></div></div>
    <div v-if="hasDiscount" class="card" style="margin-bottom:16px;border-color:#fcd34d;background:#fffbeb">
      <strong style="color:#b45309">UR 称号折扣生效：{{ data?.discount.label }}（全店通用）</strong>
      <span style="font-size:13px;color:var(--text-muted);margin-left:8px">今日已省 {{ data?.discount.saved_today }} / {{ data?.discount.cap }} 积分，还可省 {{ data?.discount.remaining }} 积分</span>
    </div>
    <div v-else-if="data?.user" class="card" style="margin-bottom:16px;font-size:13px;color:var(--text-muted)">拥有至尊 UR 称号可享全店商品 95 折（不可打折与特价商品除外，拥有即生效）。</div>
    <div class="shop-columns">
      <div>
        <div class="card" style="margin-bottom:24px">
          <div class="card-header-line"><h2 class="card-title">站内积分钱包</h2><span class="card-subtitle">{{ data?.quota ? `今日全站 LDC 兑换额度：已用 ${data.quota.used} / ${data.quota.limit} LDC（剩余 ${data.quota.remaining} LDC）` : '' }}</span></div>
          <p style="font-size:13px;color:var(--text-muted);margin:0">当前可用积分余额</p><div class="wallet-box-balance"><span>{{ data?.user && data.wallet ? Number(data.wallet.balance).toLocaleString() : '—' }}</span><span>积分</span></div>
          <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:12px"><RouterLink class="btn-primary" to="/">去每日打卡赚积分 →</RouterLink><button class="btn-secondary" type="button" :disabled="loading" @click="refresh">{{ loading ? '正在刷新…' : '刷新状态' }}</button></div>
          <p style="font-size:12px;color:var(--text-dim);margin:0">{{ data?.user ? `当前登录账号：@${data.user.username}` : '登录后即可使用站内积分兑换 LDC 并自动发货。' }}</p>
        </div>
        <details class="card card-collapse" open style="margin-bottom:24px"><summary class="collapse-summary"><h2 class="card-title">兑换与自动发货记录 <span class="card-subtitle">仅显示当前账户兑换流水</span></h2><span class="collapse-chevron">⌄</span></summary><div class="collapse-body"><div class="table-wrap" style="max-height:360px"><table class="data-table"><thead><tr><th>时间</th><th>商品</th><th>消耗积分</th><th>发货状态</th></tr></thead><tbody><tr v-if="!data"><td colspan="4" class="empty-cell">正在加载兑换记录…</td></tr><tr v-else-if="!data.user"><td colspan="4" class="empty-cell">登录 LINUX DO 后可查看个人商品兑换记录。</td></tr><tr v-else-if="!data.purchases.length"><td colspan="4" class="empty-cell">暂无兑换记录，使用积分可兑换上方 LDC。</td></tr><tr v-for="item in data?.purchases ?? []" :key="item.order_no"><td>{{ displayTime(item.created_at) }}</td><td>{{ item.product_name }} (+{{ item.ldc_amount }} LDC)</td><td style="color:var(--text-muted);font-weight:600">-{{ item.points_cost }} 分</td><td><span class="status-pill" :class="{ credited: item.status === 'success' || item.status === 'simulated' }" :style="{ color: statusMap[item.status].color }">{{ statusMap[item.status].text }}</span></td></tr></tbody></table></div></div></details>
        <details class="card card-collapse" open><summary class="collapse-summary"><h2 class="card-title">积分变动流水 <span class="card-subtitle">每日打卡奖励与兑换明细</span></h2><span class="collapse-chevron">⌄</span></summary><div class="collapse-body"><div class="table-wrap" style="max-height:360px"><table class="data-table"><thead><tr><th>时间</th><th>类型</th><th>积分变动</th><th>变动后余额</th></tr></thead><tbody><tr v-if="!data"><td colspan="4" class="empty-cell">正在读取流水记录…</td></tr><tr v-else-if="!data.user"><td colspan="4" class="empty-cell">登录 LINUX DO 后可查看自己的站内积分流水。</td></tr><tr v-else-if="!data.ledger.length"><td colspan="4" class="empty-cell">还没有积分记录，先去完成今日打卡赚积分吧。</td></tr><tr v-for="entry in data?.ledger ?? []" :key="entry.id"><td>{{ displayTime(entry.created_at) }}</td><td>{{ kindMap[entry.kind] || entry.kind }}</td><td :style="{ fontWeight: '600', color: entry.delta > 0 ? 'var(--primary)' : '#dc2626' }">{{ entry.delta > 0 ? `+${entry.delta}` : entry.delta }}</td><td>{{ entry.balance_after }} 积分</td></tr></tbody></table></div></div></details>
      </div>
      <div><details class="card card-collapse" open><summary class="collapse-summary"><div><h2 class="card-title">商品兑换</h2><span class="card-subtitle">全自动转账到账，每日限购保障社区公平</span></div><span class="collapse-chevron">⌄</span></summary><div class="collapse-body"><div class="data-scroll-box" style="max-height:760px"><div class="products-grid"><div v-if="!data" class="products-empty">正在加载商品…</div><div v-else-if="!data.products.length" class="products-empty"><div style="font-size:32px;margin-bottom:12px">🪙</div><div style="font-size:15px;font-weight:600;color:var(--text-main);margin-bottom:4px">暂无上架商品</div><div style="font-size:13px">管理员可在后台添加 LDC 自动发货商品。</div></div><article v-for="item in data?.products ?? []" :key="item.id" class="product-card"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px"><span class="product-badge">{{ isTicket(item) ? '抽卡券' : (item.category || 'LDC') + ' 自动发货' }}</span><span style="font-size:13px;font-weight:700;color:var(--emerald)">{{ isTicket(item) ? ((item.draw_count ?? 0) + ' 抽') : ('+' + item.ldc_amount + ' LDC') }}</span></div><h3 class="product-name">{{ item.name }}</h3><p class="product-desc">{{ item.description || (isTicket(item) ? '购买获得抽卡券，可前往「称号」页抽卡。' : '购买后系统将自动转账发货至你的 Linux DO 账户。') }}</p><div class="limits"><span v-if="!isTicket(item) && item.user_daily_limit > 0" :style="{ color: Number(item.user_remaining) <= 0 ? '#dc2626' : undefined }">个人今日剩余：{{ item.user_remaining ?? item.user_daily_limit }} / {{ item.user_daily_limit }} 份</span><span v-if="!isTicket(item) && item.total_daily_limit > 0" :style="{ color: Number(item.total_remaining) <= 0 ? '#dc2626' : undefined }">全站今日剩余：{{ item.total_remaining ?? item.total_daily_limit }} / {{ item.total_daily_limit }} 份</span></div><div class="product-footer"><span class="product-price"><span v-if="discountedPrice(item) < item.points_price" style="text-decoration:line-through;color:var(--text-dim);font-size:12px;margin-right:6px">{{ item.points_price }}</span>{{ discountedPrice(item) }} 积分</span><button class="btn-primary" type="button" style="padding:6px 14px;font-size:13px" :disabled="buttonState(item).disabled" @click="chooseProduct(item)">{{ buttonState(item).text }}</button></div></article></div></div></div></details></div>
    </div>
  </main>
  <dialog ref="purchaseDialog" class="dialog-modal"><form method="dialog" @submit.prevent="purchase"><h2 style="font-size:18px;font-weight:700;margin:0 0 10px">{{ selectedProduct && isTicket(selectedProduct) ? '确认购买抽卡券：' : '确认兑换：' }}{{ selectedProduct?.name }}</h2><div v-if="selectedProduct && isTicket(selectedProduct)" style="font-size:14px;color:var(--text-muted);line-height:1.6;margin-bottom:20px">即将消耗 <strong>{{ selectedProduct ? discountedPrice(selectedProduct) : 0 }} 积分</strong><span v-if="selectedProduct && discountedPrice(selectedProduct) < selectedProduct.points_price" style="color:var(--text-dim)">（原价 {{ selectedProduct.points_price }}，折扣生效）</span> 购买 <strong>{{ selectedProduct.name }}</strong>（可抽 <strong>{{ selectedProduct.draw_count ?? 0 }} 次</strong>）。<br>购买后前往「称号」页使用抽卡券抽取称号。</div><div v-else style="font-size:14px;color:var(--text-muted);line-height:1.6;margin-bottom:20px">即将消耗 <strong>{{ selectedProduct ? discountedPrice(selectedProduct) : 0 }} 积分</strong><span v-if="selectedProduct && discountedPrice(selectedProduct) < selectedProduct.points_price" style="color:var(--text-dim)">（原价 {{ selectedProduct.points_price }}，UR 折扣）</span> 兑换 <strong>{{ selectedProduct?.ldc_amount }} LDC</strong>。<br>发货方式：系统自动转账至当前登录用户 <strong>@{{ data?.user?.username }}</strong> 的 Linux DO 账户。</div><div class="notice-box" style="margin-bottom:20px"><span style="font-size:18px">⚡</span><div><strong>自动发货机制</strong><br>确认兑换后，系统将立即扣减积分并调用 Linux DO Credit 接口发起转账。若发货失败，积分将自动全额退还。</div></div><div style="display:flex;gap:12px;justify-content:flex-end"><button class="btn-secondary" type="button" @click="purchaseDialog?.close()">取消</button><button class="btn-primary" type="submit" :disabled="purchasing">{{ purchasing ? '处理中…' : (selectedProduct && isTicket(selectedProduct) ? '确认购买抽卡券' : '确认兑换并自动发货') }}</button></div></form></dialog>
  <div v-if="notice" class="toast-notice" role="status" aria-live="polite">{{ notice }}</div>
</template>

<style scoped>
.empty-cell{text-align:center;color:var(--text-dim);padding:24px 16px}.products-empty{grid-column:1/-1;text-align:center;padding:48px 24px;color:var(--text-dim)}.limits{font-size:12px;color:var(--text-dim);margin-bottom:14px;display:flex;flex-direction:column;gap:4px}.product-footer{display:flex;justify-content:space-between;align-items:center;margin-top:auto;padding-top:12px;border-top:1px solid var(--border-light)}
</style>
