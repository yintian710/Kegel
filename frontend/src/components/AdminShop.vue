<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Product, Purchase, SaveProductInput } from '../api'
import AdminIcon from './AdminIcon.vue'
import AdminProductDrawer from './AdminProductDrawer.vue'
import { fmtTime, purchaseStatus, remaining, zheText } from './adminFormat'

const props = defineProps<{ products: Product[]; purchases: Purchase[]; busy: boolean }>()
const emit = defineEmits<{
  save: [value: SaveProductInput, afterSuccess: () => void]
  archive: [product: Product]
  reconcile: [order: Purchase, result: 'success' | 'failed']
  check: [order: Purchase]
  checkAll: []
}>()

const view = ref<'orders' | 'products'>('orders')

// ── 商品 ──
const drawerOpen = ref(false)
const editing = ref<Product | null>(null)
function openDrawer(product: Product | null): void {
  editing.value = product
  drawerOpen.value = true
}
function closeDrawer(): void {
  drawerOpen.value = false
}
function onSave(value: SaveProductInput): void {
  emit('save', value, closeDrawer)
}
function limitText(n: number, unit: string): string {
  return n > 0 ? `${n} ${unit}` : '不限'
}

// ── 订单筛选 ──
type Filter = 'all' | Purchase['status'] | 'no_payout'
const filter = ref<Filter>('all')
const keyword = ref('')
const filters: Array<{ key: Filter; label: string }> = [
  { key: 'all', label: '全部' },
  { key: 'uncertain', label: '待核对' },
  { key: 'pending', label: '处理中' },
  { key: 'success', label: '成功' },
  { key: 'failed', label: '失败' },
  { key: 'no_payout', label: '不发货' },
]
function matches(order: Purchase, key: Filter): boolean {
  if (key === 'all') return true
  if (key === 'no_payout') return !!order.no_payout
  if (key === 'success') return order.status === 'success' || order.status === 'simulated'
  return order.status === key
}
const counts = computed(() => Object.fromEntries(filters.map((f) => [f.key, props.purchases.filter((p) => matches(p, f.key)).length])) as Record<Filter, number>)
const shown = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  return props.purchases.filter((p) =>
    matches(p, filter.value)
    && (!q || p.username.toLowerCase().includes(q) || p.order_no.toLowerCase().includes(q) || (p.trade_no || '').toLowerCase().includes(q)),
  )
})
const uncertainCount = computed(() => counts.value.uncertain)
</script>

