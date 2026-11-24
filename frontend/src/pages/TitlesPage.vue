<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError, loginUrl, titles as titlesApi, type DrawData, type Rarity, type TicketType, type TitleData, type TitleItem } from '../api'
import { useBodyAttributes } from '../composables/useBodyAttributes'
import { useIdentity } from '../composables/useIdentity'
import { playFeedbackSound, triggerHaptic } from '../composables/usePreferences'

useBodyAttributes({})
const identity = useIdentity()
const data = ref<TitleData | null>(null)
const loading = ref(false)
const busy = ref(false)
const notice = ref('')
const results = ref<DrawData['results']>([])
let noticeTimer: number | undefined

const rarityOrder: Rarity[] = ['UR', 'SSR', 'SR', 'R', 'N']
const rarityMeta: Record<Rarity, { label: string; color: string; bg: string }> = {
  UR: { label: '至尊', color: '#b45309', bg: '#fef3c7' },
  SSR: { label: '传说', color: '#7c3aed', bg: '#ede9fe' },
  SR: { label: '史诗', color: '#2563eb', bg: '#dbeafe' },
  R: { label: '稀有', color: '#059669', bg: '#d1fae5' },
  N: { label: '普通', color: '#6b7280', bg: '#f3f4f6' },
}
const ticketMeta: Array<{ type: TicketType; label: string; draws: number; icon: string }> = [
  { type: 'single', label: '单抽券', draws: 1, icon: '🎫' },
  { type: 'ten', label: '十连券', draws: 10, icon: '🎟️' },
  { type: 'hundred', label: '百连券', draws: 100, icon: '✨' },
]

const nameMap = computed<Record<string, TitleItem>>(() => {
  const map: Record<string, TitleItem> = {}
  for (const item of data.value?.collection ?? []) map[item.id] = item
  return map
})
const grouped = computed(() => rarityOrder.map((rarity) => ({
  rarity,
  items: (data.value?.collection ?? []).filter((item) => item.rarity === rarity),
  owned: (data.value?.collection ?? []).filter((item) => item.rarity === rarity && item.owned).length,
})))
const wallet = computed(() => Number(data.value?.wallet?.balance ?? 0))
const codeMap = computed<Record<string, TitleItem>>(() => {
  const map: Record<string, TitleItem> = {}
  for (const item of data.value?.collection ?? []) map[item.code] = item
  return map
})
const smeltRarities: Rarity[] = ['N', 'R', 'SR']
const nextRarityMap: Record<string, Rarity> = { N: 'R', R: 'SR', SR: 'SSR' }
const smeltCostMap: Record<string, { random: number; target: number }> = {
  N: { random: 3, target: 6 }, R: { random: 3, target: 6 }, SR: { random: 5, target: 10 },
}
const smeltMode = ref<'random' | 'target'>('random')
const smeltRarity = ref<Rarity>('N')
const smeltSelection = ref<Record<string, number>>({})
const smeltTarget = ref('')
const smeltDialog = ref<HTMLDialogElement | null>(null)
const smeltCost = computed(() => smeltCostMap[smeltRarity.value]?.[smeltMode.value] ?? 0)
const smeltCandidates = computed(() => (data.value?.collection ?? [])
  .filter((item) => item.rarity === smeltRarity.value && availableOf(item) > 0)
  .map((item) => ({ ...item, available: availableOf(item) })))
const selectedTotal = computed(() => Object.values(smeltSelection.value).reduce((sum, n) => sum + n, 0))
const targetCandidates = computed(() => (data.value?.collection ?? []).filter((item) => item.rarity === nextRarityMap[smeltRarity.value]))

function availableOf(item: TitleItem): number {
  return item.copies - (data.value?.equipped_title_id === item.id ? 1 : 0)
}
function resetSmelt(): void { smeltSelection.value = {}; smeltTarget.value = '' }
function titleOfCode(code: string): TitleItem | undefined { return codeMap.value[code] }
function titleOfId(id: string): TitleItem | undefined { return nameMap.value[id] }
function addMaterial(item: TitleItem): void {
  const current = smeltSelection.value[item.id] ?? 0
  if (current >= availableOf(item)) return
  smeltSelection.value = { ...smeltSelection.value, [item.id]: current + 1 }
  triggerHaptic(20)
}
function removeMaterial(item?: TitleItem): void {
  if (!item) return
  const next = { ...smeltSelection.value }
  delete next[item.id]
  smeltSelection.value = next
}
function openSmeltPicker(): void {
  if (!smeltCandidates.value.length) { notify('该稀有度暂无可熔炼的副本'); return }
  smeltDialog.value?.showModal()
}

