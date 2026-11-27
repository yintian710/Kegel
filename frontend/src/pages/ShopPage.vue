<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { ApiError, loginUrl, shop, titles as titlesApi, type Product, type Purchase, type ShopData } from '../api'
import { useBodyAttributes } from '../composables/useBodyAttributes'
import ScrollTable from '../components/ScrollTable.vue'
import { useIdentity } from '../composables/useIdentity'
import { triggerHaptic } from '../composables/usePreferences'

useBodyAttributes({})
const identity = useIdentity()
const data = ref<ShopData | null>(null)
const loading = ref(false)
const purchasing = ref(false)
const checkingOrder = ref('')
const selectedProduct = ref<Product | null>(null)
const purchaseDialog = ref<HTMLDialogElement | null>(null)
const notice = ref('')
const searchKeyword = ref('')
const activeCategory = ref<'ALL' | 'TICKET' | 'LDC' | 'PRIVILEGE'>('ALL')
const historyTab = ref<'purchases' | 'ledger'>('purchases')
let noticeTimer: number | undefined

const statusMap: Record<Purchase['status'], { text: string; color: string; bg: string }> = {
  success: { text: '自动发货成功', color: '#0d9488', bg: 'rgba(13, 148, 136, 0.1)' },
  simulated: { text: '模拟发货成功', color: '#0d9488', bg: 'rgba(13, 148, 136, 0.1)' },
  pending: { text: '转账处理中', color: '#d97706', bg: 'rgba(217, 119, 6, 0.1)' },
  failed: { text: '失败(已退积分)', color: '#dc2626', bg: 'rgba(220, 38, 38, 0.1)' },
  uncertain: { text: '待核对流水', color: '#d97706', bg: 'rgba(217, 119, 6, 0.1)' },
}

const kindMap: Record<string, string> = {
  checkin: '每日打卡奖励',
  admin_credit: '管理员增加积分',
  shop_purchase: '商品兑换扣除',
  shop_refund: '发货失败退款',
  ticket_purchase: '抽卡券购买扣除',
}

function notify(message: string): void {
  notice.value = message
  window.clearTimeout(noticeTimer)
  noticeTimer = window.setTimeout(() => { notice.value = '' }, 4000)
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function isTicket(item: Product): boolean {
  return item.category === 'TICKET'
}

const hasDiscount = computed(() => Number(data.value?.discount?.bp ?? 10000) < 10000)

// 实付价由服务端按「限时折扣 × 称号折扣」算出（含每日节省上限），前端只展示
function discountedPrice(item: Product): number {
  return item.price_now ?? item.points_price
}

// 划线原价：只在真的有折扣时显示
function originalStrikedPrice(item: Product): number | null {
  return discountedPrice(item) < item.points_price ? item.points_price : null
}

// ── 限时折扣倒计时 ──
const nowMs = ref(Date.now())
let clockTimer: number | undefined
let promoRefreshing = false

function promoLive(item: Product): boolean {
  return !!item.promo_active && (item.promo_ends_at ?? 0) * 1000 > nowMs.value
}

function zhe(bp: number | null | undefined): string {
  return bp ? `${(bp / 1000).toFixed(1).replace(/\.0$/, '')} 折` : ''
}

function countdownText(item: Product): string {
  const left = Math.max(0, Math.floor((item.promo_ends_at ?? 0) - nowMs.value / 1000))
  const pad = (n: number) => String(n).padStart(2, '0')
  const days = Math.floor(left / 86400)
  const clock = `${pad(Math.floor((left % 86400) / 3600))}:${pad(Math.floor((left % 3600) / 60))}:${pad(left % 60)}`
  return days ? `${days} 天 ${clock}` : clock
}

function tickClock(): void {
  nowMs.value = Date.now()
  // 有折扣刚好到期：重新拉取一次，价格恢复原价
  const expired = (data.value?.products ?? []).some((item) => item.promo_active && (item.promo_ends_at ?? 0) * 1000 <= nowMs.value)
  if (expired && !promoRefreshing) {
    promoRefreshing = true
    void refresh().finally(() => { promoRefreshing = false })
  }
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
    return { text: '立即兑换', disabled: false }
  }
  const remaining = Number(data.value.quota?.remaining ?? 0)
  if (Number(item.ldc_amount) > remaining) return { text: remaining <= 0 ? '今日额度已尽' : 'LDC 额度不足', disabled: true }
  if (item.user_daily_limit > 0 && Number(item.user_remaining) <= 0) return { text: '今日已达限购', disabled: true }
  if (item.total_daily_limit > 0 && Number(item.total_remaining) <= 0) return { text: '今日已抢光', disabled: true }
  if (Number(data.value.wallet?.balance ?? 0) < discountedPrice(item)) return { text: '积分不足', disabled: true }
  return { text: '立即兑换', disabled: false }
}

const filteredProducts = computed(() => {
  const list = data.value?.products ?? []
  return list.filter(item => {
    if (activeCategory.value === 'TICKET' && item.category !== 'TICKET') return false
    if (activeCategory.value === 'LDC' && item.category === 'TICKET') return false
    if (activeCategory.value === 'PRIVILEGE' && (item.category === 'TICKET' || Number(item.ldc_amount) > 0)) return false
    if (searchKeyword.value.trim()) {
      const q = searchKeyword.value.trim().toLowerCase()
      const matchName = item.name.toLowerCase().includes(q)
      const matchDesc = (item.description || '').toLowerCase().includes(q)
      return matchName || matchDesc
    }
    return true
  })
})

