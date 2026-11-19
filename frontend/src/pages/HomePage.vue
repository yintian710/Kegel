<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { claim, loginUrl, session as sessionApi, status as getStatus, visit, type CheckinEntry, type Session, type StatusData } from '../api'
import { useBodyAttributes } from '../composables/useBodyAttributes'
import { ft, preferenceQuery } from '../composables/usePreferences'

useBodyAttributes({ class: 'stage-wrap', data: { step: '0' } })

type CompletionKind = 'server' | 'anonymous' | 'review' | 'closed' | null
const started = ref(false)
const busy = ref(false)
const polling = ref(false)
const statusData = ref<StatusData | null>(null)
const activeSession = ref<Session | null>(null)
const entry = ref<CheckinEntry | null>(null)
const step = ref(0)
const readyAt = ref(0)
const expiresAt = ref(0)
const showResult = ref(false)
const completionKind = ref<CompletionKind>(null)
const notice = ref('')
const footerError = ref('')
const now = ref(Date.now())
const shownView = ref<'landing' | 'prompt' | 'completed'>('landing')
const promptText = ref<string | null>(null)
const contentEl = ref<HTMLElement | null>(null)
const promptEl = ref<HTMLElement | null>(null)
let noticeTimer: number | undefined
let timer: number | undefined
let pollTimer: number | undefined
let unmounted = false

const repetitions = computed(() => {
  const value = Number(activeSession.value?.repetitions)
  return Number.isInteger(value) && value >= 1 && value <= 20 ? value : 3
})
const completed = computed(() => showResult.value || Boolean(activeSession.value?.completed) || Boolean(activeSession.value && activeSession.value.step >= repetitions.value))
const remaining = computed(() => activeSession.value ? Math.max(0, Math.ceil((readyAt.value - now.value) / 1000)) : 0)
const targetPrompt = computed<string | null>(() => {
  if (!started.value) return null
  if (!activeSession.value) return '开始第 1 次？'
  if (step.value >= repetitions.value - 1) return '最后一次，加油！'
  return `开始第 ${step.value + 2} 次？`
})
const fadeSeconds = computed(() => (Number(activeSession.value?.interval_seconds ?? activeSession.value?.min_seconds ?? statusData.value?.min_step_seconds) || 2) / 2)
const hint = computed(() => {
  if (!started.value) return '点击任意位置开始'
  if (busy.value) return '正在记录，请稍候…'
  if (!activeSession.value) return '点击页面或按任意键，开始第 1 次'
  if (remaining.value > 0) return '轻轻收紧，缓慢放松 · 本次还剩 '
  if (step.value < repetitions.value - 1) return `点击页面或按任意键，开始第 ${step.value + 2} 次`
  return `${repetitions.value} 次完成，正在确认记录…`
})
const footerNote = computed(() => {
  if (footerError.value) return footerError.value
  const value = statusData.value
  if (!value) return ''
  const opening = value.review && !value.review.approved ? '今日访问待管理员确认 · 可以先练习' : value.is_open ? `今日打卡已开放 · ${value.total} 人完成` : `今日尚未开放 · 最晚 ${value.deadline} 北京时间开启`
  return `${opening} · 今日 LDC 兑换额度剩余 ${value.quota.remaining} LDC`
})
const completionSummary = computed(() => {
  if (entry.value) return { titlePrefix: '今日第 ', rank: String(entry.value.rank), titleSuffix: ' 位', rewardPrefix: '本次奖励 ', amount: String(entry.value.amount), rewardSuffix: ' 站内积分' }
  if (completionKind.value === 'closed') return { titlePrefix: '今日打卡操作完成', rank: '', titleSuffix: '', rewardPrefix: '打卡尚未开放，本次操作不计入正式排名。', amount: '', rewardSuffix: '' }
  if (completionKind.value === 'review') return { titlePrefix: '今日练习完成', rank: '', titleSuffix: '', rewardPrefix: '今日访问需要管理员确认，暂不计奖励排名。', amount: '', rewardSuffix: '' }
  return { titlePrefix: '今日练习完成', rank: '', titleSuffix: '', rewardPrefix: '本次访客练习已完成，登录后可参与每日正式排名。', amount: '', rewardSuffix: '' }
})
const rewardNote = computed(() => {
  if (entry.value?.reward_status === 'credited') return '今日打卡奖励已成功记入站内积分钱包。'
  if (entry.value?.reward_status === 'none') return '已记录今日排名，本名次无站内积分奖励。'
  if (entry.value?.reward_status === 'unclaimed') return '签到积分领取不受每日 LDC 兑换额度限制。'
  if (completionKind.value === 'closed') return `每日最晚 ${statusData.value?.deadline || '22:00'}（北京时间）开放，也可能提前开启。`
  if (completionKind.value === 'review') return '请联系管理员确认访问记录。批准后刷新页面，开始正式打卡。'
  return '访客操作不会生成正式打卡记录或积分。'
})
const statusPill = computed(() => entry.value?.reward_status === 'credited' ? '已记入钱包' : entry.value?.reward_status === 'none' ? '打卡已记录' : '')
const quotaPercent = computed(() => {
  const quota = statusData.value?.quota
  const limit = Number(quota?.limit || 0)
  return limit > 0 ? Math.min(100, Math.round(Number(quota?.used || 0) / limit * 100)) : 0
})
const rewardRules = computed(() => {
  let start = 1
  const rules = (statusData.value?.reward_tiers || []).map(tier => {
    const label = start === tier.through ? `第 ${start} 名` : `第 ${start} - ${tier.through} 名`
    start = tier.through + 1
    return { label, value: `${tier.amount} 积分`, rewarded: true }
  })
  rules.push({ label: `第 ${start} 名起`, value: '无积分', rewarded: false })
  return rules
})

