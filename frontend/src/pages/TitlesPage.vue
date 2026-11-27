<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ApiError, loginUrl, titles as titlesApi, type DrawResultItem, type Rarity, type TicketType, type TitleData, type TitleItem } from '../api'
import { useBodyAttributes } from '../composables/useBodyAttributes'
import { useIdentity } from '../composables/useIdentity'
import { playFeedbackSound, triggerHaptic } from '../composables/usePreferences'

interface DisplayCard {
  id: string
  title_id: string
  rarity: Rarity
  is_new: boolean
  name: string
  description?: string
  icon?: string
}

useBodyAttributes({})
const identity = useIdentity()
const data = ref<TitleData | null>(null)
const loading = ref(false)
const busy = ref(false)
const notice = ref('')
const results = ref<DrawResultItem[]>([])
const activeTab = ref<'draw' | 'owned' | 'gallery' | 'smelt'>('draw')
const galleryRarity = ref<'ALL' | Rarity>('ALL')
let noticeTimer: number | undefined

// 抽卡仪式与动画状态
const showGachaOverlay = ref(false)
const gachaStage = ref<'idle' | 'spinning' | 'revealing' | 'sorting' | 'settled'>('idle')
const spinningPullCount = ref<number>(1)
const displayCards = ref<DisplayCard[]>([])
const isAutoSorting = ref(false)
let spinFastForwardFn: (() => void) | null = null
let autoSortTimer: number | undefined

const rarityOrder: Rarity[] = ['UR', 'SSR', 'SR', 'R', 'N']
const rarityMeta: Record<Rarity, { label: string; color: string; bg: string; glow: string }> = {
  UR: { label: '至尊', color: '#b45309', bg: '#fef3c7', glow: 'rgba(245, 158, 11, 0.4)' },
  SSR: { label: '传说', color: '#7c3aed', bg: '#ede9fe', glow: 'rgba(124, 58, 237, 0.35)' },
  SR: { label: '史诗', color: '#2563eb', bg: '#dbeafe', glow: 'rgba(37, 99, 235, 0.3)' },
  R: { label: '稀有', color: '#059669', bg: '#d1fae5', glow: 'rgba(5, 150, 105, 0.25)' },
  N: { label: '普通', color: '#6b7280', bg: '#f3f4f6', glow: 'rgba(107, 114, 128, 0.15)' },
}

const ticketMeta: Array<{ type: TicketType; label: string; countText: string; icon: string }> = [
  { type: 'single', label: '单抽券', countText: '1 抽', icon: '🎫' },
  { type: 'ten', label: '十连券', countText: '10 抽', icon: '🎟️' },
  { type: 'hundred', label: '百连券', countText: '100 抽', icon: '✨' },
]

const equippedItem = computed(() => {
  if (!data.value?.equipped_title_id) return null
  return data.value.collection.find(item => item.id === data.value?.equipped_title_id) || null
})

const ownedTitles = computed(() => {
  return (data.value?.collection ?? []).filter(item => item.owned)
})

const filteredGallery = computed(() => {
  const list = data.value?.collection ?? []
  if (galleryRarity.value === 'ALL') return list
  return list.filter(item => item.rarity === galleryRarity.value)
})

// 连抽卡牌转圈阵列计算 (1抽 1张，10连抽 10张单环，100连抽 100张四层同心环)
const spinningCards = computed(() => {
  const count = spinningPullCount.value
  if (count === 1) {
    return [{ id: 0, x: 0, y: 0, ring: 0, rotate: 0 }]
  }
  if (count === 10) {
    const radius = 175
    return Array.from({ length: 10 }, (_, i) => {
      const deg = (i * 360) / 10
      const rad = (deg * Math.PI) / 180
      return {
        id: i,
        x: Math.round(Math.cos(rad) * radius),
        y: Math.round(Math.sin(rad) * radius),
        ring: 1,
        rotate: deg + 90,
      }
    })
  }
  // 100 张卡牌：14 + 22 + 30 + 34 = 100 张
  const ringDefs = [
    { count: 14, radius: 90 },
    { count: 22, radius: 150 },
    { count: 30, radius: 215 },
    { count: 34, radius: 280 },
  ]
  const list: Array<{ id: number; x: number; y: number; ring: number; rotate: number }> = []
  let id = 0
  ringDefs.forEach((ringDef, rIdx) => {
    for (let i = 0; i < ringDef.count; i++) {
      const deg = (i * 360) / ringDef.count
      const rad = (deg * Math.PI) / 180
      list.push({
        id: id++,
        x: Math.round(Math.cos(rad) * ringDef.radius),
        y: Math.round(Math.sin(rad) * ringDef.radius),
        ring: rIdx + 1,
        rotate: deg + 90,
      })
    }
  })
  return list
})

const vortexRings = computed(() => {
  const rings: Array<typeof spinningCards.value> = [[], [], [], []]
  for (const c of spinningCards.value) rings[c.ring - 1]?.push(c)
  return rings
})

const raritySummary = computed(() => {
  const counts: Record<Rarity, number> = { UR: 0, SSR: 0, SR: 0, R: 0, N: 0 }
  for (const c of displayCards.value) {
    if (counts[c.rarity] !== undefined) {
      counts[c.rarity]++
    }
  }
  return counts
})

function getCardIcon(card: DisplayCard): string {
  if (card.icon && card.icon.length <= 4 && !card.icon.includes('/')) {
    return card.icon
  }
  switch (card.rarity) {
    case 'UR': return '👑'
    case 'SSR': return '💎'
    case 'SR': return '🔮'
    case 'R': return '🌿'
    case 'N': return '🪷'
    default: return '🪷'
  }
}

function notify(message: string): void {
  notice.value = message
  window.clearTimeout(noticeTimer)
  noticeTimer = window.setTimeout(() => { notice.value = '' }, 4500)
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function newRequestId(): string {
  return crypto.randomUUID()
}

async function refresh(): Promise<void> {
  if (loading.value) return
  loading.value = true
  try {
    data.value = await titlesApi.get({ headers: { 'Cache-Control': 'no-cache' } })
    if (data.value.wallet) {
      identity.setWallet(data.value.wallet)
    }
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      window.location.assign(loginUrl('/titles'))
      return
    }
    notify(`无法读取称号数据：${messageOf(error)}`)
  } finally {
    loading.value = false
  }
}

function closeGacha(): void {
  showGachaOverlay.value = false
  gachaStage.value = 'idle'
  displayCards.value = []
  results.value = []
  isAutoSorting.value = false
  if (spinFastForwardFn) {
    spinFastForwardFn()
    spinFastForwardFn = null
  }
  if (autoSortTimer) {
    clearTimeout(autoSortTimer)
    autoSortTimer = undefined
  }
}

function fastForwardAnimation(): void {
  if (spinFastForwardFn) {
    spinFastForwardFn()
    spinFastForwardFn = null
  }
}