function chooseProduct(item: Product): void {
  if (!data.value?.user) {
    window.location.assign(loginUrl('/shop'))
    return
  }
  if (buttonState(item).disabled) return
  selectedProduct.value = item
  purchaseDialog.value?.showModal()
  triggerHaptic()
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
      notify(`🎟️ 兑换成功！已获得 ${product.name}（${product.draw_count ?? 0} 抽），可前往「称号」页抽卡`)
      await refresh()
      return
    }
    const result = await shop.purchase({ product_id: product.id, request_id: requestId })
    if (result.status !== 'pending' && result.status !== 'uncertain') {
      sessionStorage.removeItem(requestKey)
    }
    purchaseDialog.value?.close()
    if (result.status === 'success' || result.status === 'simulated') {
      notify(`🎉 兑换成功！${product.ldc_amount} LDC 已自动转账${result.trade_no ? `（流水号: ${result.trade_no}）` : ''}`)
    } else if (result.status === 'failed') {
      notify(`自动发货失败：${result.error || '未知原因'}，消耗积分已全额退还。`)
    } else {
      notify(`转账结果待确认：${result.error || '请稍后查看状态'}。系统每 5 分钟自动核对，也可在兑换记录里点「查询发货状态」`)
    }
    await refresh()
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      window.location.assign(loginUrl('/shop'))
      return
    }
    notify(`${ticketProduct ? '购买' : '兑换'}失败：${messageOf(error)}`)
  } finally {
    purchasing.value = false
  }
}

async function checkOrder(item: Purchase): Promise<void> {
  if (checkingOrder.value) return
  checkingOrder.value = item.order_no
  try {
    const result = await shop.checkOrder(item.order_no)
    if (result.wallet) identity.setWallet(result.wallet)
    notify(result.message)
    await refresh()
  } catch (error) {
    notify(`查询失败：${messageOf(error)}`)
  } finally {
    checkingOrder.value = ''
  }
}

async function refresh(): Promise<void> {
  if (loading.value) return
  loading.value = true
  try {
    data.value = await shop.get({ headers: { 'Cache-Control': 'no-cache' } })
    if (data.value.wallet) {
      identity.setWallet(data.value.wallet)
    }
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      window.location.assign(loginUrl('/shop'))
      return
    }
    notify(`无法读取数据：${messageOf(error)}`)
  } finally {
    loading.value = false
  }
}

function onVisibility(): void {
  if (!document.hidden) void refresh()
}

