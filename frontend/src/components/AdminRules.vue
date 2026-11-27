<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import type { AdminVisit, RewardTier, Settings } from '../api'
import { fmtTime } from './adminFormat'

type BaseSettings = Pick<Settings, 'deadline' | 'min_step_seconds' | 'condition_url'>

const props = defineProps<{ settings: Settings; visits: AdminVisit[]; busy: boolean }>()
const emit = defineEmits<{
  saveBase: [value: BaseSettings]
  saveRewards: [tiers: RewardTier[]]
  saveNoPayout: [ids: string[]]
  review: [visit: AdminVisit]
}>()

// ── 基础参数 ──
const base = reactive<BaseSettings>({ deadline: '', min_step_seconds: 8, condition_url: '' })
const baseDirty = computed(() =>
  base.deadline !== props.settings.deadline
  || base.min_step_seconds !== props.settings.min_step_seconds
  || (base.condition_url || '') !== (props.settings.condition_url || ''),
)
function resetBase(): void {
  Object.assign(base, {
    deadline: props.settings.deadline,
    min_step_seconds: props.settings.min_step_seconds,
    condition_url: props.settings.condition_url || '',
  })
}

// ── 奖励档位 ──
const tiers = ref<RewardTier[]>([])
const tiersDirty = computed(() => JSON.stringify(tiers.value) !== JSON.stringify(props.settings.reward_tiers))
const tierError = computed(() => {
  const list = tiers.value
  if (list.some((t, i) => !Number.isInteger(t.through) || t.through < 1 || (i > 0 && t.through <= list[i - 1]!.through))) {
    return '截止名次须为递增的正整数'
  }
  if (list.some((t) => !Number.isInteger(t.amount) || t.amount < 0 || t.amount > 100000000)) {
    return '每人积分须为 0 至 100000000 的整数'
  }
  return ''
})
function resetTiers(): void {
  tiers.value = props.settings.reward_tiers.map((t) => ({ ...t }))
}
function addTier(): void {
  const last = tiers.value[tiers.value.length - 1]
  tiers.value.push({ through: (last?.through ?? 0) + 10, amount: 0 })
}
function tierRange(index: number): string {
  const from = index === 0 ? 1 : tiers.value[index - 1]!.through + 1
  return `第 ${from} – ${tiers.value[index]!.through} 名`
}

// ── 不发货名单 ──
const noPayoutText = ref('')
const parsedIds = computed(() => [...new Set(noPayoutText.value.split(/[\s,，]+/).filter(Boolean))])
const noPayoutDirty = computed(() => {
  const saved = [...(props.settings.no_payout_user_ids ?? [])].sort().join(',')
  return [...parsedIds.value].sort().join(',') !== saved
})
const noPayoutError = computed(() => {
  if (parsedIds.value.some((id) => !/^\d{1,20}$/.test(id))) return '名单只能填写纯数字的 LINUX DO 用户 ID'
  if (parsedIds.value.length > 200) return '名单最多 200 个用户'
  return ''
})
function resetNoPayout(): void {
  noPayoutText.value = (props.settings.no_payout_user_ids ?? []).join('\n')
}

watch(() => props.settings, () => {
  resetBase()
  resetTiers()
  resetNoPayout()
}, { immediate: true })

// ── 访问审核 ──
const visitFilter = ref<'all' | 'flagged'>('flagged')
const flaggedCount = computed(() => props.visits.filter((v) => v.reason && !v.approved).length)
const shownVisits = computed(() =>
  visitFilter.value === 'flagged' ? props.visits.filter((v) => v.reason && !v.approved) : props.visits,
)
</script>