function messageOf(error: unknown): string { return error instanceof Error ? error.message : String(error) }
function notify(message: string): void {
  notice.value = message
  window.clearTimeout(noticeTimer)
  noticeTimer = window.setTimeout(() => { notice.value = '' }, 4500)
}
function displayTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false })
}
function newRequestId(): string { return crypto.randomUUID() }

async function refresh(): Promise<void> {
  if (loading.value) return
  loading.value = true
  try {
    data.value = await titlesApi.get({ headers: { 'Cache-Control': 'no-cache' } })
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) { window.location.assign(loginUrl('/titles')); return }
    notify(`无法读取抽卡数据：${messageOf(error)}`)
  } finally { loading.value = false }
}

async function draw(type: TicketType): Promise<void> {
  if (busy.value) return
  const owned = data.value?.tickets?.[type] ?? 0
  const meta = ticketMeta.find((item) => item.type === type)!
  if (owned < 1) { notify(`没有${meta.label}了，请先在右侧购买`); return }
  busy.value = true
  try {
    const result = await titlesApi.draw({ ticket_type: type, request_id: newRequestId() })
    results.value = result.results
    const top = result.results.reduce((best, item) => (rarityOrder.indexOf(item.rarity) < rarityOrder.indexOf(best) ? item.rarity : best), 'N' as Rarity)
    playFeedbackSound('complete')
    triggerHaptic([30, 60, 40])
    notify(`🎴 抽卡完成！共 ${result.batch.count} 抽，最高稀有度：${rarityMeta[top].label}`)
    await refresh()
  } catch (error) {
    notify(`抽卡失败：${messageOf(error)}`)
  } finally { busy.value = false }
}

async function equip(item: TitleItem): Promise<void> {
  if (busy.value || !item.owned) return
  busy.value = true
  try {
    const equipped = data.value?.equipped_title_id === item.id
    await titlesApi.equip({ title_id: equipped ? null : item.id })
    playFeedbackSound('step')
    triggerHaptic(30)
    notify(equipped ? '已卸下称号' : `已装备「${item.name}」`)
    await refresh()
  } catch (error) {
    notify(`操作失败：${messageOf(error)}`)
  } finally { busy.value = false }
}

async function doSmelt(): Promise<void> {
  if (busy.value) return
  const materials = Object.entries(smeltSelection.value).map(([title_id, count]) => ({ title_id, count }))
  if (selectedTotal.value !== smeltCost.value) { notify(`请选择 ${smeltCost.value} 张材料`); return }
  if (smeltMode.value === 'target' && !smeltTarget.value) { notify('请选择定向目标'); return }
  busy.value = true
  try {
    const result = await titlesApi.smelt({
      mode: smeltMode.value, input_rarity: smeltRarity.value,
      target_title_id: smeltMode.value === 'target' ? smeltTarget.value : undefined,
      materials, request_id: newRequestId(),
    })
    playFeedbackSound('complete')
    triggerHaptic([40, 60])
    notify(`🔥 熔炼成功！获得${rarityMeta[result.output.rarity].label}「${nameMap.value[result.output.title_id]?.name || '称号'}」${result.output.is_new ? '（新）' : '（副本）'}`)
    resetSmelt()
    await refresh()
  } catch (error) {
    notify(`熔炼失败：${messageOf(error)}`)
  } finally { busy.value = false }
}

function recipeNeed(recipe: { materials: string[] }): Record<string, number> {
  const need: Record<string, number> = {}
  for (const code of recipe.materials) need[code] = (need[code] ?? 0) + 1
  return need
}
function recipeReady(recipe: { materials: string[] }): boolean {
  return Object.entries(recipeNeed(recipe)).every(([code, n]) => {
    const item = codeMap.value[code]
    return !!item && availableOf(item) >= n
  })
}
function recipeOutput(recipe: { output_code: string }): TitleItem | undefined { return codeMap.value[recipe.output_code] }