onMounted(async () => {
  document.addEventListener('visibilitychange', onVisibility)
  clockTimer = window.setInterval(tickClock, 1000)
  if (await identity.requireLogin('/shop')) {
    await refresh()
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', onVisibility)
  window.clearInterval(clockTimer)
  window.clearTimeout(noticeTimer)
})
</script>

<template>
  <main class="shop-page-wrapper">
    <!-- 顶部商城标题、搜索框与三大资产指标卡片 -->
    <header class="shop-hero-header">
      <div class="shop-hero-left">
        <div class="shop-badge-icon" aria-hidden="true">
          <svg class="lotus-svg" viewBox="0 0 32 32" fill="none">
            <path d="M16 4C16 4 11 12 11 18C11 21.3137 13.2386 24 16 24C18.7614 24 21 21.3137 21 18C21 12 16 4 16 4Z" fill="url(#shop-lotus-grad)" />
            <path d="M9 13C9 13 4 18 5 23C5.5 25.5 8 26.5 11 25.5C13 24.8 14.5 23 15 21C13 20 10.5 17.5 9 13Z" fill="url(#shop-lotus-grad)" opacity="0.85" />
            <path d="M23 13C23 13 28 18 27 23C26.5 25.5 24 26.5 21 25.5C19 24.8 17.5 23 17 21C19 20 21.5 17.5 23 13Z" fill="url(#shop-lotus-grad)" opacity="0.85" />
            <defs>
              <linearGradient id="shop-lotus-grad" x1="16" y1="4" x2="16" y2="24" gradientUnits="userSpaceOnUse">
                <stop stop-color="#2dd4bf" />
                <stop offset="1" stop-color="#0d9488" />
              </linearGradient>
            </defs>
          </svg>
        </div>
        <div class="shop-hero-headings">
          <h1 class="shop-title">积分商城</h1>
          <p class="shop-subtitle">用坚持换好物 · 商品每周上新 · 自动秒级转账到账</p>
        </div>
      </div>

      <!-- 搜索框 -->
      <div class="shop-search-box">
        <span class="search-icon" aria-hidden="true">🔍</span>
        <input
          v-model="searchKeyword"
          type="search"
          placeholder="搜索商品..."
          class="shop-search-input"
          aria-label="搜索商品"
        />
        <button
          v-if="searchKeyword"
          type="button"
          class="search-clear-btn"
          aria-label="清空搜索"
          @click="searchKeyword = ''"
        >
          ✕
        </button>
      </div>

      <!-- 右侧三大指标胶囊卡片 -->
      <div class="shop-metrics-pills">
        <!-- 1. 我的积分 -->
        <div class="metric-card metric-points">
          <div class="metric-icon-wrap points-icon">
            <span>🪙</span>
          </div>
          <div class="metric-info">
            <span class="metric-label">我的积分</span>
            <span class="metric-val">{{ data?.user && data.wallet ? Number(data.wallet.balance).toLocaleString() : '—' }}</span>
          </div>
        </div>

        <!-- 2. UR 特权 -->
        <div class="metric-card metric-privilege" :class="{ active: hasDiscount }">
          <div class="metric-icon-wrap privilege-icon">
            <span>👑</span>
          </div>
          <div class="metric-info">
            <span class="metric-label">UR 特权</span>
            <span class="metric-val">{{ hasDiscount ? '95 折' : '未激活' }}</span>
          </div>
        </div>

        <!-- 3. LDC 额度池 -->
        <div class="metric-card metric-ldc">
          <div class="metric-icon-wrap ldc-icon">
            <span>📦</span>
          </div>
          <div class="metric-info">
            <span class="metric-label">LDC 额度池</span>
            <span class="metric-val">{{ data?.quota ? Number(data.quota.remaining).toLocaleString() : '—' }}</span>
          </div>
        </div>
      </div>
    </header>

    <!-- 分类筛选标签胶囊 -->
    <div class="shop-category-bar">
      <div class="category-pills">
        <button
          type="button"
          class="category-pill"
          :class="{ active: activeCategory === 'ALL' }"
          @click="activeCategory = 'ALL'"
        >
          全部商品
        </button>
        <button
          type="button"
          class="category-pill"
          :class="{ active: activeCategory === 'TICKET' }"
          @click="activeCategory = 'TICKET'"
        >
          🎟️ 抽卡券
        </button>
        <button
          type="button"
          class="category-pill"
          :class="{ active: activeCategory === 'LDC' }"
          @click="activeCategory = 'LDC'"
        >
          🪙 官方 LDC 额度
        </button>
        <button
          type="button"
          class="category-pill"
          :class="{ active: activeCategory === 'PRIVILEGE' }"
          @click="activeCategory = 'PRIVILEGE'"
        >
          👑 优惠特权
        </button>
      </div>

      <!-- 赞助入口快捷按钮 -->
      <RouterLink class="donate-quick-link" to="/donate">
        ❤️ 赞助 LDC 社区池 ↗
      </RouterLink>
    </div>

    <!-- 现代商品陈列展柜 (高颜值卡片网格) -->
    <section class="products-showcase-section">
      <div v-if="!data" class="products-empty-card">
        <div class="empty-spinner" />
        <span>正在读取商城商品列表…</span>
      </div>
      <div v-else-if="!filteredProducts.length" class="products-empty-card">
        <span class="empty-emoji">🪙</span>
        <h3>未找到匹配的商品</h3>
        <p>可以尝试切换分类筛选或清空搜索关键词。</p>
      </div>
      <div v-else class="modern-products-grid">
        <article
          v-for="item in filteredProducts"
          :key="item.id"
          class="modern-product-card"
          :class="{
            'is-ticket': isTicket(item),
            'is-hundred': isTicket(item) && item.draw_count === 100,
            'is-ten': isTicket(item) && item.draw_count === 10
          }"
        >
          <!-- 顶部标签栏 (热门/限定/到账说明) -->
          <div class="product-top-row">
            <span
              v-if="promoLive(item)"
              class="card-badge badge-discount"
            >
              ⏳ 限时 {{ zhe(item.promo_bp) }}
            </span>
            <span
              v-else-if="isTicket(item) && item.draw_count === 100"
              class="card-badge badge-hot"
            >
              🔥 热门推荐
            </span>
            <span
              v-else-if="isTicket(item) && item.draw_count === 10"
              class="card-badge badge-discount"
            >
              ⚡ 十连保底 SR
            </span>
            <span
              v-else-if="isTicket(item)"
              class="card-badge badge-ticket"
            >
              🎟️ 体验券
            </span>
            <span
              v-else
              class="card-badge badge-ldc"
            >
              🪙 自动转账
            </span>

            <!-- 右侧规格标签 -->
            <span v-if="isTicket(item)" class="spec-highlight">
              {{ item.draw_count ?? 0 }} 连抽
            </span>
            <span v-else class="spec-highlight">
              +{{ item.ldc_amount }} LDC
            </span>
          </div>

          <!-- 商品核心拟物卡槽视觉区 (Art Canvas) -->
          <div
            class="product-art-canvas"
            :class="{
              'art-gold': isTicket(item) && item.draw_count === 100,
              'art-purple': isTicket(item) && item.draw_count === 10,
              'art-teal': isTicket(item) && (item.draw_count ?? 1) < 10,
              'art-coin': !isTicket(item)
            }"
          >
            <div class="art-glow-ring" />
            
            <!-- 百连券豪华立绘插画 -->
            <div v-if="isTicket(item) && item.draw_count === 100" class="art-graphic-box">
              <span class="art-symbol-hero">🎴</span>
              <span class="art-symbol-sparkle sparkle-1">✨</span>
              <span class="art-symbol-sparkle sparkle-2">👑</span>
            </div>

            <!-- 十连券精品立绘插画 -->
            <div v-else-if="isTicket(item) && item.draw_count === 10" class="art-graphic-box">
              <span class="art-symbol-hero">🎴</span>
              <span class="art-symbol-sparkle sparkle-1">✨</span>
            </div>

            <!-- 单抽券立绘插画 -->
            <div v-else-if="isTicket(item)" class="art-graphic-box">
              <span class="art-symbol-hero">🎟️</span>
            </div>

            <!-- LDC 额度立体硬币 -->
            <div v-else class="art-graphic-box">
              <span class="art-symbol-hero">🪙</span>
              <span class="art-symbol-sparkle sparkle-1">⚡</span>
            </div>
          </div>

          <!-- 商品信息：标题与说明 -->
          <div class="product-body">
            <h3 class="product-card-title">{{ item.name }}</h3>
            <p class="product-card-desc">
              {{ item.description || (isTicket(item) ? '兑换后直接存入您的抽卡背包，可前往称号中心抽取专属荣耀称号。' : '购买后系统将自动秒级转账到账至您的 Linux DO 账户。') }}
            </p>

            <!-- 限购/库存提示条 (若存在限制) -->
            <div v-if="!isTicket(item) && (item.user_daily_limit > 0 || item.total_daily_limit > 0)" class="product-limits-banner">
              <span v-if="item.user_daily_limit > 0">今日个人限额: {{ item.user_remaining ?? item.user_daily_limit }}/{{ item.user_daily_limit }}</span>
              <span v-if="item.total_daily_limit > 0">全站剩余: {{ item.total_remaining ?? item.total_daily_limit }}</span>
            </div>
          </div>

          <!-- 价格区 (大字突出) -->
          <div class="product-price-section">
            <div class="price-original">
              <template v-if="originalStrikedPrice(item)">
                原价 <s>{{ originalStrikedPrice(item)?.toLocaleString() }}</s>
              </template>
            </div>
            <div class="price-figures">
              <span class="price-val">{{ discountedPrice(item).toLocaleString() }}</span>
              <span class="price-unit">积分</span>
            </div>
            <div class="promo-countdown">
              <template v-if="promoLive(item)">距折扣结束 <b>{{ countdownText(item) }}</b></template>
            </div>
          </div>

          <!-- 底部全宽兑换主按钮 (如同设计图) -->
          <div class="product-btn-wrap">
            <button
              class="btn-redeem-action"
              :class="{
                'btn-disabled': buttonState(item).disabled,
                'btn-hundred-gold': isTicket(item) && item.draw_count === 100
              }"
              type="button"
              :disabled="buttonState(item).disabled"
              @click="chooseProduct(item)"
            >
              {{ buttonState(item).text }}
            </button>
          </div>
        </article>
      </div>
    </section>

    <!-- 下方折叠卡片: 兑换发货记录 vs 积分明细 -->
    <section class="shop-records-section">
      <div class="records-header-tabs">
        <button
          type="button"
          class="record-tab-btn"
          :class="{ active: historyTab === 'purchases' }"
          @click="historyTab = 'purchases'"
        >
          📦 兑换发货记录 <span class="tab-badge-num">{{ data?.purchases?.length ?? 0 }}</span>
        </button>
        <button
          type="button"
          class="record-tab-btn"
          :class="{ active: historyTab === 'ledger' }"
          @click="historyTab = 'ledger'"
        >
          🧾 积分变动明细 <span class="tab-badge-num">{{ data?.ledger?.length ?? 0 }}</span>
        </button>
        <button
          class="refresh-icon-btn"
          type="button"
          title="刷新最新数据"
          :disabled="loading"
          @click="refresh"
        >
          {{ loading ? '刷新中…' : '⟳ 刷新流水' }}
        </button>
      </div>

      <!-- TAB 1: 兑换发货记录 -->
      <div v-show="historyTab === 'purchases'" class="table-container-card">
        <ScrollTable :min-rows="3" :max-rows="8" :row-height="56">
          <table class="modern-data-table">
            <thead>
              <tr>
                <th>流水号</th>
                <th>商品详情</th>
                <th>消耗积分</th>
                <th>发货状态</th>
                <th>兑换时间</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!data?.purchases?.length">
                <td colspan="5" class="table-empty">暂无兑换记录，快挑选心仪的抽卡券或额度吧！</td>
              </tr>
              <tr v-for="item in data?.purchases ?? []" :key="item.order_no">
                <td class="font-mono text-dim">{{ item.order_no }}</td>
                <td class="font-semibold">{{ item.product_name }}</td>
                <td class="text-primary font-bold">{{ item.points_cost }} 分</td>
                <td>
                  <span
                    class="status-badge"
                    :style="{
                      color: statusMap[item.status]?.color ?? 'var(--text-muted)',
                      backgroundColor: statusMap[item.status]?.bg ?? 'var(--bg-subtle)'
                    }"
                  >
                    ● {{ statusMap[item.status]?.text ?? item.status }}
                  </span>
                  <button
                    v-if="item.status === 'uncertain'"
                    class="btn-secondary check-order-btn"
                    type="button"
                    :disabled="!!checkingOrder"
                    @click="checkOrder(item)"
                  >
                    {{ checkingOrder === item.order_no ? '查询中…' : '查询发货状态' }}
                  </button>
                </td>
                <td class="text-dim">{{ displayTime(item.created_at) }}</td>
              </tr>
            </tbody>
          </table>
        </ScrollTable>
      </div>

      <!-- TAB 2: 积分变动明细 -->
      <div v-show="historyTab === 'ledger'" class="table-container-card">
        <ScrollTable :min-rows="3" :max-rows="8" :row-height="56">
          <table class="modern-data-table">
            <thead>
              <tr>
                <th>变动类型</th>
                <th>积分变动</th>
                <th>变动后余额</th>
                <th>时间</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!data?.ledger?.length">
                <td colspan="4" class="table-empty">暂无积分变动流水记录。</td>
              </tr>
              <tr v-for="item in data?.ledger ?? []" :key="item.id">
                <td>{{ kindMap[item.kind] || item.kind }}</td>
                <td
                  class="font-bold"
                  :style="{ color: item.delta > 0 ? '#10b981' : '#dc2626' }"
                >
                  {{ item.delta > 0 ? `+${item.delta}` : item.delta }} 分
                </td>
                <td class="font-semibold">{{ Number(item.balance_after).toLocaleString() }} 分</td>
                <td class="text-dim">{{ displayTime(item.created_at) }}</td>
              </tr>
            </tbody>
          </table>
        </ScrollTable>
      </div>
    </section>
  </main>

  <!-- 兑换确认现代化毛玻璃弹窗 -->
  <dialog ref="purchaseDialog" class="modern-dialog-modal">
    <form method="dialog" class="dialog-content-box" @submit.prevent="purchase">
      <div class="dialog-hero-visual">
        <div class="dialog-icon-circle">
          <span>{{ selectedProduct && isTicket(selectedProduct) ? '🎟️' : '🪙' }}</span>
        </div>
        <h2 class="dialog-title">
          {{ selectedProduct && isTicket(selectedProduct) ? '确认购买抽卡券' : '确认兑换 LDC' }}
        </h2>
        <span class="dialog-product-name">{{ selectedProduct?.name }}</span>
      </div>

      <div class="dialog-info-card">
        <div class="info-row">
          <span class="info-label">扣除积分</span>
          <span class="info-val price-text">
            {{ selectedProduct ? discountedPrice(selectedProduct).toLocaleString() : 0 }} 积分
          </span>
        </div>
        <div v-if="selectedProduct && discountedPrice(selectedProduct) < selectedProduct.points_price" class="info-row discount-row">
          <span class="info-label">原价 {{ selectedProduct.points_price.toLocaleString() }}</span>
          <span class="info-val discount-tip">
            {{ promoLive(selectedProduct) ? `限时 ${zhe(selectedProduct.promo_bp)}` : '' }}{{ promoLive(selectedProduct) && hasDiscount ? ' + ' : '' }}{{ hasDiscount ? '称号折扣' : '' }}
          </span>
        </div>
        <div class="info-row">
          <span class="info-label">获得内容</span>
          <span class="info-val highlight-val">
            {{ selectedProduct && isTicket(selectedProduct) ? `${selectedProduct.draw_count ?? 0} 次抽卡券` : `${selectedProduct?.ldc_amount} LDC` }}
          </span>
        </div>
      </div>

      <p v-if="!selectedProduct || !isTicket(selectedProduct)" class="dialog-hint-text">
        💡 兑换成功后，系统将通过官方 Credit 接口秒级转账至你的 Linux DO 账户。
      </p>

      <div class="dialog-actions-row">
        <button class="btn-cancel" type="button" @click="purchaseDialog?.close()">
          取消
        </button>
        <button class="btn-confirm" type="submit" :disabled="purchasing">
          {{ purchasing ? '正在处理…' : '立即兑换' }}
        </button>
      </div>
    </form>
  </dialog>

  <!-- 消息轻提示 -->
  <div v-if="notice" class="toast-notice" role="status" aria-live="polite">
    {{ notice }}
  </div>