<template>
  <div class="adm-grid c2" style="align-items: start">
    <!-- 基础参数 -->
    <div class="adm-card">
      <div class="adm-card-head">
        <div><h3>基础参数</h3><p class="sub">控制每日开放时间与单次练习时长</p></div>
        <span v-if="baseDirty" class="adm-tag warn">有未保存的更改</span>
      </div>
      <form class="adm-card-body adm-form" @submit.prevent="emit('saveBase', { ...base })">
        <div class="adm-row2">
          <div class="adm-field">
            <label for="r-deadline">最晚开放时间</label>
            <input id="r-deadline" v-model="base.deadline" class="adm-input" type="time" required>
          </div>
          <div class="adm-field">
            <label for="r-step">每次最短秒数</label>
            <input id="r-step" v-model.number="base.min_step_seconds" class="adm-input" type="number" min="1" max="300" required>
          </div>
        </div>
        <div class="adm-field">
          <label for="r-url">提前开放条件 URL（可选）</label>
          <input id="r-url" v-model.trim="base.condition_url" class="adm-input" type="url" placeholder="https://example.com/checkin-condition">
          <span class="help">该地址返回 <code>{"open": true}</code> 时自动提前开放今日打卡。</span>
        </div>
        <div class="adm-actions">
          <button class="adm-btn ghost" type="button" :disabled="!baseDirty || busy" @click="resetBase">还原</button>
          <button class="adm-btn primary" type="submit" :disabled="!baseDirty || busy">保存</button>
        </div>
      </form>
    </div>

    <!-- 排名奖励 -->
    <div class="adm-card">
      <div class="adm-card-head">
        <div><h3>排名奖励</h3><p class="sub">按截止名次递增，未覆盖的名次没有奖励（保存需二级密码）</p></div>
        <span v-if="tiersDirty" class="adm-tag warn">有未保存的更改</span>
      </div>
      <form class="adm-card-body adm-form" @submit.prevent="emit('saveRewards', tiers.map((t) => ({ ...t })))">
        <div>
          <div v-if="!tiers.length" class="adm-empty" style="padding: 16px">暂无档位，所有名次都没有奖励</div>
          <div v-for="(tier, index) in tiers" :key="index" class="adm-tier">
            <div class="adm-field">
              <label class="range">{{ tier.through >= 1 ? tierRange(index) : '截止名次' }}</label>
              <input v-model.number="tier.through" class="adm-input" type="number" min="1" required aria-label="截止名次">
            </div>
            <div class="adm-field">
              <label>每人积分</label>
              <input v-model.number="tier.amount" class="adm-input" type="number" min="0" max="100000000" required aria-label="奖励积分">
            </div>
            <button class="adm-btn danger sm" type="button" style="margin-bottom: 4px" aria-label="移除档位" @click="tiers.splice(index, 1)">移除</button>
          </div>
        </div>
        <p v-if="tiersDirty && tierError" class="adm-err" role="alert">{{ tierError }}</p>
        <div class="adm-actions">
          <button class="adm-btn" type="button" @click="addTier">+ 添加档位</button>
          <span style="flex: 1" />
          <button class="adm-btn ghost" type="button" :disabled="!tiersDirty || busy" @click="resetTiers">还原</button>
          <button class="adm-btn primary" type="submit" :disabled="!tiersDirty || !!tierError || busy">保存</button>
        </div>
      </form>
    </div>

    <!-- 访问审核 -->
    <div class="adm-card">
      <div class="adm-card-head">
        <div><h3>访问频率与异常审核</h3><p class="sub">周期性定时访问等模式会被自动标记，需人工确认</p></div>
        <div class="adm-seg">
          <button type="button" :class="{ on: visitFilter === 'flagged' }" @click="visitFilter = 'flagged'">待审核 <em>{{ flaggedCount }}</em></button>
          <button type="button" :class="{ on: visitFilter === 'all' }" @click="visitFilter = 'all'">全部 <em>{{ visits.length }}</em></button>
        </div>
      </div>
      <div class="adm-tablewrap" style="margin-top: 12px; max-height: 340px">
        <table class="adm-table">
          <thead><tr><th>用户</th><th>次数</th><th>原因</th><th class="r">操作</th></tr></thead>
          <tbody>
            <tr v-if="!shownVisits.length">
              <td colspan="4" class="adm-empty">{{ visitFilter === 'flagged' ? '没有待审核的访问' : '今日暂无访问记录' }}</td>
            </tr>
            <tr v-for="visit in shownVisits" :key="visit.user_id" :class="{ flag: visit.reason && !visit.approved }">
              <td>
                <b>{{ visit.username ? '@' + visit.username : '匿名访客' }}</b>
                <div class="muted" style="font-size: 12px">{{ fmtTime(visit.last_seen) }}</div>
              </td>
              <td class="nowrap">{{ visit.count }} 次</td>
              <td>{{ visit.reason || '正常访问' }}</td>
              <td class="r">
                <button v-if="visit.reason && !visit.approved" class="adm-btn sm" type="button" :disabled="busy" @click="emit('review', visit)">批准</button>
                <span v-else class="adm-tag" :class="visit.approved ? 'ok' : 'plain'">{{ visit.approved ? '已批准' : '正常' }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 不发货名单 -->
    <div class="adm-card">
      <div class="adm-card-head">
        <div><h3>不发货名单</h3><p class="sub">名单内用户的兑换订单显示成功但不调用 Credit 转账；每日打卡榜中置灰且不占名次，自己的积分奖励不变（保存需二级密码）</p></div>
        <span v-if="noPayoutDirty" class="adm-tag warn">有未保存的更改</span>
      </div>
      <form class="adm-card-body adm-form" @submit.prevent="emit('saveNoPayout', parsedIds)">
        <div class="adm-field">
          <label for="r-nopay">用户 ID（每行一个，当前 {{ parsedIds.length }} / 200）</label>
          <textarea id="r-nopay" v-model="noPayoutText" class="adm-textarea mono" rows="6" spellcheck="false" placeholder="317545" />
        </div>
        <p v-if="noPayoutError" class="adm-err" role="alert">{{ noPayoutError }}</p>
        <div class="adm-actions">
          <button class="adm-btn ghost" type="button" :disabled="!noPayoutDirty || busy" @click="resetNoPayout">还原</button>
          <button class="adm-btn primary" type="submit" :disabled="!noPayoutDirty || !!noPayoutError || busy">保存名单</button>
        </div>
      </form>
    </div>
  </div>
</template>