<template>
  <div class="adm-card">
    <div class="adm-card-head">
      <div class="adm-seg">
        <button type="button" :class="{ on: view === 'orders' }" @click="view = 'orders'">
          兑换订单 <em>{{ purchases.length }}</em>
        </button>
        <button type="button" :class="{ on: view === 'products' }" @click="view = 'products'">
          商品 <em>{{ products.length }}</em>
        </button>
      </div>
      <button v-if="view === 'products'" class="adm-btn primary" type="button" :disabled="busy" @click="openDrawer(null)">
        <AdminIcon name="plus" /> 上架商品
      </button>
      <div v-else class="adm-search">
        <AdminIcon name="search" />
        <input v-model="keyword" class="adm-input" type="search" placeholder="搜索用户 / 订单号 / 交易号" aria-label="搜索订单">
      </div>
    </div>

    <!-- 订单 -->
    <template v-if="view === 'orders'">
      <div style="padding: 12px 20px 0">
        <div class="adm-seg">
          <button v-for="f in filters" :key="f.key" type="button" :class="{ on: filter === f.key }" @click="filter = f.key">
            {{ f.label }} <em>{{ counts[f.key] }}</em>
          </button>
        </div>
        <div v-if="uncertainCount" class="adm-actions" style="justify-content: space-between; margin-top: 10px">
          <span class="adm-err" style="color: var(--text-muted)">
            有 {{ uncertainCount }} 笔订单待核对。系统每 5 分钟自动向 Credit 查询：确认已发货则标记成功；下单满 30 秒仍查无此单则判定未发货并退分。
          </span>
          <button class="adm-btn sm" type="button" :disabled="busy" @click="emit('checkAll')">
            <AdminIcon name="refresh" /> 全部查询
          </button>
        </div>
      </div>
      <div class="adm-tablewrap" style="margin-top: 12px; max-height: 620px">
        <table class="adm-table">
          <thead>
            <tr><th>用户 / 订单</th><th>商品</th><th>积分</th><th>状态</th><th>交易号 / 错误</th><th>时间</th><th class="r">操作</th></tr>
          </thead>
          <tbody>
            <tr v-if="!shown.length"><td colspan="7" class="adm-empty">没有符合条件的订单</td></tr>
            <tr v-for="item in shown" :key="item.order_no" :class="{ flag: item.no_payout }">
              <td>
                <b>@{{ item.username }}</b>
                <span v-if="item.no_payout" class="adm-tag err plain" style="margin-left: 6px">不发货</span>
                <div class="mono muted">{{ item.order_no }}</div>
              </td>
              <td>{{ item.product_name.includes(item.ldc_amount) ? item.product_name : `${item.product_name}（${item.ldc_amount} LDC）` }}</td>
              <td class="nowrap">-{{ item.points_cost }}</td>
              <td><span class="adm-tag" :class="purchaseStatus[item.status]?.tone">{{ purchaseStatus[item.status]?.label ?? item.status }}</span></td>
              <td class="mono">{{ item.trade_no || item.error || '—' }}</td>
              <td class="nowrap muted">{{ fmtTime(item.created_at) }}</td>
              <td class="r">
                <div v-if="item.status === 'uncertain'" class="ops">
                  <button class="adm-btn sm primary" type="button" :disabled="busy" @click="emit('check', item)">查询</button>
                  <button class="adm-btn sm" type="button" :disabled="busy" @click="emit('reconcile', item, 'success')">已发货</button>
                  <button class="adm-btn sm danger" type="button" :disabled="busy" @click="emit('reconcile', item, 'failed')">未发货并退分</button>
                </div>
                <span v-else class="muted">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <!-- 商品 -->
    <div v-else class="adm-tablewrap" style="margin-top: 12px">
      <table class="adm-table">
        <thead>
          <tr><th>商品</th><th>售价</th><th>发货 / 券面额</th><th>每日限购（人 / 全站）</th><th>今日已售</th><th>状态</th><th class="r">操作</th></tr>
        </thead>
        <tbody>
          <tr v-if="!products.length"><td colspan="7" class="adm-empty">还没有商品，点击右上角「上架商品」添加</td></tr>
          <tr v-for="item in products" :key="item.id">
            <td>
              <b>{{ item.name }}</b>
              <span v-if="item.category === 'TICKET'" class="adm-tag info plain" style="margin-left: 6px">抽卡券</span>
              <div class="mono muted">#{{ item.id }}</div>
            </td>
            <td class="nowrap">
              <template v-if="item.promo_active">
                <b>{{ item.points_price && item.promo_bp ? Math.ceil((item.points_price * item.promo_bp) / 10000) : item.points_price }} 分</b>
                <s class="muted" style="margin-left: 4px">{{ item.points_price }}</s>
                <div><span class="adm-tag warn plain">限时 {{ zheText(item.promo_bp) }} · 剩 {{ remaining(item.promo_ends_at) }}</span></div>
              </template>
              <template v-else>{{ item.points_price }} 分</template>
            </td>
            <td class="nowrap">{{ item.category === 'TICKET' ? `${item.draw_count} 抽` : `${item.ldc_amount} LDC` }}</td>
            <td class="nowrap">{{ item.category === 'TICKET' ? '不限' : `${limitText(item.user_daily_limit, '份')} / ${limitText(item.total_daily_limit, '份')}` }}</td>
            <td>{{ item.total_today_count }}</td>
            <td><span class="adm-tag" :class="item.is_active ? 'ok' : 'plain'">{{ item.is_active ? '在售' : '已下架' }}</span></td>
            <td class="r">
              <div class="ops">
                <button class="adm-btn sm" type="button" :disabled="busy" @click="openDrawer(item)"><AdminIcon name="edit" /> 编辑</button>
                <button v-if="item.is_active" class="adm-btn sm danger" type="button" :disabled="busy" @click="emit('archive', item)">下架</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <AdminProductDrawer :open="drawerOpen" :product="editing" :busy="busy" @save="onSave" @close="closeDrawer" />
</template>