</template>

<style scoped>
.shop-page-wrapper {
  max-width: 1320px;
  margin: 0 auto;
  padding: 24px 24px 80px;
  display: flex;
  flex-direction: column;
  gap: 28px;
}

/* 顶部商城标题与吸顶资产状态栏 */
.shop-hero-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  flex-wrap: wrap;
  padding: 20px 28px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
}

.shop-hero-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.shop-badge-icon {
  width: 48px;
  height: 48px;
  border-radius: var(--radius-sm);
  background: var(--primary-light);
  border: 1px solid var(--primary-border);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 4px 14px rgba(13, 148, 136, 0.15);
}

.shop-badge-icon .lotus-svg {
  width: 32px;
  height: 32px;
}

.shop-hero-headings {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.shop-title {
  font-size: 24px;
  font-weight: 800;
  color: var(--text-main);
  margin: 0;
  letter-spacing: -0.02em;
}

.shop-subtitle {
  font-size: 13px;
  color: var(--text-muted);
  margin: 0;
}

/* 搜索框 */
.shop-search-box {
  position: relative;
  display: flex;
  align-items: center;
  min-width: 240px;
  max-width: 320px;
  flex: 1;
}

.shop-search-box .search-icon {
  position: absolute;
  left: 14px;
  font-size: 14px;
  pointer-events: none;
  opacity: 0.6;
}

.shop-search-input {
  width: 100%;
  padding: 9px 36px 9px 38px;
  border-radius: var(--radius-pill);
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  font-size: 13px;
  color: var(--text-main);
  outline: none;
  transition: all 0.2s ease;
}

.shop-search-input:focus {
  border-color: var(--primary);
  background: var(--bg-card);
  box-shadow: 0 0 0 3px rgba(13, 148, 136, 0.14);
}

.search-clear-btn {
  position: absolute;
  right: 12px;
  font-size: 12px;
  color: var(--text-dim);
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 50%;
}

.search-clear-btn:hover {
  color: var(--text-main);
}

/* 右侧三大指标胶囊 */
.shop-metrics-pills {
  display: flex;
  align-items: center;
  gap: 14px;
}

.metric-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 16px;
  border-radius: var(--radius);
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  min-width: 120px;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.metric-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-sm);
}