function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'Escape' && showGachaOverlay.value) {
    closeGacha()
  }
}

async function draw(type: TicketType): Promise<void> {
  if (busy.value) return
  const owned = data.value?.tickets?.[type] ?? 0
  const meta = ticketMeta.find((item) => item.type === type)!
  if (owned < 1) {
    notify(`没有${meta.label}了，可前往商店购买抽卡券！`)
    return
  }

  const count = type === 'single' ? 1 : type === 'ten' ? 10 : 100
  spinningPullCount.value = count
  gachaStage.value = 'spinning'
  showGachaOverlay.value = true
  displayCards.value = []
  isAutoSorting.value = false
  busy.value = true

  playFeedbackSound('step')
  triggerHaptic(40)

  const minDuration = count === 1 ? 1200 : count === 10 ? 1800 : 2200
  let fastForwarded = false
  const delayPromise = new Promise<void>((resolve) => {
    const timer = setTimeout(() => resolve(), minDuration)
    spinFastForwardFn = () => {
      fastForwarded = true
      clearTimeout(timer)
      resolve()
    }
  })

  try {
    const drawPromise = titlesApi.draw({ ticket_type: type, request_id: newRequestId() })
    const [result] = await Promise.all([drawPromise, delayPromise])
    spinFastForwardFn = null

    if (!showGachaOverlay.value) {
      await refresh()
      return
    }

    const rawResults = result.results
    const enriched: DisplayCard[] = rawResults.map((card, idx) => {
      const match = data.value?.collection?.find((c) => String(c.id) === String(card.title_id))
      return {
        ...card,
        id: `draw-${card.title_id}-${idx}-${Math.random().toString(36).slice(2, 6)}`,
        name: card.name || match?.name || '神秘称号',
        icon: card.icon || match?.icon || '',
        description: card.description || match?.description || '',
      }
    })

    displayCards.value = [...enriched]
    results.value = result.results
    gachaStage.value = 'revealing'

    const top = rawResults.reduce(
      (best, item) => (rarityOrder.indexOf(item.rarity) < rarityOrder.indexOf(best) ? item.rarity : best),
      'N' as Rarity
    )
    playFeedbackSound('complete')
    triggerHaptic([30, 60, 40])
    notify(`🎴 抽卡完成！共 ${result.batch.count} 抽，最高稀有度：${rarityMeta[top].label}`)

    refresh()

    const sortDelay = fastForwarded ? 300 : 700
    autoSortTimer = window.setTimeout(() => {
      if (!showGachaOverlay.value) return
      isAutoSorting.value = true
      gachaStage.value = 'sorting'
      playFeedbackSound('step')
      triggerHaptic(25)

      displayCards.value = [...displayCards.value].sort((a, b) => {
        const orderA = rarityOrder.indexOf(a.rarity)
        const orderB = rarityOrder.indexOf(b.rarity)
        if (orderA !== orderB) return orderA - orderB
        return a.name.localeCompare(b.name, 'zh-CN')
      })

      autoSortTimer = window.setTimeout(() => {
        if (!showGachaOverlay.value) return
        isAutoSorting.value = false
        gachaStage.value = 'settled'
      }, 750)
    }, sortDelay)
  } catch (error) {
    showGachaOverlay.value = false
    gachaStage.value = 'idle'
    notify(`抽卡失败：${messageOf(error)}`)
  } finally {
    busy.value = false
  }
}

async function equip(item: TitleItem): Promise<void> {
  if (busy.value || !item.owned) return
  busy.value = true
  try {
    const isCurrent = data.value?.equipped_title_id === item.id
    await titlesApi.equip({ title_id: isCurrent ? null : item.id })
    playFeedbackSound('step')
    triggerHaptic(30)
    notify(isCurrent ? '已卸下称号' : `已装备称号「${item.name}」`)
    await refresh()
  } catch (error) {
    notify(`操作失败：${messageOf(error)}`)
  } finally {
    busy.value = false
  }
}

async function quickBuyTicket(productId: string): Promise<void> {
  if (busy.value) return
  busy.value = true
  try {
    await titlesApi.buyTicket({ product_id: productId, request_id: newRequestId() })
    notify('🎟️ 购买抽卡券成功！已存入背包。')
    playFeedbackSound('complete')
    await refresh()
  } catch (error) {
    notify(`购买失败：${messageOf(error)}`)
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  window.addEventListener('keydown', onKeydown)
  if (await identity.requireLogin('/titles')) {
    await refresh()
  }
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  if (autoSortTimer) clearTimeout(autoSortTimer)
})
</script>