function errorMessage(error: unknown): string { return error instanceof Error ? error.message : '请求失败，请稍后重试。' }
function notify(message: string): void {
  notice.value = message
  if (noticeTimer !== undefined) window.clearTimeout(noticeTimer)
  noticeTimer = window.setTimeout(() => { notice.value = '' }, 4000)
}
function reset(message?: string): void {
  activeSession.value = null; step.value = 0; readyAt.value = 0; expiresAt.value = 0; showResult.value = false; completionKind.value = null
  if (statusData.value) statusData.value.session = null
  if (message && started.value) notify(message)
}
function applySession(value: Session): void {
  now.value = Date.now()
  const same = activeSession.value?.token === value.token
  activeSession.value = value
  step.value = Math.max(0, Math.min(Number(value.repetitions) || 3, Number(value.step) || 0))
  const nextReady = Date.now() + Math.max(0, Number(value.wait_seconds) || 0) * 1000
  readyAt.value = same ? Math.min(readyAt.value, nextReady) : nextReady
  expiresAt.value = value.expires_in === null ? 0 : Date.now() + Math.max(0, Number(value.expires_in) || 0) * 1000
  completionKind.value = value.eligible ? 'server' : !statusData.value?.user ? 'anonymous' : statusData.value.review ? 'review' : 'closed'
  showResult.value = Boolean(value.completed) || value.step >= value.repetitions
}
function applyStatus(value: StatusData): void {
  const previousDay = statusData.value?.day
  statusData.value = value
  if (value.session && (value.session.mode !== 'manual' || value.session.repetitions !== 3)) value.session = null
  if (previousDay && previousDay !== value.day) { entry.value = null; reset('新的一天开始了，点击页面开始今天的练习。') }
  if (value.entry) entry.value = value.entry
  if (started.value && value.session && !value.session.completed && value.session.step < value.session.repetitions) applySession(value.session)
  else if (started.value && activeSession.value && !completed.value) reset('十分钟未进入下一次，本轮已失效，请从第一次重新开始。')
}
async function pollStatus(): Promise<void> {
  if (!started.value || busy.value || polling.value || document.hidden) return
  polling.value = true
  try { applyStatus(await getStatus()); footerError.value = '' }
  catch (error) { footerError.value = `状态更新暂不可用 · ${errorMessage(error)}` }
  finally { polling.value = false }
}
async function begin(): Promise<void> {
  if (!statusData.value) applyStatus(await getStatus())
  const response = await sessionApi.start({ mode: 'manual', repetitions: 3 })
  showResult.value = false
  applySession(response.session)
}
async function completeSession(): Promise<void> {
  if (busy.value || polling.value || !activeSession.value || step.value !== repetitions.value - 1 || Date.now() < readyAt.value) return
  busy.value = true
  try {
    const response = await sessionApi.complete(activeSession.value.token)
    applySession(response.session); entry.value = response.entry
    applyStatus(await getStatus())
  } catch (error) { notify(errorMessage(error)) }
  finally { busy.value = false }
}
function wait(milliseconds: number): Promise<void> { return new Promise(resolve => window.setTimeout(resolve, milliseconds)) }
let promptFading = false
let shownPrompt: string | null = null
let pendingPrompt: string | null = null
async function fadePrompt(hidden: boolean): Promise<void> {
  const element = promptEl.value
  if (!element) return
  void getComputedStyle(element).opacity
  element.classList.toggle('practice-text-fading', hidden)
  const transitions = element.getAnimations().filter(animation => (animation as CSSTransition).transitionProperty === 'opacity')
  await Promise.all(transitions.map(animation => animation.finished.catch(() => {})))
}
async function runPromptFade(): Promise<void> {
  promptFading = true
  try {
    while (pendingPrompt !== null) {
      if (pendingPrompt === shownPrompt) { pendingPrompt = null; break }
      await fadePrompt(true)
      const next = pendingPrompt
      if (next === null) break
      pendingPrompt = null
      promptText.value = next; shownPrompt = next
      await nextTick()
      await fadePrompt(false)
    }
  } finally { promptFading = false }
}
function setPrompt(text: string | null): void {
  if (text === null || !activeSession.value) {
    pendingPrompt = null; shownPrompt = text; promptText.value = text
    promptEl.value?.classList.remove('practice-text-fading')
    return
  }
  pendingPrompt = text
  if (!promptFading) void runPromptFade()
}
let desiredView: 'prompt' | 'completed' = 'prompt'
let viewSwitching = false
function switchView(target: 'prompt' | 'completed'): void {
  desiredView = target
  if (viewSwitching) return
  const content = contentEl.value
  if (shownView.value === desiredView || shownView.value === 'landing' || !content) { shownView.value = desiredView; return }
  viewSwitching = true
  void (async () => {
    while (shownView.value !== desiredView) {
      content.classList.add('scene-fading')
      await wait(220)
      shownView.value = desiredView
      content.classList.remove('scene-fading')
      await wait(220)
    }
    viewSwitching = false
  })()
}
watch(targetPrompt, setPrompt, { immediate: true })
watch(() => started.value ? (completed.value ? 'completed' : 'prompt') : null, target => { if (target) switchView(target) }, { immediate: true })
watch(step, value => { document.body.dataset.step = String(value) })
async function advance(): Promise<void> {
  if (busy.value || polling.value || completed.value || promptFading) return
  if (activeSession.value && expiresAt.value && Date.now() >= expiresAt.value) reset('十分钟未进入下一次，请从第一次重新开始。')
  if (activeSession.value && step.value === repetitions.value - 1 && Date.now() >= readyAt.value) return completeSession()
  busy.value = true
  try {
    if (!started.value) {
      started.value = true
      if (pollTimer === undefined) pollTimer = window.setInterval(pollStatus, 20_000)
      if (!statusData.value) {
        const initialStatus = await visitPromise
        if (initialStatus) applyStatus(initialStatus)
      }
      if (statusData.value?.session && !statusData.value.session.completed) applySession(statusData.value.session)
      else if (entry.value) { showResult.value = true; completionKind.value = 'server' }
      return
    }
    if (!activeSession.value) { await begin(); return }
    if (Date.now() < readyAt.value) return
    applySession((await sessionApi.step(activeSession.value.token)).session)
  } catch (error) { notify(errorMessage(error)) }
  finally { busy.value = false }
}
async function claimReward(): Promise<void> {
  if (!entry.value) { window.location.assign(loginUrl('/')); return }
  if (busy.value || entry.value.reward_status !== 'unclaimed') return
  busy.value = true
  try {
    const response = await claim(); entry.value = response.entry
    if (statusData.value) { statusData.value.entry = response.entry; statusData.value.wallet = response.wallet; statusData.value.quota = response.quota }
    notify('恭喜！站内积分已成功到账。')
  } catch (error) { notify(errorMessage(error)) }
  finally { busy.value = false; await pollStatus() }
}
function stageClick(event: MouseEvent): void {
  if ((event.target as Element).closest('a, button, input, textarea, select, summary, [contenteditable], [data-interactive], .toast-notice')) return
  void advance()
}
function stageKey(event: KeyboardEvent): void {
  if (event.repeat || event.isComposing || event.ctrlKey || event.altKey || event.metaKey || event.shiftKey || ['Tab', 'Escape', 'Shift', 'Control', 'Alt', 'Meta', 'CapsLock', 'Fn', 'Unidentified'].includes(event.key) || (event.target as Element).closest('a, button, input, textarea, select, summary, [contenteditable], [data-interactive]')) return
  event.preventDefault(); void advance()
}