.metric-icon-wrap {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 17px;
  flex-shrink: 0;
}

.points-icon {
  background: rgba(245, 158, 11, 0.14);
}

.privilege-icon {
  background: rgba(139, 92, 246, 0.14);
}

.ldc-icon {
  background: rgba(16, 185, 129, 0.14);
}

.metric-info {
  display: flex;
  flex-direction: column;
}

.metric-info .metric-label {
  font-size: 11px;
  color: var(--text-muted);
  font-weight: 500;
}

.metric-info .metric-val {
  font-size: 16px;
  font-weight: 800;
  color: var(--text-main);
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}

.metric-points .metric-val {
  color: #d97706;
}

[data-theme="dark"] .metric-points .metric-val {
  color: #fbbf24;
}

.metric-privilege.active {
  background: var(--amber-light);
  border-color: var(--amber-border);
}

.metric-privilege.active .metric-val {
  color: #b45309;
}

[data-theme="dark"] .metric-privilege.active .metric-val {
  color: #fbbf24;
}

.metric-ldc .metric-val {
  color: #10b981;
}

/* 分类标签栏 */
.shop-category-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.category-pills {
  display: flex;
  align-items: center;
  gap: 8px;
}

.category-pill {
  padding: 7px 18px;
  border-radius: var(--radius-pill);
  font-size: 13px;
  font-weight: 600;
  background: var(--bg-card);
  border: 1px solid var(--border);
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.2s ease;
}