<template>
  <main class="titles-page-wrapper">
    <!-- 顶部称号中心横幅与背包券数胶囊 -->
    <header class="titles-hero-header">
      <div class="header-brand-info">
        <div class="titles-badge-icon">
          <svg class="lotus-svg" viewBox="0 0 32 32" fill="none">
            <path d="M16 4C16 4 11 12 11 18C11 21.3137 13.2386 24 16 24C18.7614 24 21 21.3137 21 18C21 12 16 4 16 4Z" fill="url(#t-lotus-grad)" />
            <path d="M9 13C9 13 4 18 5 23C5.5 25.5 8 26.5 11 25.5C13 24.8 14.5 23 15 21C13 20 10.5 17.5 9 13Z" fill="url(#t-lotus-grad)" opacity="0.85" />
            <path d="M23 13C23 13 28 18 27 23C26.5 25.5 24 26.5 21 25.5C19 24.8 17.5 23 17 21C19 20 21.5 17.5 23 13Z" fill="url(#t-lotus-grad)" opacity="0.85" />
            <defs>
              <linearGradient id="t-lotus-grad" x1="16" y1="4" x2="16" y2="24" gradientUnits="userSpaceOnUse">
                <stop stop-color="#2dd4bf" />
                <stop offset="1" stop-color="#0d9488" />
              </linearGradient>
            </defs>
          </svg>
        </div>
        <div>
          <h1 class="titles-title">称号中心</h1>
          <p class="titles-subtitle">收集专属称号 · 展示你的坚持与成长 · 激活商城折扣特权</p>
        </div>
      </div>

      <!-- 右侧三大抽卡券实时背包 -->
      <div class="tickets-inventory-pills">
        <div class="ticket-pill">
          <span class="ticket-icon">🎫</span>
          <span class="ticket-name">单抽券</span>
          <span class="ticket-val">{{ data?.tickets?.single ?? 0 }}</span>
        </div>
        <div class="ticket-pill highlight-ten">
          <span class="ticket-icon">🎟️</span>
          <span class="ticket-name">十连券</span>
          <span class="ticket-val">{{ data?.tickets?.ten ?? 0 }}</span>
        </div>
        <div class="ticket-pill highlight-hundred">
          <span class="ticket-icon">✨</span>
          <span class="ticket-name">百连券</span>
          <span class="ticket-val">{{ data?.tickets?.hundred ?? 0 }}</span>
        </div>
      </div>
    </header>

    <!-- Master-Detail 分栏 (左侧导航菜单 + 右侧抽卡舞台/展厅) -->
    <section class="titles-master-detail-grid">
      <!-- 左侧菜单侧边栏 -->
      <aside class="titles-menu-sidebar">
        <div class="titles-nav-list">
          <button
            type="button"
            class="title-nav-item"
            :class="{ active: activeTab === 'draw' }"
            @click="activeTab = 'draw'"
          >
            <span class="item-icon">🎰</span>
            <span class="item-text">抽取称号</span>
            <span v-if="activeTab === 'draw'" class="active-arrow">➔</span>
          </button>
          <button
            type="button"
            class="title-nav-item"
            :class="{ active: activeTab === 'owned' }"
            @click="activeTab = 'owned'"
          >
            <span class="item-icon">👑</span>
            <span class="item-text">我的称号 ({{ ownedTitles.length }})</span>
            <span v-if="activeTab === 'owned'" class="active-arrow">➔</span>
          </button>
          <button
            type="button"
            class="title-nav-item"
            :class="{ active: activeTab === 'gallery' }"
            @click="activeTab = 'gallery'"
          >
            <span class="item-icon">📖</span>
            <span class="item-text">称号图鉴</span>
            <span v-if="activeTab === 'gallery'" class="active-arrow">➔</span>
          </button>
        </div>

        <!-- 快速购券卡片 -->
        <div class="quick-shop-card">
          <div class="quick-shop-header">
            <span>🎟️ 抽卡券快捷兑换</span>
            <span class="wallet-balance-text">余额: {{ Number(data?.wallet?.balance ?? 0).toLocaleString() }} 分</span>
          </div>
          <div class="quick-products-list">
            <div
              v-for="p in data?.ticket_products ?? []"
              :key="p.id"
              class="quick-product-row"
            >
              <span class="p-name">{{ p.name }}</span>
              <span class="p-price">
                <s v-if="(p.price_now ?? p.points_price) < p.points_price" class="p-price-old">{{ p.points_price }}</s>
                <span><b class="p-price-now">{{ (p.price_now ?? p.points_price).toLocaleString() }}</b> 积分</span>
              </span>
              <button
                class="btn-secondary btn-buy-ticket"
                type="button"
                :disabled="busy || Number(data?.wallet?.balance ?? 0) < (p.price_now ?? p.points_price)"
                @click="quickBuyTicket(p.id)"
              >
                购买
              </button>
            </div>
          </div>
        </div>
      </aside>

      <!-- 右侧主展示舞台 -->
      <div class="titles-content-stage">
        <!-- TAB 1: 3D 抽卡主舞台 (Screen 4 核心) -->
        <div v-if="activeTab === 'draw'" class="draw-arena-card">
          <!-- 3D 发光神话卡牌展示 -->
          <div class="gacha-3d-cards-row">
            <div class="gacha-card-visual card-left">
              <div class="card-inner-graphic">
                <span class="card-lotus-emblem">🪷</span>
                <span class="card-badge-tag">R</span>
              </div>
            </div>
            <div class="gacha-card-visual card-center">
              <div class="card-inner-graphic">
                <span class="card-lotus-emblem">👑</span>
                <span class="card-badge-tag">UR</span>
              </div>
              <div class="golden-rays-aura" />
            </div>
            <div class="gacha-card-visual card-right">
              <div class="card-inner-graphic">
                <span class="card-lotus-emblem">🪷</span>
                <span class="card-badge-tag">SR</span>
              </div>
            </div>
          </div>

          <!-- 右侧抽卡控制台 -->
          <div class="draw-control-panel">
            <h2 class="draw-title">称号抽取</h2>
            <p class="draw-subtitle">集齐至尊 UR 称号，解锁全店商品 95 折特权与炫彩专属头像标识！</p>

            <div class="draw-buttons-cluster">
              <button
                class="btn-draw-single"
                type="button"
                :disabled="busy"
                @click="draw('single')"
              >
                <span class="draw-btn-icon">🎫</span>
                <span class="draw-btn-text">单抽 × 1</span>
                <span class="draw-btn-sub">剩余 {{ data?.tickets?.single ?? 0 }} 张</span>
              </button>

              <button
                class="btn-draw-ten"
                type="button"
                :disabled="busy"
                @click="draw('ten')"
              >
                <span class="draw-btn-icon">🎟️</span>
                <span class="draw-btn-text">十连 × 10</span>
                <span class="draw-btn-sub">保底必出 SR · 剩余 {{ data?.tickets?.ten ?? 0 }} 张</span>
              </button>

              <button
                class="btn-draw-hundred"
                type="button"
                :disabled="busy"
                @click="draw('hundred')"
              >
                <span class="draw-btn-icon">✨</span>
                <span class="draw-btn-text">百连 × 100</span>
                <span class="draw-btn-sub">保底必出 SSR · 剩余 {{ data?.tickets?.hundred ?? 0 }} 张</span>
              </button>
            </div>
          </div>
        </div>

        <!-- TAB 2: 我的称号 -->
        <div v-else-if="activeTab === 'owned'" class="owned-titles-section">
          <!-- 当前佩戴卡片 -->
          <div class="equipped-showcase-box">
            <div class="equipped-header">
              <span class="equipped-label">当前装配称号</span>
              <button
                v-if="equippedItem"
                class="btn-secondary btn-sm"
                type="button"
                @click="equip(equippedItem)"
              >
                卸下当前称号
              </button>
            </div>
            <div v-if="equippedItem" class="equipped-card-content">
              <span class="equipped-crown">👑</span>
              <div>
                <h3 class="equipped-title-name">{{ equippedItem.name }}</h3>
                <p class="equipped-title-desc">{{ equippedItem.description }}</p>
                <span class="rarity-badge" :style="{ color: rarityMeta[equippedItem.rarity].color, background: rarityMeta[equippedItem.rarity].bg }">
                  {{ rarityMeta[equippedItem.rarity].label }} · {{ equippedItem.rarity }}
                </span>
              </div>
            </div>
            <div v-else class="equipped-empty">
              <span>暂未装配称号，请在下方点击「装备」佩戴你喜欢的称号。</span>
            </div>
          </div>

          <!-- 已拥有的称号网格 -->
          <div class="owned-grid">
            <div v-if="!ownedTitles.length" class="empty-owned-hint">
              <span>背包空空如也，快去「抽取称号」试试手气吧！</span>
            </div>
            <div
              v-for="item in ownedTitles"
              :key="item.id"
              class="owned-card"
              :class="{ 'is-equipped': data?.equipped_title_id === item.id }"
            >
              <div class="owned-card-top">
                <span class="rarity-badge" :style="{ color: rarityMeta[item.rarity].color, background: rarityMeta[item.rarity].bg }">
                  {{ item.rarity }}
                </span>
                <span class="copies-tag">拥有 {{ item.copies }} 张</span>
              </div>
              <h4 class="item-name">{{ item.name }}</h4>
              <p class="item-desc">{{ item.description }}</p>
              <button
                class="btn-primary btn-sm btn-equip"
                type="button"
                :disabled="busy"
                @click="equip(item)"
              >
                {{ data?.equipped_title_id === item.id ? '已装备 ✓' : '立即佩戴' }}
              </button>
            </div>
          </div>
        </div>

        <!-- TAB 3: 称号图鉴陈列室 -->
        <div v-else-if="activeTab === 'gallery'" class="gallery-section">
          <!-- 稀有度筛选胶囊 -->
          <div class="gallery-rarity-filter">
            <button
              type="button"
              class="filter-pill"
              :class="{ active: galleryRarity === 'ALL' }"
              @click="galleryRarity = 'ALL'"
            >
              全部 ({{ data?.collection?.length ?? 0 }})
            </button>
            <button
              v-for="r in rarityOrder"
              :key="r"
              type="button"
              class="filter-pill"
              :class="{ active: galleryRarity === r }"
              @click="galleryRarity = r"
            >
              {{ r }} ({{ (data?.collection ?? []).filter(i => i.rarity === r).length }})
            </button>
          </div>

          <!-- 现代勋章陈列墙 -->
          <div class="gallery-grid">
            <div
              v-for="item in filteredGallery"
              :key="item.id"
              class="gallery-badge-card"
              :class="{ 'is-locked': !item.owned, 'is-unlocked': item.owned }"
            >
              <div class="badge-artwork">
                <span v-if="item.owned" class="badge-icon">🏅</span>
                <span v-else class="badge-icon-locked">🔒</span>
              </div>
              <span class="rarity-badge" :style="{ color: rarityMeta[item.rarity].color, background: rarityMeta[item.rarity].bg }">
                {{ item.rarity }}
              </span>
              <h4 class="badge-name">{{ item.name }}</h4>
              <p class="badge-desc">{{ item.description }}</p>
              <span class="badge-status-note">
                {{ item.owned ? `已收集 · 拥有 ${item.copies} 张` : '未获得' }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- 全屏抽卡仪式与收获预览弹窗 (ESC 快捷关闭 / 磨砂质感 / 排序动效) -->
    <Teleport to="body">
      <div
        v-if="showGachaOverlay"
        class="gacha-fullscreen-overlay"
        role="dialog"
        aria-modal="true"
        @click.self="closeGacha"
      >
        <!-- 阶段 1：卡牌转圈召唤动画 (多少连抽就多少张卡牌转圈) -->
        <div v-if="gachaStage === 'spinning'" class="gacha-summon-portal">
          <div class="summon-cosmic-glow" />

          <!-- 转圈舞台 -->
          <div class="summon-orbit-arena" :class="`pull-${spinningPullCount}`">
            <!-- 单抽卡牌 (1 张卡牌悬浮旋转) -->
            <div v-if="spinningPullCount === 1" class="single-spinning-card">
              <div class="card-back-face">
                <span class="card-back-lotus">🪷</span>
                <span class="card-back-glow" />
              </div>
            </div>

            <!-- 10连抽卡牌圈 (10 张卡牌整齐转圈) -->
            <div v-else-if="spinningPullCount === 10" class="ten-orbit-ring">
              <div
                v-for="item in spinningCards"
                :key="item.id"
                class="orbit-card-node"
                :style="{
                  transform: `translate(${item.x}px, ${item.y}px) rotate(${item.rotate}deg)`
                }"
              >
                <div class="mini-card-back">
                  <span class="mini-lotus">🪷</span>
                </div>
              </div>
            </div>

            <!-- 100连抽大阵 (100 张卡牌四层同心圆旋涡飞旋) -->
            <div v-else class="hundred-orbit-vortex">
              <div
                v-for="(ring, ri) in vortexRings"
                :key="ri"
                class="vortex-ring"
                :class="`ring-${ri + 1}`"
              >
                <div
                  v-for="item in ring"
                  :key="item.id"
                  class="vortex-card-node"
                  :style="{
                    transform: `translate(${item.x}px, ${item.y}px) rotate(${item.rotate}deg)`
                  }"
                >
                  <div class="vortex-mini-card">
                    <span class="vortex-rune">✦</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- 中心光核 -->
            <div class="summon-center-core">
              <div class="core-lotus-glyph">🪷</div>
              <div class="core-pulse-wave" />
            </div>
          </div>

          <!-- 召唤底部提示与跳过 -->
          <div class="summon-controls-bar">
            <h3 class="summon-status-text">
              {{ spinningPullCount === 1 ? '单抽祈愿中 · 灵光汇聚' : spinningPullCount === 10 ? '十连召唤阵运转中 · 10 张卡牌流转' : '百连天命大阵运转中 · 100 张卡牌飞旋' }}
            </h3>
            <div class="summon-sub-actions">
              <button class="btn-skip-summon" type="button" @click="fastForwardAnimation">
                跳过动画 ➔
              </button>
              <span class="summon-esc-tip">
                <kbd class="esc-kbd">ESC</kbd> 退出预览
              </span>
            </div>
          </div>
        </div>

        <!-- 阶段 2 / 3：收获预览主窗体 (常驻顶部按 ESC 退出 + 磨砂卡牌 + 排序动画) -->
        <div v-else class="gacha-dialog-window">
          <!-- 顶部常驻小字导航条 (Sticky Header，100抽时滚动也永远可见) -->
          <div class="gacha-sticky-header">
            <div class="header-left-meta">
              <h2 class="gacha-harvest-title">🎉 抽卡收获</h2>
              <span class="gacha-harvest-count">共获得 {{ displayCards.length }} 张称号</span>
              <span v-if="isAutoSorting" class="sort-status-pill is-sorting">
                <span class="spin-dot">✦</span> 正在按稀有度自动排序...
              </span>
              <span v-else-if="gachaStage === 'settled'" class="sort-status-pill is-settled">
                ✓ 已按稀有度排列
              </span>
            </div>

            <!-- 用户要求核心：上面小字，按 esc 退出预览 -->
            <div class="header-center-esc-hint" title="按键盘 ESC 键或点击退出预览">
              <kbd class="esc-kbd">ESC</kbd>
              <span class="esc-hint-text">按 ESC 退出预览</span>
            </div>

            <!-- 右侧统计与关闭按钮 -->
            <div class="header-right-tools">
              <div class="harvest-rarity-chips">
                <span v-if="raritySummary.UR" class="summary-chip chip-ur">UR × {{ raritySummary.UR }}</span>
                <span v-if="raritySummary.SSR" class="summary-chip chip-ssr">SSR × {{ raritySummary.SSR }}</span>
                <span v-if="raritySummary.SR" class="summary-chip chip-sr">SR × {{ raritySummary.SR }}</span>
                <span v-if="raritySummary.R" class="summary-chip chip-r">R × {{ raritySummary.R }}</span>
                <span v-if="raritySummary.N" class="summary-chip chip-n">N × {{ raritySummary.N }}</span>
              </div>
              <button
                class="gacha-close-btn"
                type="button"
                aria-label="关闭预览"
                title="按 ESC 或点击关闭"
                @click="closeGacha"
              >
                ✕
              </button>
            </div>
          </div>

          <!-- 卡牌展示滚动体 (100 连抽也能极度流畅自如浏览，永不挡住头部和退出提示) -->
          <div class="gacha-cards-scroll-body">
            <TransitionGroup name="card-sort" tag="div" class="frosted-cards-grid">
              <div
                v-for="card in displayCards"
                :key="card.id"
                class="frosted-gacha-card"
                :class="[`rarity-${card.rarity}`]"
              >
                <!-- 卡片顶部稀有度与 NEW 标 -->
                <div class="card-header-bar">
                  <span
                    class="card-rarity-pill"
                    :style="{
                      color: rarityMeta[card.rarity].color,
                      background: rarityMeta[card.rarity].bg
                    }"
                  >
                    {{ card.rarity }}
                  </span>
                  <span v-if="card.is_new" class="card-new-pill">NEW!</span>
                </div>

                <!-- 卡片中心图标徽记 -->
                <div class="card-visual-emblem">
                  <span class="emblem-symbol">{{ getCardIcon(card) }}</span>
                  <div class="emblem-halo" :style="{ background: rarityMeta[card.rarity].glow }" />
                </div>

                <!-- 卡片底部称号名称与等级 (100% 解决没有称号名的问题) -->
                <div class="card-footer-box">
                  <h4 class="card-title-text" :title="card.name">{{ card.name }}</h4>
                  <span class="card-level-label">
                    {{ rarityMeta[card.rarity].label }}
                  </span>
                </div>
              </div>
            </TransitionGroup>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 消息提示 -->
    <div v-if="notice" class="toast-notice" role="status" aria-live="polite">
      {{ notice }}
    </div>
  </main>
