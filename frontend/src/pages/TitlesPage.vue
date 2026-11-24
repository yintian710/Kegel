<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError, loginUrl, titles as titlesApi, type DrawData, type Rarity, type TicketType, type TitleData, type TitleItem } from '../api'
import { useBodyAttributes } from '../composables/useBodyAttributes'
import { useIdentity } from '../composables/useIdentity'

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
const ticketMeta: Array<{ type: TicketType; label: string; draws: number }> = [
  { type: 'single', label: '单抽券', draws: 1 },
  { type: 'ten', label: '十连券', draws: 10 },
  { type: 'hundred', label: '百连券', draws: 100 },
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
const smeltCost = computed(() => smeltCostMap[smeltRarity.value][smeltMode.value])
const smeltCandidates = computed(() => (data.value?.collection ?? [])
  .filter((item) => item.rarity === smeltRarity.value && availableOf(item) > 0)
  .map((item) => ({ ...item, available: availableOf(item) })))
const selectedTotal = computed(() => Object.values(smeltSelection.value).reduce((sum, n) => sum + n, 0))
const targetCandidates = computed(() => (data.value?.collection ?? []).filter((item) => item.rarity === nextRarityMap[smeltRarity.value]))

function availableOf(item: TitleItem): number {
  return item.copies - (data.value?.equipped_title_id === item.id ? 1 : 0)
}
function resetSmelt(): void { smeltSelection.value = {}; smeltTarget.value = '' }
function addMaterial(item: TitleItem): void {
  const current = smeltSelection.value[item.id] ?? 0
  if (current >= availableOf(item)) return
  smeltSelection.value = { ...smeltSelection.value, [item.id]: current + 1 }
}
function subMaterial(item: TitleItem): void {
  const current = smeltSelection.value[item.id] ?? 0
  if (current <= 0) return
  const next = { ...smeltSelection.value }
  if (current <= 1) delete next[item.id]
  else next[item.id] = current - 1
  smeltSelection.value = next
}
function removeMaterial(item: TitleItem): void {
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
    notify(`🎴 抽卡完成，共 ${result.batch.count} 抽，最高稀有度：${rarityMeta[top].label}`)
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
    notify(`🔥 熔炼成功，获得${rarityMeta[result.output.rarity].label}「${nameMap[result.output.title_id]?.name || '称号'}」${result.output.is_new ? '（新）' : '（副本）'}`)
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
    const materials = Object.entries(recipeNeed(recipe)).map(([code, count]) => ({ title_id: codeMap.value[code].id, count }))
    const result = await titlesApi.craft({ recipe_id: recipe.id, materials, request_id: newRequestId() })
    notify(`✨ 合成成功，获得至尊「${nameMap[result.output.title_id]?.name || 'UR'}」`)
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
        <div><h1>称号抽卡</h1><p>用抽卡券抽取称号，收集图鉴、熔炼合成，至尊 UR 可解锁 LDC 兑换 95 折。</p></div>
        <RouterLink class="btn-primary" to="/shop" style="background:#fff;color:var(--primary);border:1px solid var(--primary-border);box-shadow:var(--shadow-sm)">去商店 ↗</RouterLink>
      </div>
    </div>

    <div class="card" style="margin-bottom:20px">
      <div class="card-header-line"><h2 class="card-title">我的抽卡状态</h2><span class="card-subtitle">{{ data?.user ? `当前账号：@${data.user.username}` : '登录后可用' }}</span></div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:12px;margin-bottom:14px">
        <div style="padding:12px;border:1px solid var(--border-light);border-radius:12px"><div style="font-size:12px;color:var(--text-muted)">积分余额</div><div style="font-size:22px;font-weight:800">{{ wallet.toLocaleString() }}</div></div>
        <div v-for="t in ticketMeta" :key="t.type" style="padding:12px;border:1px solid var(--border-light);border-radius:12px">
          <div style="font-size:12px;color:var(--text-muted)">{{ t.label }}（{{ t.draws }} 抽）</div>
          <div style="font-size:22px;font-weight:800">{{ data?.tickets?.[t.type] ?? 0 }}</div>
        </div>
      </div>
      <div style="font-size:13px;color:var(--text-muted)">保底规则：<strong>十连必出 SR 及以上</strong>；<strong>百连必出 SSR</strong>；单抽无保底。</div>
    </div>

    <div class="shop-columns">
      <div>
        <div class="card" style="margin-bottom:20px">
          <h2 class="card-title" style="margin-bottom:12px">抽卡</h2>
          <div style="display:flex;gap:12px;flex-wrap:wrap">
            <button v-for="t in ticketMeta" :key="t.type" class="btn-primary" type="button" :disabled="busy || (data?.tickets?.[t.type] ?? 0) < 1" @click="draw(t.type)">
              {{ t.label }}抽 {{ t.draws }} 次（持有 {{ data?.tickets?.[t.type] ?? 0 }}）
            </button>
          </div>
          <p style="font-size:12px;color:var(--text-dim);margin:14px 0 0">抽卡只消耗对应券；三种券各自整用，不可拆分或混用。</p>
          <div v-if="results.length" style="margin-top:16px">
            <div style="font-size:13px;font-weight:700;margin-bottom:8px">本次结果</div>
            <div style="display:flex;flex-wrap:wrap;gap:8px">
              <div v-for="(item, index) in results" :key="index" :style="{ background: rarityMeta[item.rarity].bg, color: rarityMeta[item.rarity].color }" style="padding:8px 10px;border-radius:10px;font-size:12px;font-weight:700">
                <span>{{ rarityMeta[item.rarity].label }}</span>
                <span style="margin-left:6px">{{ nameMap[item.title_id]?.name || '未知称号' }}</span>
                <span v-if="item.is_new" style="margin-left:6px;background:#111;color:#fff;border-radius:6px;padding:0 4px">NEW</span>
              </div>
            </div>
          </div>
        </div>

        <div class="card" style="margin-top:20px">
          <h2 class="card-title" style="margin-bottom:12px">熔炼与合成</h2>

          <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">
            <button class="btn-secondary" type="button" :style="smeltMode === 'random' ? { borderColor: 'var(--primary)', color: 'var(--primary)' } : {}" @click="smeltMode = 'random'; resetSmelt()">随机熔炼</button>
            <button class="btn-secondary" type="button" :style="smeltMode === 'target' ? { borderColor: 'var(--primary)', color: 'var(--primary)' } : {}" @click="smeltMode = 'target'; resetSmelt()">定向熔炼</button>
          </div>

          <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:10px">
            <span style="font-size:13px;color:var(--text-muted)">材料稀有度：</span>
            <button v-for="r in smeltRarities" :key="r" class="product-badge" type="button" :style="smeltRarity === r ? { background: rarityMeta[r].bg, color: rarityMeta[r].color, borderColor: rarityMeta[r].color } : {}" @click="smeltRarity = r; resetSmelt()">{{ rarityMeta[r].label }} · {{ r }}</button>
          </div>

          <div style="font-size:13px;color:var(--text-muted);margin-bottom:10px">需要 <strong>{{ smeltCost }}</strong> 张 {{ smeltRarity }} 材料（已选 {{ selectedTotal }}）→ 产出 {{ smeltMode === 'random' ? '随机' : '指定' }} {{ nextRarityMap[smeltRarity] }}</div>

          <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:12px">
            <span style="font-size:13px;color:var(--text-muted)">已选材料：</span>
            <span v-if="!selectedTotal" style="font-size:13px;color:var(--text-dim)">尚未选择，点击右侧按钮挑选</span>
            <span v-for="(count, titleId) in smeltSelection" :key="titleId" style="display:flex;align-items:center;gap:6px;border:1px solid var(--border-light);border-radius:10px;padding:4px 8px;font-size:12px;font-weight:700">
              {{ nameMap[titleId]?.name || titleId }} ×{{ count }}
              <button class="btn-secondary" type="button" style="padding:0 6px" @click="removeMaterial(nameMap[titleId])">×</button>
            </span>
            <button class="btn-secondary" type="button" style="padding:4px 12px" @click="openSmeltPicker">＋ 选择材料</button>
          </div>

          <div v-if="smeltMode === 'target'" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px">
            <span style="font-size:13px;color:var(--text-muted)">定向目标（{{ nextRarityMap[smeltRarity] }}）：</span>
            <select v-model="smeltTarget" style="padding:6px 10px;border:1px solid var(--border-light);border-radius:8px;background:#fff">
              <option value="">请选择目标</option>
              <option v-for="item in targetCandidates" :key="item.id" :value="item.id">{{ item.name }}（副本×{{ item.copies }}）</option>
            </select>
          </div>

          <button class="btn-primary" type="button" :disabled="busy || selectedTotal !== smeltCost || (smeltMode === 'target' && !smeltTarget)" @click="doSmelt">熔炼（{{ smeltMode === 'random' ? '随机' : '定向' }}）</button>

          <div style="border-top:1px solid var(--border-light);margin:18px 0"></div>
          <div style="font-size:13px;font-weight:700;margin-bottom:8px">UR 合成</div>
          <div v-if="!data?.recipes?.length" style="font-size:13px;color:var(--text-dim)">暂未配置 UR 配方。</div>
          <div v-for="recipe in data?.recipes ?? []" :key="recipe.id" style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;padding:10px;border:1px solid var(--border-light);border-radius:10px;margin-bottom:8px">
            <div>
              <div style="font-size:13px;font-weight:700">{{ recipeOutput(recipe)?.name || recipe.output_code }}</div>
              <div style="font-size:12px;color:var(--text-dim);margin-top:4px">
                需要：<span v-for="(code, index) in recipe.materials" :key="code + index">{{ index ? ' + ' : '' }}{{ codeMap[code]?.name || code }}（有 {{ codeMap[code]?.copies ?? 0 }}）</span>
              </div>
            </div>
            <button class="btn-primary" type="button" style="padding:6px 14px;font-size:13px" :disabled="busy || !recipeReady(recipe)" @click="doCraft(recipe)">{{ recipeReady(recipe) ? '合成' : '材料不足' }}</button>
          </div>
        </div>

        <details class="card card-collapse" open style="margin-top:20px">
          <summary class="collapse-summary"><h2 class="card-title">称号图鉴 <span class="card-subtitle">按稀有度分组</span></h2><span class="collapse-chevron">⌄</span></summary>
          <div class="collapse-body">
            <div v-for="group in grouped" :key="group.rarity" style="margin-bottom:14px">
              <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
                <span class="product-badge" :style="{ background: rarityMeta[group.rarity].bg, color: rarityMeta[group.rarity].color }">{{ rarityMeta[group.rarity].label }} · {{ group.rarity }}</span>
                <span style="font-size:12px;color:var(--text-dim)">已拥有 {{ group.owned }} / {{ group.items.length }}</span>
              </div>
              <div style="display:flex;flex-wrap:wrap;gap:8px">
                <button v-for="item in group.items" :key="item.id" type="button" :disabled="!item.owned" @click="equip(item)"
                  :style="{ borderColor: item.owned ? rarityMeta[item.rarity].color : '#e5e7eb', opacity: item.owned ? 1 : .55, background: item.owned ? rarityMeta[item.rarity].bg : '#f8fafc' }"
                  style="border:1.5px solid;border-radius:10px;padding:8px 10px;min-width:110px;text-align:left;cursor:pointer">
                  <div style="font-size:12px;font-weight:700" :style="{ color: item.owned ? rarityMeta[item.rarity].color : '#9ca3af' }">{{ item.owned ? item.name : '未获得' }}</div>
                  <div style="font-size:11px;color:var(--text-dim);margin-top:2px">{{ item.owned ? `副本 ×${item.copies}` : '—' }}<span v-if="data?.equipped_title_id === item.id"> · 已装备</span></div>
                </button>
              </div>
            </div>
          </div>
        </details>

        <details class="card card-collapse" open style="margin-top:20px">
          <summary class="collapse-summary"><h2 class="card-title">抽卡记录 <span class="card-subtitle">最近 50 次</span></h2><span class="collapse-chevron">⌄</span></summary>
          <div class="collapse-body"><div class="table-wrap" style="max-height:340px"><table class="data-table"><thead><tr><th>时间</th><th>称号</th><th>稀有度</th><th>结果</th></tr></thead><tbody>
            <tr v-if="!data?.history?.draws?.length"><td colspan="4" class="empty-cell">还没有抽卡记录，先买券抽一发吧。</td></tr>
            <tr v-for="item in data?.history?.draws ?? []" :key="item.id"><td>{{ displayTime(item.created_at) }}</td><td>{{ nameMap[item.title_id]?.name || item.title_id }}</td><td>{{ rarityMeta[item.rarity].label }}</td><td>{{ item.is_new ? '新获得' : '重复副本' }}</td></tr>
          </tbody></table></div></div>
        </details>
      </div>

      <div>
        <div class="card">
          <h2 class="card-title" style="margin-bottom:10px">抽卡券购买</h2>
          <p style="font-size:13px;color:var(--text-muted);line-height:1.7;margin:0 0 14px">抽卡券和 LDC 一样属于商店商品，只是品类不同；请到「商店」购买单抽券 / 十连券 / 百连券。</p>
          <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px">
            <span v-for="t in ticketMeta" :key="t.type" class="product-badge">{{ t.label }} ×{{ data?.tickets?.[t.type] ?? 0 }}</span>
          </div>
          <RouterLink class="btn-primary" to="/shop">前往商店购买抽卡券 →</RouterLink>
        </div>

        <div class="card" style="margin-top:20px">
          <h2 class="card-title" style="margin-bottom:10px">概率公示</h2>
          <ul style="font-size:13px;color:var(--text-muted);line-height:1.8;margin:0;padding-left:18px">
            <li>N 普通 60%，R 稀有 28%，SR 史诗 9%，SSR 传说 3%，UR 仅合成获得。</li>
            <li>保底：十连必出 SR 及以上；百连必出 SSR；单抽及其他无保底。</li>
            <li>称号不可交易、赠送或兑换积分；UR 拥有即享 LDC 兑换 95 折。</li>
          </ul>
        </div>
      </div>
    </div>
  </main>
  <dialog ref="smeltDialog" class="dialog-modal">
    <div style="width:min(720px,86vw)">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
        <h2 style="font-size:18px;font-weight:700;margin:0">选择熔炼材料 · {{ smeltRarity }}</h2>
        <span style="font-size:13px;color:var(--text-muted)">已选 {{ selectedTotal }} / {{ smeltCost }}</span>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px;max-height:60vh;overflow:auto">
        <button v-for="item in smeltCandidates" :key="item.id" type="button" :disabled="(smeltSelection[item.id] ?? 0) >= item.available" @click="addMaterial(item)"
          :style="{ borderColor: (smeltSelection[item.id] ?? 0) > 0 ? rarityMeta[item.rarity].color : '#e5e7eb', background: (smeltSelection[item.id] ?? 0) > 0 ? rarityMeta[item.rarity].bg : '#fff', opacity: (smeltSelection[item.id] ?? 0) >= item.available ? .5 : 1 }"
          style="border:1.5px solid;border-radius:10px;padding:10px;text-align:left;cursor:pointer">
          <div style="font-size:13px;font-weight:700">{{ item.name }}</div>
          <div style="font-size:11px;color:var(--text-dim);margin-top:2px">可用 {{ item.available }}<span v-if="(smeltSelection[item.id] ?? 0) > 0"> · 已选 {{ smeltSelection[item.id] }}</span></div>
        </button>
      </div>
      <div style="display:flex;justify-content:flex-end;gap:10px;margin-top:16px">
        <button class="btn-secondary" type="button" @click="smeltDialog?.close()">完成</button>
      </div>
    </div>
  </dialog>
  <div v-if="notice" class="toast-notice" role="status" aria-live="polite">{{ notice }}</div>
</template>

<style scoped>
.empty-cell{text-align:center;color:var(--text-dim);padding:24px 16px}
.products-empty{grid-column:1/-1;text-align:center;padding:40px 24px;color:var(--text-dim)}
.product-footer{display:flex;justify-content:space-between;align-items:center;margin-top:auto;padding-top:12px;border-top:1px solid var(--border-light)}
</style>