.category-pill:hover {
  color: var(--text-main);
  border-color: var(--primary-border);
}

.category-pill.active {
  background: var(--primary);
  color: #ffffff;
  border-color: var(--primary);
  box-shadow: 0 4px 12px rgba(13, 148, 136, 0.28);
}

.donate-quick-link {
  font-size: 13px;
  font-weight: 600;
  color: var(--primary);
  text-decoration: none;
  padding: 6px 14px;
  border-radius: var(--radius-pill);
  background: var(--primary-light);
  border: 1px solid var(--primary-border);
  transition: all 0.2s ease;
}

.donate-quick-link:hover {
  background: var(--primary);
  color: #ffffff;
}

/* 现代 4 列商品展示网格 (对齐设计图) */
.modern-products-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 22px;
}

.modern-product-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 20px;
  box-shadow: var(--shadow-card);
  display: flex;
  flex-direction: column;
  position: relative;
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

.modern-product-card:hover {
  transform: translateY(-5px);
  border-color: var(--primary-border);
  box-shadow: 0 14px 32px -4px rgba(13, 148, 136, 0.16);
}

/* 顶部标签行 */
.product-top-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.card-badge {
  font-size: 11px;
  font-weight: 700;
  padding: 3px 9px;
  border-radius: var(--radius-pill);
}

.badge-hot {
  background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
  color: #ffffff;
  box-shadow: 0 2px 6px rgba(239, 68, 68, 0.3);
}

.badge-discount {
  background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
  color: #ffffff;
  box-shadow: 0 2px 6px rgba(245, 158, 11, 0.3);
}

.badge-ticket {
  background: rgba(99, 102, 241, 0.12);
  color: #6366f1;
}

.badge-ldc {
  background: var(--emerald-light);
  color: var(--emerald);
}

.spec-highlight {
  font-size: 12px;
  font-weight: 800;
  color: var(--primary);
  font-variant-numeric: tabular-nums;
}

/* 居中核心卡槽插画展示区 (Art Canvas) */
.product-art-canvas {
  width: 100%;
  height: 130px;
  border-radius: var(--radius);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 16px;
  position: relative;
  overflow: hidden;
  transition: all 0.3s ease;
}

.modern-product-card:hover .product-art-canvas {
  transform: scale(1.02);
}

.art-gold {
  background: radial-gradient(circle at 50% 50%, rgba(251, 191, 36, 0.22) 0%, rgba(254, 243, 199, 0.4) 60%, var(--bg-subtle) 100%);
  border: 1px solid rgba(245, 158, 11, 0.2);
}

[data-theme="dark"] .art-gold {
  background: radial-gradient(circle at 50% 50%, rgba(245, 158, 11, 0.18) 0%, rgba(30, 27, 75, 0.4) 100%);
  border-color: rgba(245, 158, 11, 0.3);
}

.art-purple {
  background: radial-gradient(circle at 50% 50%, rgba(139, 92, 246, 0.18) 0%, rgba(237, 233, 254, 0.4) 60%, var(--bg-subtle) 100%);
  border: 1px solid rgba(139, 92, 246, 0.2);
}