</template>

<style scoped>
.titles-page-wrapper {
  max-width: 1280px;
  margin: 0 auto;
  padding: 24px 24px 80px;
  display: flex;
  flex-direction: column;
  gap: 28px;
}

/* 顶部称号横幅 */
.titles-hero-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  flex-wrap: wrap;
  padding: 18px 24px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
}

.header-brand-info {
  display: flex;
  align-items: center;
  gap: 14px;
}

.titles-badge-icon {
  width: 42px;
  height: 42px;
  border-radius: var(--radius-sm);
  background: var(--primary-light);
  border: 1px solid var(--primary-border);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.lotus-svg {
  width: 26px;
  height: 26px;
}

.titles-title {
  font-size: 20px;
  font-weight: 700;
  margin: 0;
  color: var(--text-main);
  letter-spacing: -0.01em;
}

.titles-subtitle {
  font-size: 13px;
  color: var(--text-muted);
  margin: 2px 0 0;
}

/* 右侧抽卡券背包 */
.tickets-inventory-pills {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.ticket-pill {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  border-radius: var(--radius-pill);
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  font-size: 13px;
  color: var(--text-main);
}

.ticket-pill .ticket-val {
  font-weight: 800;
  color: var(--primary);
  font-variant-numeric: tabular-nums;
}

.ticket-pill.highlight-ten {
  background: rgba(99, 102, 241, 0.1);
  border-color: rgba(99, 102, 241, 0.3);
  color: #6366f1;
}

.ticket-pill.highlight-ten .ticket-val {
  color: #6366f1;
}

.ticket-pill.highlight-hundred {
  background: var(--amber-light);
  border-color: var(--amber-border);
  color: #b45309;
}

[data-theme="dark"] .ticket-pill.highlight-hundred {
  color: #fbbf24;
}

.ticket-pill.highlight-hundred .ticket-val {
  color: #d97706;
}

/* Master-Detail 分栏 */
.titles-master-detail-grid {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 24px;
  align-items: start;
}

/* 左侧导航菜单 */
.titles-menu-sidebar {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.titles-nav-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.title-nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 18px;
  border-radius: var(--radius);
  background: var(--bg-card);
  border: 1px solid var(--border);
  color: var(--text-main);
  cursor: pointer;
  text-align: left;
  transition: all 0.2s ease;
  box-shadow: var(--shadow-sm);
  font-size: 14px;
  font-weight: 600;
}

.title-nav-item:hover {
  background: var(--bg-card-subtle);
  border-color: var(--primary-border);
}

.title-nav-item.active {
  background: var(--primary-light);
  border-color: var(--primary);
  color: var(--primary);
  box-shadow: 0 4px 14px rgba(13, 148, 136, 0.15);
}

.active-arrow {
  margin-left: auto;
  font-size: 13px;
}

/* 快速购券卡片 */
.quick-shop-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 18px;
  box-shadow: var(--shadow-card);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.quick-shop-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  font-weight: 700;
  color: var(--text-main);
}

.wallet-balance-text {
  font-size: 11px;
  color: var(--primary);
}

.quick-products-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.quick-product-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  background: var(--bg-subtle);
  border-radius: var(--radius-sm);
  font-size: 12px;
}