async function doCraft(recipe: { id: string; materials: string[] }): Promise<void> {
  if (busy.value || !recipeReady(recipe)) return
  busy.value = true
  try {
    const materials = Object.entries(recipeNeed(recipe)).map(([code, count]) => ({ title_id: codeMap.value[code]!.id, count }))
    const result = await titlesApi.craft({ recipe_id: recipe.id, materials, request_id: newRequestId() })
    playFeedbackSound('complete')
    triggerHaptic([50, 80, 50])
    notify(`✨ 至尊合成成功！获得「${nameMap.value[result.output.title_id]?.name || 'UR'}」`)
    await refresh()
  } catch (error) {
    notify(`合成失败：${messageOf(error)}`)
  } finally { busy.value = false }
}

onMounted(async () => {
  if (await identity.requireLogin('/titles')) await refresh()
})
</script>

<template>
  <main class="page-wrap">
    <div class="page-hero">
      <div style="display:flex;justify-content:space-between;align-items:flex-end;flex-wrap:wrap;gap:16px">
        <div>
          <h1>称号殿堂与抽卡</h1>
          <p>用抽卡券抽取全站限定称号，点亮图鉴、熔炼进阶，至尊 UR 可解锁全店 95 折特权。</p>
        </div>
        <RouterLink class="btn-primary" to="/shop" style="background:var(--bg-card);color:var(--primary);border:1px solid var(--primary-border);box-shadow:var(--shadow-sm)">
          购买更多抽卡券 ➔
        </RouterLink>
      </div>
    </div>

    <!-- 顶部资产看板 -->
    <div class="card" style="margin-bottom:24px">
      <div class="card-header-line">
        <h2 class="card-title">我的抽卡券背包</h2>
        <span class="card-subtitle">{{ data?.user ? `当前绑定账号：@${data.user.username}` : '登录后可用' }}</span>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:14px;margin-bottom:14px">
        <div class="ticket-stat-box">
          <span style="font-size:12px;color:var(--text-muted)">积分余额</span>
          <div style="font-size:24px;font-weight:800;color:var(--text-main);margin-top:2px">
            {{ wallet.toLocaleString() }}
          </div>
        </div>
        <div v-for="t in ticketMeta" :key="t.type" class="ticket-stat-box">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <span style="font-size:12px;color:var(--text-muted)">{{ t.label }} ({{ t.draws }}抽)</span>
            <span>{{ t.icon }}</span>
          </div>
          <div style="font-size:24px;font-weight:800;color:var(--primary);margin-top:2px">
            {{ data?.tickets?.[t.type] ?? 0 }}
          </div>
        </div>
      </div>
      <div style="font-size:12px;color:var(--text-muted);background:var(--bg-subtle);padding:8px 12px;border-radius:var(--radius-sm)">
        ✨ 保底机制：<strong>十连必出 SR 史诗及以上</strong> · <strong>百连必出 SSR 传说</strong> · 单抽无保底。
      </div>
    </div>

    <div class="shop-columns">
      <!-- 左栏：抽卡台与合成炉 -->
      <div>
        <!-- 抽卡互动台 -->
        <div class="card" style="margin-bottom:24px">
          <div class="card-header-line" style="margin-bottom:16px">
            <h2 class="card-title">抽卡法阵</h2>
            <span class="card-subtitle">消耗背包中的对应抽卡券</span>
          </div>
          <div style="display:flex;gap:12px;flex-wrap:wrap">
            <button
              v-for="t in ticketMeta"
              :key="t.type"
              class="btn-primary"
              type="button"
              :disabled="busy || (data?.tickets?.[t.type] ?? 0) < 1"
              style="padding:12px 22px"
              @click="draw(t.type)"
            >
              {{ t.icon }} {{ t.label }}（{{ t.draws }} 连抽）
            </button>
          </div>

          <!-- 抽卡展示结果 -->
          <div v-if="results.length" style="margin-top:24px;padding-top:20px;border-top:1px solid var(--border-light)">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
              <span style="font-size:14px;font-weight:700">本次抽卡战利品（共 {{ results.length }} 项）</span>
              <button class="btn-secondary" type="button" style="padding:2px 10px;font-size:11px" @click="results = []">收起结果</button>
            </div>
            <div class="draw-result-grid">
              <div
                v-for="(item, index) in results"
                :key="index"
                class="draw-card-item"
                :class="`rarity-${item.rarity.toLowerCase()}`"
              >
                <div class="draw-card-rarity">{{ rarityMeta[item.rarity].label }}</div>
                <div class="draw-card-name">{{ titleOfId(item.title_id)?.name || '称号' }}</div>
                <span v-if="item.is_new" class="draw-card-new">NEW</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 熔炼与合成 -->
        <div class="card" style="margin-bottom:24px">
          <div class="card-header-line" style="margin-bottom:16px">
            <div>
              <h2 class="card-title">熔炼与合成工坊</h2>
              <span class="card-subtitle">消耗多余副本，向上跃迁更高稀有度</span>
            </div>
          </div>

          <div style="display:flex;gap:8px;margin-bottom:14px">
            <button
              class="home-tab-btn"
              type="button"
              :class="{ active: smeltMode === 'random' }"
              @click="smeltMode = 'random'; resetSmelt()"
            >
              🎲 随机熔炼 (高性价比)
            </button>
            <button
              class="home-tab-btn"
              type="button"
              :class="{ active: smeltMode === 'target' }"
              @click="smeltMode = 'target'; resetSmelt()"
            >
              🎯 定向熔炼 (指定产出)
            </button>
          </div>

          <div style="display:flex;gap:8px;align-items:center;margin-bottom:14px;flex-wrap:wrap">
            <span style="font-size:13px;color:var(--text-muted)">材料稀有度：</span>
            <button
              v-for="r in smeltRarities"
              :key="r"
              class="product-badge"
              type="button"
              :style="smeltRarity === r ? { background: rarityMeta[r].bg, color: rarityMeta[r].color, borderColor: rarityMeta[r].color } : {}"
              @click="smeltRarity = r; resetSmelt()"
            >
              {{ rarityMeta[r].label }} · {{ r }}
            </button>
          </div>

          <div style="font-size:13px;color:var(--text-muted);margin-bottom:14px;background:var(--bg-subtle);padding:10px 12px;border-radius:var(--radius-sm)">
            需要 <strong>{{ smeltCost }}</strong> 张 {{ smeltRarity }} 副本（已选 {{ selectedTotal }}） ➔ 产出 {{ smeltMode === 'random' ? '随机' : '定向' }} <strong>{{ nextRarityMap[smeltRarity] }}</strong> 称号
          </div>

          <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:14px">
            <span style="font-size:13px;color:var(--text-muted)">投入材料：</span>
            <span v-if="!selectedTotal" style="font-size:13px;color:var(--text-dim)">尚未放入，点击右侧按钮挑选</span>
            <span v-for="(count, titleId) in smeltSelection" :key="titleId" class="status-pill" style="display:inline-flex;align-items:center;gap:6px">
              {{ nameMap[titleId]?.name || titleId }} ×{{ count }}
              <button type="button" style="cursor:pointer;color:#dc2626;font-size:14px" @click="removeMaterial(nameMap[titleId])">✕</button>
            </span>
            <button class="btn-secondary" type="button" style="padding:4px 12px;font-size:12px" @click="openSmeltPicker">＋ 选择材料</button>
          </div>

          <div v-if="smeltMode === 'target'" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:16px">
            <span style="font-size:13px;color:var(--text-muted)">定向目标（{{ nextRarityMap[smeltRarity] }}）：</span>
            <select v-model="smeltTarget" class="input-select" style="max-width:260px">
              <option value="">请选择目标称号</option>
              <option v-for="item in targetCandidates" :key="item.id" :value="item.id">
                {{ item.name }}（现有副本×{{ item.copies }}）
              </option>
            </select>
          </div>

          <button class="btn-primary" type="button" :disabled="busy || selectedTotal !== smeltCost || (smeltMode === 'target' && !smeltTarget)" @click="doSmelt">
            🔥 开始熔炼（{{ smeltMode === 'random' ? '随机' : '定向' }}）
          </button>

          <!-- UR 配方合成 -->
          <div style="border-top:1px solid var(--border-light);margin:20px 0 16px" />
          <h3 style="font-size:15px;font-weight:700;margin-bottom:10px">至尊 UR 专属配方合成</h3>
          <div v-if="!data?.recipes?.length" style="font-size:13px;color:var(--text-dim)">暂未配置 UR 配方。</div>
          <div
            v-for="recipe in data?.recipes ?? []"
            :key="recipe.id"
            style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;padding:12px 14px;border:1px solid var(--border-light);border-radius:12px;margin-bottom:10px;background:var(--bg-subtle)"
          >
            <div>
              <div style="font-size:14px;font-weight:700;color:#b45309">👑 {{ recipeOutput(recipe)?.name || recipe.output_code }}</div>
              <div style="font-size:12px;color:var(--text-muted);margin-top:4px">
                材料需求：
                <span v-for="(code, index) in recipe.materials" :key="code + index">
                  {{ index ? ' + ' : '' }}{{ titleOfCode(code)?.name || code }}（持有 {{ titleOfCode(code)?.copies ?? 0 }}）
                </span>
              </div>
            </div>
            <button
              class="btn-primary"
              type="button"
              style="padding:6px 16px;font-size:12px"
              :disabled="busy || !recipeReady(recipe)"
              @click="doCraft(recipe)"
            >
              {{ recipeReady(recipe) ? '立即合成' : '材料不足' }}
            </button>
          </div>
        </div>

        <!-- 称号全集图鉴墙 -->
        <div class="card" style="padding:24px">
          <div class="card-header-line" style="margin-bottom:18px">
            <h2 class="card-title">称号图鉴展览室</h2>
            <span class="card-subtitle">点击拥有的称号可一键佩戴或卸下</span>
          </div>

          <div v-for="group in grouped" :key="group.rarity" style="margin-bottom:20px">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
              <span class="product-badge" :style="{ background: rarityMeta[group.rarity].bg, color: rarityMeta[group.rarity].color }">
                {{ rarityMeta[group.rarity].label }} · {{ group.rarity }}
              </span>
              <span style="font-size:12px;color:var(--text-dim)">已收集 {{ group.owned }} / {{ group.items.length }}</span>
            </div>
            <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px">
              <button
                v-for="item in group.items"
                :key="item.id"
                type="button"
                class="title-badge-card"
                :class="{
                  'is-owned': item.owned,
                  'is-equipped': data?.equipped_title_id === item.id
                }"
                :disabled="!item.owned || busy"
                @click="equip(item)"
              >
                <div class="title-badge-name">{{ item.name }}</div>
                <div class="title-badge-footer">
                  <span>{{ item.owned ? `副本 ×${item.copies}` : '🔒 未获得' }}</span>
                  <span v-if="data?.equipped_title_id === item.id" class="equipped-tag">已佩戴</span>
                </div>
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 右栏：抽卡说明与历史记录 -->
      <div>
        <div class="card" style="margin-bottom:24px">
          <h2 class="card-title" style="margin-bottom:12px">抽取机制公示</h2>
          <ul style="font-size:13px;color:var(--text-muted);line-height:1.8;margin:0;padding-left:18px">
            <li>概率：N 普通 60%，R 稀有 28%，SR 史诗 9%，SSR 传说 3%，UR 仅能通过配方合成获得。</li>
            <li>保底：十连必出 SR 及以上；百连必出 SSR；单抽无保底。</li>
            <li>特权：拥有至尊 UR 称号即享全店商品 95 折，全站通用！</li>
          </ul>
        </div>

        <div class="card">
          <div class="card-header-line" style="margin-bottom:14px">
            <h2 class="card-title">抽卡历史流水</h2>
            <span class="card-subtitle">最近 50 次</span>
          </div>
          <div class="table-wrap" style="max-height:480px">
            <table class="data-table">
              <thead>
                <tr><th>时间</th><th>称号</th><th>稀有度</th><th>状态</th></tr>
              </thead>
              <tbody>
                <tr v-if="!data?.history?.draws?.length"><td colspan="4" class="empty-cell">还没有抽卡记录，快去试一发吧。</td></tr>
                <tr v-for="item in data?.history?.draws ?? []" :key="item.id">
                  <td>{{ displayTime(item.created_at) }}</td>
                  <td style="font-weight:600">{{ nameMap[item.title_id]?.name || item.title_id }}</td>
                  <td>
                    <span class="product-badge" :style="{ background: rarityMeta[item.rarity].bg, color: rarityMeta[item.rarity].color, fontSize: '11px' }">
                      {{ rarityMeta[item.rarity].label }}
                    </span>
                  </td>
                  <td>{{ item.is_new ? '✨ 新获得' : '重复副本' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  </main>

  <!-- 熔炼选材弹窗 -->
  <dialog ref="smeltDialog" class="dialog-modal">
    <div style="width:min(640px,86vw)">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
        <h2 style="font-size:18px;font-weight:700;margin:0">挑选熔炼材料 · {{ smeltRarity }}</h2>
        <span style="font-size:13px;color:var(--text-muted)">已选 {{ selectedTotal }} / {{ smeltCost }}</span>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px;max-height:55vh;overflow:auto;padding:2px">
        <button
          v-for="item in smeltCandidates"
          :key="item.id"
          type="button"
          class="title-badge-card is-owned"
          :style="{
            borderColor: (smeltSelection[item.id] ?? 0) > 0 ? rarityMeta[item.rarity].color : undefined,
            background: (smeltSelection[item.id] ?? 0) > 0 ? rarityMeta[item.rarity].bg : undefined,
            opacity: (smeltSelection[item.id] ?? 0) >= item.available ? 0.5 : 1
          }"
          :disabled="(smeltSelection[item.id] ?? 0) >= item.available"
          @click="addMaterial(item)"
        >
          <div class="title-badge-name">{{ item.name }}</div>
          <div class="title-badge-footer">
            <span>可用 {{ item.available }}</span>
            <span v-if="(smeltSelection[item.id] ?? 0) > 0" style="color:var(--primary);font-weight:700">
              已选 ×{{ smeltSelection[item.id] }}
            </span>
          </div>
        </button>
      </div>
      <div style="display:flex;justify-content:flex-end;gap:10px;margin-top:18px">
        <button class="btn-primary" type="button" @click="smeltDialog?.close()">完成选择</button>
      </div>
    </div>
  </dialog>

  <div v-if="notice" class="toast-notice" role="status" aria-live="polite">{{ notice }}</div>
</template>

<style scoped>
.ticket-stat-box {
  padding: 14px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-card);
}
.draw-result-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
  gap: 10px;
}
.draw-card-item {
  position: relative;
  padding: 12px 10px;
  border-radius: var(--radius-sm);
  text-align: center;
  border: 1.5px solid var(--border);
  background: var(--bg-card);
  animation: cardFlipIn 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}