const visitPromise = visit().then(value => {
  if (unmounted) return value
  applyStatus(value)
  const done = value.entry || (value.session?.completed || (value.session && value.session.step >= value.session.repetitions))
  if (done) {
    started.value = true
    if (pollTimer === undefined) pollTimer = window.setInterval(pollStatus, 20_000)
    if (value.entry) { entry.value = value.entry; completionKind.value = 'server' }
    else if (value.session) applySession(value.session)
    showResult.value = true
  }
  return value
}).catch(error => { notify(errorMessage(error)); return null })

onMounted(() => {
  timer = window.setInterval(() => {
    now.value = Date.now()
    if (!started.value || busy.value || polling.value || completed.value) return
    if (activeSession.value && expiresAt.value && Date.now() >= expiresAt.value) { reset('十分钟未进入下一次，本轮已失效，请从第一次重新开始。'); return }
    if (activeSession.value && !document.hidden && Date.now() >= readyAt.value && step.value === repetitions.value - 1) void completeSession()
  }, 250)
})
onBeforeUnmount(() => { unmounted = true; if (timer) clearInterval(timer); if (pollTimer) clearInterval(pollTimer); if (noticeTimer) clearTimeout(noticeTimer) })
</script>

<template>
  <main class="stage-main" tabindex="0" :role="activeSession && remaining > 0 ? 'region' : 'button'" :aria-label="ft(activeSession && remaining > 0 ? `正在进行第 ${step + 1} 次练习，等待倒计时` : `开始第 ${activeSession ? Math.min(step + 2, repetitions) : 1} 次练习，点击开始`)" @click="stageClick" @keydown="stageKey">
    <div ref="contentEl" class="stage-content">
      <div v-if="shownView !== 'completed'">
        <h1 id="prompt" ref="promptEl" class="landing-prompt" :style="{ '--prompt-fade-duration': `${fadeSeconds}s` }" aria-live="polite" aria-atomic="true"><template v-if="promptText === null">你今天<span class="prompt-accent">{{ ft('提肛') }}</span>了吗？</template><template v-else>{{ promptText }}</template></h1>
        <p class="landing-sub"><span>{{ hint }}</span><span id="stageCountdown">{{ remaining > 0 ? `${remaining} 秒` : '' }}</span></p>
        <div v-if="activeSession && !completed" class="dots-progress" aria-label="练习进度"><span v-for="index in repetitions" :key="index" :class="{ active: index - 1 <= step }" /></div>
      </div>
      <section v-else class="completion-container" data-interactive>
        <div class="completion-card">
          <div class="completion-check-wrap"><div class="check-aura" /><div class="check-circle"><svg fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" /></svg></div></div>
          <div class="completion-info">
            <h2 class="completion-title">{{ completionSummary.titlePrefix }}<span class="rank-num">{{ completionSummary.rank }}</span>{{ completionSummary.titleSuffix }}</h2>
            <p class="completion-reward-text">{{ completionSummary.rewardPrefix }}<b>{{ completionSummary.amount }}</b>{{ completionSummary.rewardSuffix }}</p>
            <p v-if="entry" class="completion-streak-text">已连续 <b>{{ entry.streak_days ?? 0 }}</b> 天打卡（只计入工作日），每多一天获取积分提升 1%，最高 100%</p>
            <div class="completion-actions">
              <button v-if="entry ? entry.reward_status === 'unclaimed' : completionKind !== 'closed' && completionKind !== 'review'" class="btn-primary" type="button" :disabled="busy || (!entry && !statusData?.oauth_ready)" @click="claimReward">{{ entry ? (busy ? '正在领取…' : '领取站内积分') : statusData?.oauth_ready ? 'LINUX DO 登录参与排名' : '登录暂未配置' }}</button>
              <RouterLink class="btn-secondary" to="/practice" :query="preferenceQuery()">{{ ft('提肛练习') }}</RouterLink>
              <span v-if="statusPill" class="status-pill" :class="{ credited: entry?.reward_status === 'credited' }">{{ statusPill }}</span>
            </div>
            <p class="status-copy" style="font-size:13px;color:var(--text-muted);margin-top:10px" aria-live="polite">{{ rewardNote }}</p>
          </div>
        </div>
        <div class="completion-grid">
          <details class="card card-collapse" open><summary class="card-header-line collapse-summary"><h3 class="card-title">今日榜单 <span class="card-subtitle">坚持打卡，赢取更多奖励</span></h3><div style="display:flex;align-items:center;gap:8px"><span style="font-size:12px;color:var(--text-dim)">已有 {{ statusData?.total || 0 }} 人完成今日打卡</span><svg class="collapse-chevron" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" /></svg></div></summary><div class="collapse-body"><div class="table-wrap" style="max-height:380px"><table class="rank-table"><thead><tr><th>名次</th><th>用户名</th><th>奖励积分</th></tr></thead><tbody><tr v-if="!statusData?.leaderboard.length"><td colspan="3" style="text-align:center;color:var(--text-dim)">今天的第一份向上，正在路上。</td></tr><tr v-for="record in statusData?.leaderboard || []" :key="`${record.rank}-${record.username}`" :class="{ 'current-user': record.username === statusData?.user?.username }"><td><span v-if="record.rank <= 3" class="rank-badge" :class="`rank-${record.rank}`">{{ record.rank }}</span><template v-else>{{ record.rank }}</template></td><td>{{ record.username === statusData?.user?.username ? `你 (@${record.username})` : `@${record.username}` }}</td><td>{{ record.amount }}</td></tr></tbody></table></div></div></details>
          <details class="card card-collapse" open><summary class="card-header-line collapse-summary"><h3 class="card-title">奖励规则 <span class="card-subtitle">根据今日打卡名次获得对应站内积分</span></h3><svg class="collapse-chevron" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" /></svg></summary><div class="collapse-body"><ul class="rules-list"><li v-for="rule in rewardRules" :key="rule.label"><span class="tier-range">{{ rule.label }}</span><span class="tier-val" :style="rule.rewarded ? undefined : { color: 'var(--text-dim)' }">{{ rule.value }}</span></li></ul><div class="quota-box"><div class="card-header-line" style="margin-bottom:10px"><h4 class="card-title" style="font-size:15px">今日 LDC 兑换额度 <span class="card-subtitle">全站每日兑换金额上限，北京时间重置</span></h4></div><div class="quota-labels"><span>今日已兑换 {{ statusData?.quota.used || '0.00' }} / {{ statusData?.quota.limit || '0.00' }} LDC</span><span style="color:var(--primary);font-weight:600">剩余 {{ statusData?.quota.remaining || '0.00' }} LDC</span></div><div class="quota-bar-track"><div class="quota-bar-fill" :style="{ width: `${quotaPercent}%` }" /></div></div></div></details>
        </div>
      </section>
    </div>
  </main>
  <footer v-if="started" style="padding:24px;text-align:center;font-size:12px;color:var(--text-dim)"><span>{{ footerNote }}</span> · <span>慢一点，也向上一点。</span></footer>
  <div v-if="notice" class="toast-notice" role="status" aria-live="polite">{{ notice }}</div>
</template>
