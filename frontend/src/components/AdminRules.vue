<script setup lang="ts">
import type { AdminVisit, RewardTier, Settings } from '../api'

const props = defineProps<{ settings: Settings; visits: AdminVisit[]; busy: boolean }>()
const emit = defineEmits<{ saveSettings:[value:Pick<Settings,'deadline'|'min_step_seconds'|'condition_url'>]; saveRewards:[tiers:RewardTier[]]; review:[visit:AdminVisit] }>()
const base = reactive({ deadline:'', min_step_seconds:8, condition_url:'' })
const tiers = ref<RewardTier[]>([])
watch(() => props.settings, value => { Object.assign(base, { deadline:value.deadline,min_step_seconds:value.min_step_seconds,condition_url:value.condition_url||'' }); tiers.value=value.reward_tiers.map(t=>({...t})) }, { immediate:true })
function saveRewards() {
  if (tiers.value.some((t,i)=>!Number.isInteger(t.through)||t.through<1||(i>0&&t.through<=tiers.value[i-1]!.through))) return emitInvalid('截止名次须为递增的正整数。')
  if (tiers.value.some(t=>!Number.isInteger(t.amount)||t.amount<0||t.amount>100000000)) return emitInvalid('每人站内积分须为 0 至 100000000 的整数。')
  emit('saveRewards', tiers.value.map(t=>({...t})))
}
const invalid = ref('')
function emitInvalid(text:string){ invalid.value=text; window.setTimeout(()=>invalid.value='',4000) }
</script>

<template>
<section id="sec-rules" style="margin-bottom:36px"><h2 style="font-size:20px;font-weight:700;margin:0 0 16px">规则配置</h2>
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:20px">
<details class="card card-collapse" open><summary class="collapse-summary"><h3 class="card-title">基础参数设置</h3></summary><div class="collapse-body"><form @submit.prevent="emit('saveSettings',{...base})"><div class="form-group"><label class="form-label">最晚开放时间 (HH:MM)</label><input v-model="base.deadline" class="input-text" type="time" required></div><div class="form-group"><label class="form-label">每次最短秒数 (1-300)</label><input v-model.number="base.min_step_seconds" class="input-text" type="number" min="1" max="300" required></div><div class="form-group"><label class="form-label">提前开启条件 URL (可选)</label><input v-model.trim="base.condition_url" class="input-text" type="url" placeholder="https://example.com/checkin-condition"><p style="font-size:12px;color:var(--text-dim);margin:4px 0 0">返回 {"open": true} 时自动提前开放今日打卡。</p></div><button class="btn-primary" type="submit" style="width:100%" :disabled="busy">保存基础规则</button></form></div></details>
<details class="card card-collapse" open><summary class="collapse-summary"><h3 class="card-title">排名奖励配置</h3></summary><div class="collapse-body"><p style="font-size:12px;color:var(--text-muted);margin:0 0 16px">按截止名次递增，未覆盖名次无奖励。</p><form @submit.prevent="saveRewards"><div class="table-wrap" style="max-height:280px;margin-bottom:16px"><table class="data-table"><thead><tr><th>截止名次</th><th>奖励积分</th><th>操作</th></tr></thead><tbody><tr v-for="(tier,index) in tiers" :key="index"><td><input v-model.number="tier.through" class="input-text" type="number" min="1" required style="padding:6px 8px"></td><td><input v-model.number="tier.amount" class="input-text" type="number" min="0" max="100000000" required style="padding:6px 8px"></td><td><button class="btn-secondary" type="button" :disabled="busy" @click="tiers.splice(index,1)">移除</button></td></tr></tbody></table></div><p v-if="invalid" style="color:#dc2626;font-size:13px">{{ invalid }}</p><div style="display:flex;gap:10px"><button class="btn-secondary" type="button" style="flex:1" :disabled="busy" @click="tiers.push({through:0,amount:0})">添加档位</button><button class="btn-primary" type="submit" style="flex:1" :disabled="busy">保存奖励设置</button></div></form></div></details>
<details class="card card-collapse" open><summary class="collapse-summary"><h3 class="card-title">访问频率与异常审核</h3></summary><div class="collapse-body"><p style="font-size:12px;color:var(--text-muted);margin:0 0 16px">周期性定时访问等模式会被自动标记，需人工确认。</p><div class="table-wrap" style="max-height:320px"><table class="data-table"><thead><tr><th>用户</th><th>次数</th><th>原因</th><th>操作</th></tr></thead><tbody><tr v-if="!visits.length"><td colspan="4" style="text-align:center">今日暂无访问记录。</td></tr><tr v-for="visit in visits" :key="visit.user_id"><td>{{ visit.username?`@${visit.username}`:`访客 (${visit.user_id})` }}</td><td>{{ visit.count }} 次</td><td>{{ visit.reason||'正常访问' }}</td><td><button v-if="visit.reason&&!visit.approved" class="btn-secondary" type="button" :disabled="busy" @click="emit('review',visit)">批准通过</button><template v-else>{{ visit.approved?'已批准':'正常' }}</template></td></tr></tbody></table></div></div></details>
</div></section>
</template>