[data-theme="dark"] .art-purple {
  background: radial-gradient(circle at 50% 50%, rgba(139, 92, 246, 0.18) 0%, rgba(30, 27, 75, 0.4) 100%);
  border-color: rgba(139, 92, 246, 0.3);
}

.art-teal {
  background: radial-gradient(circle at 50% 50%, rgba(20, 184, 166, 0.18) 0%, rgba(204, 251, 241, 0.4) 60%, var(--bg-subtle) 100%);
  border: 1px solid rgba(20, 184, 166, 0.2);
}

[data-theme="dark"] .art-teal {
  background: radial-gradient(circle at 50% 50%, rgba(20, 184, 166, 0.15) 0%, rgba(15, 23, 42, 0.4) 100%);
  border-color: rgba(20, 184, 166, 0.25);
}

.art-coin {
  background: radial-gradient(circle at 50% 50%, rgba(16, 185, 129, 0.18) 0%, rgba(209, 250, 229, 0.4) 60%, var(--bg-subtle) 100%);
  border: 1px solid rgba(16, 185, 129, 0.2);
}

.art-graphic-box {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
}

.art-symbol-hero {
  font-size: 52px;
  filter: drop-shadow(0 6px 14px rgba(0, 0, 0, 0.1));
  transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

.modern-product-card:hover .art-symbol-hero {
  transform: scale(1.1) rotate(-3deg);
}

.art-symbol-sparkle {
  position: absolute;
  font-size: 18px;
  filter: drop-shadow(0 2px 6px rgba(0, 0, 0, 0.15));
}

.sparkle-1 {
  top: -8px;
  right: -14px;
  animation: floatSlow 3s ease-in-out infinite alternate;
}

.sparkle-2 {
  bottom: -6px;
  left: -12px;
  font-size: 16px;
}

@keyframes floatSlow {
  0% { transform: translateY(0); }
  100% { transform: translateY(-4px); }
}

/* 标题与描述排版 */
.product-body {
  display: flex;
  flex-direction: column;
  flex: 1;
}

.product-card-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-main);
  margin: 0 0 6px;
  line-height: 1.3;
}

.product-card-desc {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.5;
  margin: 0 0 12px;
  min-height: 36px;
}