@keyframes cardFlipIn {
  from { opacity: 0; transform: scale(0.8) rotateY(60deg); }
  to { opacity: 1; transform: scale(1) rotateY(0); }
}
.draw-card-item.rarity-ur { border-color: #f59e0b; background: rgba(254, 243, 199, 0.3); box-shadow: 0 0 12px rgba(245, 158, 11, 0.4); }
.draw-card-item.rarity-ssr { border-color: #8b5cf6; background: rgba(237, 233, 254, 0.3); box-shadow: 0 0 10px rgba(139, 92, 246, 0.3); }
.draw-card-item.rarity-sr { border-color: #3b82f6; background: rgba(219, 234, 254, 0.3); }
.draw-card-item.rarity-r { border-color: #10b981; background: rgba(209, 250, 229, 0.3); }
.draw-card-rarity { font-size: 11px; font-weight: 800; opacity: 0.8; margin-bottom: 2px; }
.draw-card-name { font-size: 13px; font-weight: 700; color: var(--text-main); }
.draw-card-new { position: absolute; top: -6px; right: -6px; background: #dc2626; color: #fff; font-size: 9px; font-weight: 900; padding: 2px 5px; border-radius: var(--radius-pill); }

.title-badge-card {
  padding: 12px 14px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--bg-card);
  text-align: left;
  cursor: pointer;
  transition: all 0.2s ease;
  opacity: 0.45;
}
.title-badge-card.is-owned {
  opacity: 1;
}
.title-badge-card.is-owned:hover {
  border-color: var(--primary-border);
  transform: translateY(-2px);
  box-shadow: var(--shadow-sm);
}
.title-badge-card.is-equipped {
  border-color: var(--primary);
  background: var(--primary-light);
  box-shadow: 0 0 12px rgba(20, 184, 166, 0.3);
}
.title-badge-name {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-main);
  margin-bottom: 4px;
}
.title-badge-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
  color: var(--text-dim);
}
.equipped-tag {
  color: var(--primary);
  font-weight: 700;
}
.empty-cell{text-align:center;color:var(--text-dim);padding:24px 16px}
</style>