.p-name {
  overflow: hidden;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 价格列固定宽度、右对齐，三行数字上下对齐 */
.p-price {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  min-width: 84px;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.p-price-old {
  font-size: 11px;
  color: var(--text-dim);
}

.p-price-now {
  font-size: 13px;
  color: var(--text-main);
}

.btn-buy-ticket {
  padding: 4px 10px;
  font-size: 11px;
}

/* 3D 抽卡主舞台 (Arena) */
.draw-arena-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 40px 32px;
  box-shadow: var(--shadow-card);
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 40px;
  align-items: center;
  min-height: 380px;
}

.gacha-3d-cards-row {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  height: 260px;
  perspective: 800px;
}

.gacha-card-visual {
  width: 140px;
  height: 200px;
  border-radius: var(--radius);
  background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
  border: 2px solid var(--border);
  position: absolute;
  transition: all 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
  box-shadow: 0 16px 32px rgba(0, 0, 0, 0.25);
  display: flex;
  align-items: center;
  justify-content: center;
}

.card-left {
  transform: translateX(-60px) rotateY(15deg) scale(0.9);
  z-index: 1;
  opacity: 0.85;
}

.card-right {
  transform: translateX(60px) rotateY(-15deg) scale(0.9);
  z-index: 1;
  opacity: 0.85;
}

.card-center {
  transform: translateX(0) rotateY(0deg) scale(1.08);
  z-index: 3;
  border-color: #f59e0b;
  box-shadow: 0 20px 40px rgba(245, 158, 11, 0.35);
  background: linear-gradient(135deg, #78350f 0%, #1e1b4b 100%);
}

.card-inner-graphic {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.card-lotus-emblem {
  font-size: 40px;
}

.card-badge-tag {
  font-size: 14px;
  font-weight: 800;
  color: #fbbf24;
}

.golden-rays-aura {
  position: absolute;
  inset: -10px;
  border-radius: var(--radius);
  background: radial-gradient(circle, rgba(245, 158, 11, 0.25) 0%, transparent 70%);
  filter: blur(12px);
  pointer-events: none;
}

.draw-control-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.draw-title {
  font-size: 26px;
  font-weight: 800;
  margin: 0;
  color: var(--text-main);
  letter-spacing: -0.02em;
}

.draw-subtitle {
  font-size: 13px;
  color: var(--text-muted);
  line-height: 1.6;
  margin: 0;
}

.draw-buttons-cluster {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 10px;
}

.btn-draw-single, .btn-draw-ten, .btn-draw-hundred {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 18px;
  border-radius: var(--radius);
  cursor: pointer;
  transition: all 0.2s ease;
  border: 1px solid var(--border);
}

.btn-draw-single {
  background: var(--bg-card);
  color: var(--text-main);
}

.btn-draw-single:hover:not(:disabled) {
  border-color: var(--primary-border);
  transform: translateY(-2px);
}

.btn-draw-ten {
  background: linear-gradient(135deg, var(--primary) 0%, #0f766e 100%);
  color: #ffffff;
  border: none;
  box-shadow: 0 4px 14px rgba(13, 148, 136, 0.35);
}

.btn-draw-ten:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 8px 22px rgba(13, 148, 136, 0.45);
}

.btn-draw-hundred {
  background: linear-gradient(135deg, #d97706 0%, #b45309 100%);
  color: #ffffff;
  border: none;
  box-shadow: 0 4px 14px rgba(217, 119, 6, 0.35);
}

.btn-draw-hundred:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 8px 22px rgba(217, 119, 6, 0.45);
}

.draw-btn-text {
  font-size: 15px;
  font-weight: 700;
}

.draw-btn-sub {
  font-size: 12px;
  opacity: 0.85;
}

/* 我的称号 */
.owned-titles-section {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.equipped-showcase-box {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px 24px;
  box-shadow: var(--shadow-sm);
}

.equipped-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.equipped-label {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-muted);
}

.equipped-card-content {
  display: flex;
  align-items: center;
  gap: 16px;
}

.equipped-crown {
  font-size: 38px;
}

.equipped-title-name {
  font-size: 18px;
  font-weight: 800;
  margin: 0 0 4px;
  color: var(--text-main);
}

.equipped-title-desc {
  font-size: 13px;
  color: var(--text-muted);
  margin: 0 0 8px;
}

.equipped-empty {
  padding: 20px;
  text-align: center;
  color: var(--text-dim);
  font-size: 13px;
}

.owned-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 16px;
}

.owned-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  box-shadow: var(--shadow-sm);
}

.owned-card.is-equipped {
  border-color: var(--primary);
  background: var(--primary-light);
}

.owned-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.rarity-badge {
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: var(--radius-pill);
}

.copies-tag {
  font-size: 11px;
  color: var(--text-dim);
}

.item-name {
  font-size: 15px;
  font-weight: 700;
  margin: 0;
  color: var(--text-main);
}

.item-desc {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.4;
  margin: 0;
  flex: 1;
}

.btn-equip {
  align-self: flex-start;
  margin-top: 8px;
}

/* 图鉴陈列室 */
.gallery-section {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.gallery-rarity-filter {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.filter-pill {
  padding: 6px 14px;
  border-radius: var(--radius-pill);
  font-size: 12px;
  font-weight: 600;
  background: var(--bg-card);
  border: 1px solid var(--border);
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.2s ease;
}

.filter-pill.active {
  background: var(--primary);
  color: #ffffff;
  border-color: var(--primary);
}

.gallery-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 16px;
}

.gallery-badge-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px 16px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  box-shadow: var(--shadow-sm);
  transition: transform 0.2s ease;
}

.gallery-badge-card.is-unlocked:hover {
  transform: translateY(-2px);
  border-color: var(--primary-border);
}

.gallery-badge-card.is-locked {
  opacity: 0.6;
  filter: grayscale(0.8);
}

.badge-artwork {
  font-size: 36px;
  margin-bottom: 4px;
}

.badge-name {
  font-size: 14px;
  font-weight: 700;
  margin: 0;
  color: var(--text-main);
}

.badge-desc {
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.4;
  margin: 0;
}

.badge-status-note {
  font-size: 11px;
  color: var(--text-dim);
  margin-top: auto;
}

/* 全屏抽卡仪式与收获预览弹窗 */
.gacha-fullscreen-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  background: rgba(15, 23, 42, 0.78);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  animation: gacha-fade-in 0.25s ease-out;
}