.product-limits-banner {
  font-size: 11px;
  color: var(--text-dim);
  background: var(--bg-subtle);
  padding: 4px 8px;
  border-radius: var(--radius-xs);
  margin-bottom: 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

/* 价格区 (大字突出) */
.product-price-section {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  margin-bottom: 14px;
}

/* 原价行与倒计时行始终占位，保证各卡片的主价格在同一水平线上 */
.price-original {
  min-height: 16px;
  font-size: 12px;
  line-height: 16px;
  color: var(--text-dim);
  font-variant-numeric: tabular-nums;
}

.price-original s {
  text-decoration: line-through;
}

.price-figures {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.price-val {
  font-size: 22px;
  font-weight: 900;
  color: var(--primary);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
}

.price-unit {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
}

.price-strikethrough {
  font-size: 12px;
  color: var(--text-dim);
  text-decoration: line-through;
  margin-left: 4px;
}

/* 底部全宽主按钮 (对齐设计图) */
.product-btn-wrap {
  width: 100%;
}

.btn-redeem-action {
  width: 100%;
  padding: 10px 0;
  font-size: 14px;
  font-weight: 700;
  border-radius: var(--radius-pill);
  background: linear-gradient(135deg, #0d9488 0%, #10b981 100%);
  color: #ffffff;
  border: none;
  cursor: pointer;
  box-shadow: 0 4px 14px rgba(13, 148, 136, 0.28);
  transition: all 0.2s ease;
  text-align: center;
}

.btn-redeem-action:hover:not(:disabled) {
  opacity: 0.95;
  transform: translateY(-1px);
  box-shadow: 0 6px 18px rgba(13, 148, 136, 0.36);
}

.btn-redeem-action:active:not(:disabled) {
  transform: scale(0.98);
}

.btn-redeem-action.btn-disabled,
.btn-redeem-action:disabled {
  background: var(--bg-subtle) !important;
  color: var(--text-dim) !important;
  border: 1px solid var(--border) !important;
  box-shadow: none !important;
  cursor: not-allowed;
  transform: none !important;
}

.btn-redeem-action.btn-hundred-gold:not(:disabled) {
  background: linear-gradient(135deg, #d97706 0%, #f59e0b 100%);
  box-shadow: 0 4px 14px rgba(245, 158, 11, 0.32);
}

.btn-redeem-action.btn-hundred-gold:hover:not(:disabled) {
  box-shadow: 0 6px 18px rgba(245, 158, 11, 0.42);
}

/* 空状态 */
.products-empty-card {
  padding: 60px 20px;
  text-align: center;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  color: var(--text-muted);
  grid-column: 1 / -1;
}

.empty-emoji {
  font-size: 44px;
  display: block;
  margin-bottom: 10px;
}

/* 下方记录面板 */
.shop-records-section {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 24px;
  box-shadow: var(--shadow-card);
}

.records-header-tabs {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}

.record-tab-btn {
  padding: 8px 18px;
  font-size: 13px;
  font-weight: 600;
  border-radius: var(--radius-pill);
  background: var(--bg-subtle);
  color: var(--text-muted);
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
  gap: 6px;
}

.record-tab-btn.active {
  background: var(--primary-light);
  color: var(--primary);
  border-color: var(--primary-border);
}

.tab-badge-num {
  font-size: 11px;
  font-weight: 700;
  background: var(--bg-card);
  padding: 1px 6px;
  border-radius: var(--radius-pill);
}

.refresh-icon-btn {
  margin-left: auto;
  font-size: 12px;
  color: var(--text-muted);
  cursor: pointer;
  padding: 6px 12px;
  border-radius: var(--radius-sm);
  background: var(--bg-subtle);
  transition: all 0.2s ease;
}

.refresh-icon-btn:hover {
  color: var(--primary);
  background: var(--primary-light);
}

.table-container-card {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}

.table-scroll {
  overflow-x: auto;
}

.modern-data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.modern-data-table th {
  text-align: left;
  padding: 12px 16px;
  font-size: 12px;
  color: var(--text-muted);
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--border);
}

.modern-data-table td {
  padding: 14px 16px;
  border-bottom: 1px solid var(--border-light);
  color: var(--text-main);
}

.modern-data-table tr:last-child td {
  border-bottom: none;
}

.modern-data-table tr:hover td {
  background: var(--primary-light);
}

.table-empty {
  text-align: center;
  padding: 36px !important;
  color: var(--text-dim);
}

.check-order-btn {
  margin-left: 8px;
  padding: 3px 10px;
  font-size: 12px;
}

.promo-countdown {
  min-height: 16px;
  font-size: 12px;
  line-height: 16px;
  color: #d97706;
  font-variant-numeric: tabular-nums;
}

.status-badge {
  display: inline-block;
  font-size: 11px;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: var(--radius-pill);
}

/* 现代化居中弹窗 */
.modern-dialog-modal {
  border: none;
  background: transparent;
  padding: 0;
  border-radius: 20px;
  box-shadow: 0 20px 48px rgba(0, 0, 0, 0.25);
  max-width: 440px;
  width: 90vw;
}

.modern-dialog-modal::backdrop {
  background: rgba(15, 23, 42, 0.55);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.dialog-content-box {
  background: var(--bg-card);
  padding: 32px 28px 24px;
  border-radius: 20px;
  border: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.dialog-hero-visual {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 8px;
}

.dialog-icon-circle {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: var(--primary-light);
  border: 2px solid var(--primary-border);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 32px;
  box-shadow: 0 8px 24px rgba(13, 148, 136, 0.2);
}

.dialog-title {
  font-size: 20px;
  font-weight: 800;
  color: var(--text-main);
  margin: 4px 0 0;
}

.dialog-product-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--primary);
}

.dialog-info-card {
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 14px 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.info-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
}

.info-label {
  color: var(--text-muted);
}

.info-val {
  font-weight: 700;
  color: var(--text-main);
}

.price-text {
  color: var(--primary);
  font-size: 15px;
}

.discount-tip {
  color: #d97706;
  font-size: 12px;
}

.highlight-val {
  color: var(--emerald);
}

.dialog-hint-text {
  font-size: 12px;
  color: var(--text-dim);
  text-align: center;
  margin: 0;
  line-height: 1.5;
}

.dialog-actions-row {
  display: flex;
  gap: 12px;
  margin-top: 6px;
}

.btn-cancel {
  flex: 1;
  padding: 10px 0;
  font-size: 14px;
  font-weight: 600;
  border-radius: var(--radius-pill);
  background: var(--bg-subtle);
  color: var(--text-main);
  border: 1px solid var(--border);
  cursor: pointer;
}

.btn-confirm {
  flex: 1.6;
  padding: 10px 0;
  font-size: 14px;
  font-weight: 700;
  border-radius: var(--radius-pill);
  background: linear-gradient(135deg, #0d9488 0%, #10b981 100%);
  color: #ffffff;
  border: none;
  cursor: pointer;
  box-shadow: 0 4px 14px rgba(13, 148, 136, 0.28);
}

.btn-confirm:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* 消息 Toast */
.toast-notice {
  position: fixed;
  bottom: 30px;
  left: 50%;
  transform: translateX(-50%);
  background: var(--text-main);
  color: var(--bg);
  padding: 10px 22px;
  border-radius: var(--radius-pill);
  font-size: 13px;
  font-weight: 600;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
  z-index: 10000;
  animation: toastFadeIn 0.25s ease-out;
}

@keyframes toastFadeIn {
  from { opacity: 0; transform: translate(-50%, 10px); }
  to { opacity: 1; transform: translate(-50%, 0); }
}

/* 响应式断点 */
@media (max-width: 1080px) {
  .modern-products-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 820px) {
  .modern-products-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .shop-hero-header {
    flex-direction: column;
    align-items: stretch;
  }
  .shop-search-box {
    max-width: 100%;
  }
  .shop-metrics-pills {
    justify-content: space-between;
  }
  .metric-card {
    min-width: 0;
    flex: 1;
    padding: 8px 10px;
  }
}

@media (max-width: 520px) {
  .modern-products-grid {
    grid-template-columns: 1fr;
  }
  .shop-category-bar {
    flex-direction: column;
    align-items: stretch;
  }
  .category-pills {
    overflow-x: auto;
    padding-bottom: 4px;
  }
}
</style>