@keyframes gacha-fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* 阶段 1：旋转召唤大阵 */
.gacha-summon-portal {
  position: relative;
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  user-select: none;
}

.summon-cosmic-glow {
  position: absolute;
  width: 600px;
  height: 600px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(45, 212, 191, 0.22) 0%, rgba(99, 102, 241, 0.16) 45%, transparent 70%);
  animation: cosmic-breathe 3s ease-in-out infinite alternate;
  pointer-events: none;
}

@keyframes cosmic-breathe {
  from { transform: scale(0.9); opacity: 0.7; }
  to { transform: scale(1.15); opacity: 1; }
}

.summon-orbit-arena {
  position: relative;
  width: 580px;
  height: 580px;
  max-width: 88vw;
  max-height: 88vw;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 单抽旋转卡牌 */
.single-spinning-card {
  width: 100px;
  height: 145px;
  perspective: 800px;
  animation: single-card-float 2.2s ease-in-out infinite alternate;
}

.card-back-face {
  width: 100%;
  height: 100%;
  background: linear-gradient(145deg, rgba(30, 41, 59, 0.85) 0%, rgba(15, 23, 42, 0.95) 100%);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 2px solid rgba(45, 212, 191, 0.65);
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: inset 0 1px 1px rgba(255, 255, 255, 0.4), 0 12px 30px rgba(45, 212, 191, 0.35);
  position: relative;
}

.card-back-lotus {
  font-size: 38px;
  filter: drop-shadow(0 0 10px rgba(45, 212, 191, 0.8));
}

@keyframes single-card-float {
  0% { transform: translateY(-8px) rotateY(-18deg) rotateZ(-3deg); }
  50% { transform: translateY(8px) rotateY(18deg) rotateZ(3deg); }
  100% { transform: translateY(-8px) rotateY(-18deg) rotateZ(-3deg); }
}

/* 十连抽卡牌圆环 */
.ten-orbit-ring {
  position: absolute;
  width: 100%;
  height: 100%;
  animation: orbit-spin-cw 3.8s linear infinite;
}

.orbit-card-node {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 44px;
  height: 66px;
  margin-left: -22px;
  margin-top: -33px;
}

.mini-card-back {
  width: 100%;
  height: 100%;
  background: linear-gradient(135deg, rgba(30, 41, 59, 0.88), rgba(15, 23, 42, 0.95));
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1.5px solid rgba(45, 212, 191, 0.7);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: inset 0 1px 1px rgba(255, 255, 255, 0.3), 0 6px 16px rgba(45, 212, 191, 0.3);
}

.mini-lotus {
  font-size: 16px;
}

/* 百连抽 100 张卡牌旋涡 */
.hundred-orbit-vortex {
  position: absolute;
  width: 100%;
  height: 100%;
}

.vortex-card-node {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 26px;
  height: 40px;
  margin-left: -13px;
  margin-top: -20px;
}

.vortex-ring {
  position: absolute;
  inset: 0;
}
.vortex-ring.ring-1 { animation: orbit-spin-cw 5.5s linear infinite; }
.vortex-ring.ring-2 { animation: orbit-spin-ccw 7.5s linear infinite; }
.vortex-ring.ring-3 { animation: orbit-spin-cw 9.5s linear infinite; }
.vortex-ring.ring-4 { animation: orbit-spin-ccw 12s linear infinite; }

.vortex-mini-card {
  width: 100%;
  height: 100%;
  background: linear-gradient(135deg, rgba(30, 41, 59, 0.9), rgba(15, 23, 42, 0.96));
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  border: 1px solid rgba(245, 158, 11, 0.65);
  border-radius: 5px;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: inset 0 1px 1px rgba(255, 255, 255, 0.3), 0 4px 10px rgba(245, 158, 11, 0.3);
}

.vortex-rune {
  font-size: 11px;
  color: #fbbf24;
  filter: drop-shadow(0 0 4px #fbbf24);
}

@keyframes orbit-spin-cw {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

@keyframes orbit-spin-ccw {
  from { transform: rotate(0deg); }
  to { transform: rotate(-360deg); }
}

/* 中心光核 */
.summon-center-core {
  position: absolute;
  width: 76px;
  height: 76px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(45, 212, 191, 0.4) 0%, rgba(13, 148, 136, 0.2) 60%, transparent 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 5;
}

.core-lotus-glyph {
  font-size: 32px;
  filter: drop-shadow(0 0 12px rgba(45, 212, 191, 0.9));
  animation: core-glyph-pulse 1.8s ease-in-out infinite alternate;
}

@keyframes core-glyph-pulse {
  from { transform: scale(0.9); }
  to { transform: scale(1.1); }
}

.core-pulse-wave {
  position: absolute;
  inset: -12px;
  border-radius: 50%;
  border: 2px solid rgba(45, 212, 191, 0.5);
  animation: pulse-ring 2s cubic-bezier(0.2, 0.8, 0.2, 1) infinite;
}

@keyframes pulse-ring {
  0% { transform: scale(0.7); opacity: 1; }
  100% { transform: scale(1.6); opacity: 0; }
}

/* 召唤底部操作条 */
.summon-controls-bar {
  margin-top: 24px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  z-index: 10;
}

.summon-status-text {
  font-size: 17px;
  font-weight: 700;
  color: #f1f5f9;
  letter-spacing: 0.5px;
  margin: 0;
  text-shadow: 0 2px 8px rgba(0, 0, 0, 0.6);
}

.summon-sub-actions {
  display: flex;
  align-items: center;
  gap: 16px;
}

.btn-skip-summon {
  background: rgba(255, 255, 255, 0.12);
  border: 1px solid rgba(255, 255, 255, 0.25);
  color: #f8fafc;
  padding: 6px 16px;
  border-radius: var(--radius-pill);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  transition: all 0.2s ease;
}

.btn-skip-summon:hover {
  background: rgba(255, 255, 255, 0.22);
  border-color: rgba(255, 255, 255, 0.45);
  transform: translateY(-1px);
}

.summon-esc-tip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #94a3b8;
  font-size: 12px;
}

/* 阶段 2 / 3：收获预览主窗体 (常驻置顶头部 + 磨砂卡牌 + 排序动画) */
.gacha-dialog-window {
  width: 95vw;
  max-width: 1240px;
  max-height: 88vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 20px;
  box-shadow: 0 25px 60px -15px rgba(0, 0, 0, 0.45);
  overflow: hidden;
  position: relative;
  animation: window-pop-in 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes window-pop-in {
  from { opacity: 0; transform: scale(0.95) translateY(12px); }
  to { opacity: 1; transform: scale(1) translateY(0); }
}

/* 顶部常驻小字导航条 (Sticky Header，100抽时滚动也永远可见) */
.gacha-sticky-header {
  position: sticky;
  top: 0;
  z-index: 25;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 22px;
  gap: 16px;
  background: var(--bg-card);
  border-bottom: 1px solid var(--border);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
}

.header-left-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.gacha-harvest-title {
  font-size: 18px;
  font-weight: 800;
  margin: 0;
  color: var(--text-main);
}

.gacha-harvest-count {
  font-size: 13px;
  color: var(--text-muted);
}

.sort-status-pill {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 10px;
  border-radius: var(--radius-pill);
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.sort-status-pill.is-sorting {
  background: rgba(124, 58, 237, 0.12);
  color: #7c3aed;
  border: 1px solid rgba(124, 58, 237, 0.25);
  animation: pulse-gentle 1.2s infinite ease-in-out;
}

.sort-status-pill.is-settled {
  background: rgba(16, 185, 129, 0.12);
  color: #059669;
  border: 1px solid rgba(16, 185, 129, 0.25);
}

.spin-dot {
  display: inline-block;
  animation: orbit-spin-cw 1.8s linear infinite;
}

@keyframes pulse-gentle {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.65; }
}

/* 用户要求核心：上面小字，按 esc 退出预览 */
.header-center-esc-hint {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 4px 12px;
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  color: var(--text-muted);
  font-size: 12px;
  user-select: none;
}

.esc-kbd {
  display: inline-block;
  padding: 1px 6px;
  font-family: inherit;
  font-size: 10.5px;
  font-weight: 800;
  line-height: 1.4;
  color: var(--text-main);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-bottom: 2px solid var(--border);
  border-radius: 4px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}

.esc-hint-text {
  font-weight: 600;
  letter-spacing: 0.2px;
}

.header-right-tools {
  display: flex;
  align-items: center;
  gap: 12px;
}

.harvest-rarity-chips {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.summary-chip {
  font-size: 11px;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: var(--radius-pill);
  border: 1px solid;
}

.chip-ur { color: #b45309; background: #fef3c7; border-color: rgba(245, 158, 11, 0.4); }
.chip-ssr { color: #7c3aed; background: #ede9fe; border-color: rgba(124, 58, 237, 0.35); }
.chip-sr { color: #2563eb; background: #dbeafe; border-color: rgba(37, 99, 235, 0.3); }
.chip-r { color: #059669; background: #d1fae5; border-color: rgba(5, 150, 105, 0.25); }
.chip-n { color: #6b7280; background: #f3f4f6; border-color: rgba(107, 114, 128, 0.2); }

.gacha-close-btn {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 1px solid var(--border);
  background: var(--bg-subtle);
  color: var(--text-muted);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.gacha-close-btn:hover {
  background: #fee2e2;
  color: #dc2626;
  border-color: #fca5a5;
  transform: rotate(90deg);
}

/* 卡牌展示滚动体 (100 连抽也能极度流畅浏览) */
.gacha-cards-scroll-body {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  overscroll-behavior: contain;
}

.frosted-cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(136px, 1fr));
  gap: 16px;
  width: 100%;
  position: relative;
}

/* 排序 FLIP 动效 */
.card-sort-move {
  transition: transform 0.75s cubic-bezier(0.2, 0.9, 0.3, 1.15);
}

.card-sort-enter-active {
  transition: all 0.45s cubic-bezier(0.16, 1, 0.3, 1);
}

.card-sort-enter-from {
  opacity: 0;
  transform: scale(0.65) translateY(24px);
}

/* 磨砂半透明卡牌 (包含各等级底色) */
.frosted-gacha-card {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: space-between;
  min-height: 165px;
  padding: 12px 10px;
  border-radius: 16px;
  overflow: hidden;
  user-select: none;
  cursor: default;

  /* 磨砂核心材质 */
  backdrop-filter: blur(16px) saturate(160%);
  -webkit-backdrop-filter: blur(16px) saturate(160%);
  border: 1.5px solid;
  transition: transform 0.25s cubic-bezier(0.2, 0.8, 0.4, 1), box-shadow 0.25s ease;
}

.frosted-gacha-card:hover {
  transform: translateY(-4px) scale(1.02);
  z-index: 5;
}

/* 等级底色 (半透明渐变磨砂) */
.frosted-gacha-card.rarity-UR {
  background: linear-gradient(145deg, rgba(245, 158, 11, 0.22) 0%, rgba(180, 83, 9, 0.35) 100%);
  border-color: rgba(245, 158, 11, 0.75);
  box-shadow: inset 0 1px 1.5px rgba(255, 255, 255, 0.55), 0 10px 28px rgba(245, 158, 11, 0.35);
}

.frosted-gacha-card.rarity-SSR {
  background: linear-gradient(145deg, rgba(168, 85, 247, 0.20) 0%, rgba(124, 58, 237, 0.32) 100%);
  border-color: rgba(168, 85, 247, 0.7);
  box-shadow: inset 0 1px 1.5px rgba(255, 255, 255, 0.5), 0 10px 24px rgba(124, 58, 237, 0.32);
}

.frosted-gacha-card.rarity-SR {
  background: linear-gradient(145deg, rgba(59, 130, 246, 0.18) 0%, rgba(37, 99, 235, 0.28) 100%);
  border-color: rgba(59, 130, 246, 0.65);
  box-shadow: inset 0 1px 1.5px rgba(255, 255, 255, 0.45), 0 8px 20px rgba(37, 99, 235, 0.28);
}

.frosted-gacha-card.rarity-R {
  background: linear-gradient(145deg, rgba(16, 185, 129, 0.16) 0%, rgba(5, 150, 105, 0.25) 100%);
  border-color: rgba(16, 185, 129, 0.6);
  box-shadow: inset 0 1px 1.5px rgba(255, 255, 255, 0.4), 0 8px 18px rgba(16, 185, 129, 0.25);
}

.frosted-gacha-card.rarity-N {
  background: linear-gradient(145deg, rgba(148, 163, 184, 0.14) 0%, rgba(100, 116, 139, 0.22) 100%);
  border-color: rgba(148, 163, 184, 0.45);
  box-shadow: inset 0 1px 1.5px rgba(255, 255, 255, 0.35), 0 4px 12px rgba(0, 0, 0, 0.08);
}

/* 高光扫光动效 (UR 与 SSR 尊贵流光) */
.frosted-gacha-card.rarity-UR::after,
.frosted-gacha-card.rarity-SSR::after {
  content: '';
  position: absolute;
  top: -60%;
  left: -60%;
  width: 220%;
  height: 220%;
  background: linear-gradient(
    115deg,
    transparent 38%,
    rgba(255, 255, 255, 0.25) 46%,
    rgba(255, 255, 255, 0.45) 50%,
    rgba(255, 255, 255, 0.25) 54%,
    transparent 62%
  );
  transform: rotate(25deg);
  pointer-events: none;
  animation: card-hologram-shimmer 3.8s infinite linear;
}

@keyframes card-hologram-shimmer {
  0% { transform: translate(-30%, -30%) rotate(25deg); }
  100% { transform: translate(30%, 30%) rotate(25deg); }
}

.card-header-bar {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-rarity-pill {
  font-size: 10.5px;
  font-weight: 800;
  padding: 1px 7px;
  border-radius: var(--radius-pill);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.card-new-pill {
  font-size: 9px;
  font-weight: 800;
  color: #fff;
  background: linear-gradient(135deg, #ef4444, #dc2626);
  padding: 1px 5px;
  border-radius: 4px;
  box-shadow: 0 2px 6px rgba(220, 38, 38, 0.4);
  animation: pulse-gentle 1.5s infinite ease-in-out;
}

.card-visual-emblem {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 8px 0;
}

.emblem-symbol {
  font-size: 34px;
  position: relative;
  z-index: 2;
  filter: drop-shadow(0 2px 6px rgba(0, 0, 0, 0.2));
}

.emblem-halo {
  position: absolute;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  filter: blur(10px);
  opacity: 0.8;
  z-index: 1;
}

.card-footer-box {
  width: 100%;
  text-align: center;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.card-title-text {
  font-size: 13.5px;
  font-weight: 800;
  color: var(--text-main);
  margin: 0;
  line-height: 1.35;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.12);
  word-break: break-all;
}

.card-level-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
}

@media (max-width: 900px) {
  .titles-master-detail-grid {
    grid-template-columns: 1fr;
  }
  .draw-arena-card {
    grid-template-columns: 1fr;
  }
  .gacha-sticky-header {
    padding: 12px 16px;
  }
  .header-center-esc-hint {
    order: 3;
    width: 100%;
    justify-content: center;
  }
  .frosted-cards-grid {
    grid-template-columns: repeat(auto-fill, minmax(115px, 1fr));
    gap: 12px;
  }
}
</style>
