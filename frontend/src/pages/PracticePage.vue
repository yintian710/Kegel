<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ApiError, loginUrl, practice as practiceApi, type PracticeData } from '../api'
import PracticeSettings from '../components/PracticeSettings.vue'
import { readPracticePreferences, useLocalPractice, type LocalPracticeSession, type PracticePreferences } from '../composables/useLocalPractice'
import { useBodyAttributes } from '../composables/useBodyAttributes'
import { ft } from '../composables/usePreferences'

useBodyAttributes({ class: ['stage-wrap', 'practice-page'], data: { page: 'practice', step: '0' }, htmlClass: 'practice-page-root' })

const localPractice = useLocalPractice()
const settings = ref<PracticePreferences>(readPracticePreferences())
const settingsPanel = ref<InstanceType<typeof PracticeSettings>>()
const promptElement = ref<HTMLElement>()
const activeSession = ref<LocalPracticeSession | null>(null)
const training = ref<PracticeData | null>(null)
const trainingError = ref('')
const uploadError = ref('')
const busy = ref(false)
const syncing = ref(false)
const autoPaused = ref(false)
const showResult = ref(false)
const notice = ref('')
const remaining = ref(0)
const now = ref(Date.now())
let ticker: number | undefined
let poller: number | undefined
let noticeTimer: number | undefined
let promptAnimation: Animation | null = null

const repetitions = computed(() => activeSession.value?.repetitions || settings.value.repetitions)
const step = computed(() => activeSession.value?.step || 0)
const completed = computed(() => showResult.value || Boolean(activeSession.value?.completed))
const phase = computed(() => {
  const session = activeSession.value
  if (!session || remaining.value <= 0) return null
  const duration = session.interval_seconds * 1000
  const startsAt = session.ready_at - duration
  const liftEnd = startsAt + duration * session.lift_end / 100
  const relaxEnd = startsAt + duration * session.relax_end / 100
  if (now.value < liftEnd) return { index: 0, text: session.phase_names[0], startsAt, endsAt: liftEnd }
  if (now.value < relaxEnd) return { index: 1, text: session.phase_names[1], startsAt: liftEnd, endsAt: relaxEnd }
  return { index: 2, text: session.phase_names[2], startsAt: relaxEnd, endsAt: session.ready_at }
})
const prompt = computed(() => {
  if (phase.value) return phase.value.text
  if (!activeSession.value) return settings.value.mode === 'auto' ? '开始自动练习' : '开始第 1 次？'
  const current = Math.min(step.value + 1, repetitions.value)
  return activeSession.value.mode === 'auto' ? `第 ${current} 次` : `开始第 ${Math.min(current + 1, repetitions.value)} 次？`
})
const hint = computed(() => {
  if (busy.value) return '正在记录，请稍候…'
  if (autoPaused.value) return '自动练习已停止，可用下方按钮继续'
  if (!activeSession.value) return settings.value.mode === 'auto' ? '点击页面或按任意键，开始自动练习' : '点击页面或按任意键，开始第 1 次'
  if (remaining.value > 0) return phase.value ? `第 ${step.value + 1} 次 · ${phase.value.text} · 本次还剩 ` : '本次还剩 '
  if (activeSession.value.mode === 'auto' && step.value < repetitions.value - 1) return '正在自动进入下一次…'
  if (step.value < repetitions.value - 1) return `点击页面或按任意键，开始第 ${step.value + 2} 次`
  return `${repetitions.value} 次完成，正在确认记录…`
})
const completedCount = computed(() => activeSession.value?.completed_repetitions ?? repetitions.value)
const uploaded = computed(() => Boolean(activeSession.value?.uploaded_user_id))
const wrongUser = computed(() => Boolean(activeSession.value?.owner_id && training.value?.user && activeSession.value.owner_id !== training.value.user.id))
const resultError = computed(() => activeSession.value?.upload_error || uploadError.value || trainingError.value)
const statusPill = computed(() => completedCount.value === 0 ? '未完成任何次数' : uploaded.value ? '训练记录已上传' : !activeSession.value?.round_id ? '旧记录仅存本地' : syncing.value ? '正在上传…' : resultError.value ? '上传未成功' : '等待上传')
const resultNote = computed(() => {
  if (completedCount.value === 0) return '未做完的次数不计入记录，可以重新开始一轮。'
  if (!activeSession.value?.round_id) return '旧的本地记录缺少起止时间，无法补传；请重新开始一轮训练。'
  if (wrongUser.value) return '此轮训练属于开始时登录的账号，请切回该账号后上传。'
  if (uploaded.value) return '可在下方查看本轮起止时间和次数；训练不影响每日打卡和积分。'
  return resultError.value || '登录后上传起止时间与次数；每轮需在一小时内完成，并在结束后五分钟内提交。'
})
const practiceTotal = computed(() => trainingError.value ? '榜单暂不可用' : training.value?.leaderboard.length ? `今日 · 展示 ${training.value.leaderboard.length} 人` : '暂无记录')
const allTimeTotal = computed(() => trainingError.value ? '榜单暂不可用' : training.value?.total_leaderboard.length ? `累计 · 展示 ${training.value.total_leaderboard.length} 人` : '暂无记录')

function errorMessage(error: unknown): string { return error instanceof Error ? error.message : '请求失败，请稍后重试。' }
function notify(message: string): void {
  notice.value = message
  if (noticeTimer !== undefined) clearTimeout(noticeTimer)
  noticeTimer = window.setTimeout(() => { notice.value = '' }, 4000)
}
function applySession(session: LocalPracticeSession): void {
  activeSession.value = session
  remaining.value = Math.max(0, Math.ceil(session.wait_seconds))
  showResult.value = session.completed
  if (session.completed) autoPaused.value = false
}
function reset(message?: string): void {
  localPractice.reset(); activeSession.value = null; showResult.value = false; autoPaused.value = false; remaining.value = 0
  if (message) notify(message)
}
async function refreshTraining(uploadPending = false): Promise<void> {
  try {
    training.value = await practiceApi.get(); trainingError.value = ''
    if (uploadPending) await syncTraining()
  } catch (error) { trainingError.value = errorMessage(error) }
}
async function syncTraining(retryRejected = false): Promise<void> {
  if (syncing.value || !training.value?.user) return
  const userId = training.value.user.id
  syncing.value = true; uploadError.value = ''
  try {
    for (const item of localPractice.pending(userId, retryRejected)) {
      localPractice.bindOwner(item.round_id, userId)
      const { owner_id: _owner, error: _previous, ...body } = item
      try {
        training.value = await practiceApi.upload({ ...body, expected_user_id: userId })
        localPractice.uploaded(item.round_id, userId)
      } catch (error) {
        uploadError.value = errorMessage(error)
        if (error instanceof ApiError && [400, 403, 409].includes(error.status)) localPractice.rejected(item.round_id, uploadError.value)
        else break
      }
    }
  } finally {
    const local = localPractice.view()
    if (local && local.round_id === activeSession.value?.round_id) applySession(local)
    syncing.value = false
  }
}
async function begin(): Promise<void> {
  if (!settingsPanel.value?.validate()) throw new Error('请先修正练习设置中的提示。')
  showResult.value = false
  applySession(localPractice.start(settings.value, training.value?.user?.id))
}
async function stepSession(): Promise<void> {
  const session = activeSession.value
  if (busy.value || !session || Date.now() < session.ready_at) return
  busy.value = true
  try { applySession(localPractice.step(session.token)) }
  catch (error) { autoPaused.value = session.mode === 'auto'; notify(errorMessage(error)) }
  finally { busy.value = false }
}
async function completeSession(): Promise<void> {
  const session = activeSession.value
  if (busy.value || !session || session.step !== session.repetitions - 1 || Date.now() < session.ready_at) return
  busy.value = true
  try { applySession(localPractice.complete(session.token)) }
  catch (error) { autoPaused.value = session.mode === 'auto'; notify(errorMessage(error)) }
  finally { busy.value = false }
  if (activeSession.value?.completed) await refreshTraining(true)
}
async function advance(): Promise<void> {
  if (busy.value || completed.value || activeSession.value?.mode === 'auto') return
  if (activeSession.value && activeSession.value.expires_at <= Date.now()) reset('十分钟未进入下一次，请从第一次重新开始。')
  busy.value = true
  try {
    if (!activeSession.value) { await begin(); return }
    if (Date.now() < activeSession.value.ready_at) return
    if (activeSession.value.step === activeSession.value.repetitions - 1) { busy.value = false; await completeSession(); return }
    applySession(localPractice.step(activeSession.value.token))
  } catch (error) { notify(errorMessage(error)) }
  finally { busy.value = false }
}
async function restart(): Promise<void> {
  if (busy.value) return
  if (settings.value.mode === 'manual') { reset(); return }
  reset()
  try { await begin() } catch (error) { showResult.value = true; notify(errorMessage(error)) }
}
function abandon(): void {
  if (busy.value || !activeSession.value || completed.value) return
  applySession(localPractice.complete(activeSession.value.token, true))
  void refreshTraining(true)
}
async function upload(): Promise<void> {
  await refreshTraining()
  if (!training.value?.user) { window.location.assign(loginUrl('/practice')); return }
  await syncTraining(true)
}
function stageClick(event: MouseEvent): void {
  if ((event.target as Element).closest('a, button, input, textarea, select, summary, [contenteditable], [data-interactive], .toast-notice')) return
  void advance()
}
function stageKey(event: KeyboardEvent): void {
  if (event.repeat || event.isComposing || event.ctrlKey || event.altKey || event.metaKey || event.shiftKey || ['Tab', 'Escape', 'Shift', 'Control', 'Alt', 'Meta', 'CapsLock', 'Fn', 'Unidentified'].includes(event.key) || (event.target as Element).closest('a, button, input, textarea, select, summary, [contenteditable], [data-interactive]')) return
  event.preventDefault(); void advance()
}
function formatTime(value: number): string { return new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) }

watch(() => activeSession.value && phase.value ? `${activeSession.value.token}:${phase.value.index}` : '', () => {
  promptAnimation?.cancel()
  const element = promptElement.value
  const current = phase.value
  if (!element || !current) return
  const duration = current.endsAt - current.startsAt
  promptAnimation = element.animate([{ opacity: 0 }, { opacity: 1, offset: 2 / 3 }, { opacity: 0 }], { duration, easing: 'linear', fill: 'both' })
  promptAnimation.currentTime = Math.min(duration, Math.max(0, Date.now() - current.startsAt))
})

function reloadPracticePreferences(): void {
  settings.value = readPracticePreferences()
}

onMounted(() => {
  const saved = localPractice.view()
  if (saved) applySession(saved)
  void refreshTraining(true)
  window.addEventListener('practicepreferenceschange', reloadPracticePreferences)
  poller = window.setInterval(() => { if (!document.hidden) void refreshTraining() }, 20_000)
  ticker = window.setInterval(() => {
    now.value = Date.now()
    const session = activeSession.value
    remaining.value = session ? Math.max(0, Math.ceil((session.ready_at - now.value) / 1000)) : 0
    document.body.dataset.step = String(step.value)
    if (!session || completed.value || busy.value) return
    if (session.expires_at <= now.value) { reset('十分钟未进入下一次，本轮已失效，请从第一次重新开始。'); return }
    if (autoPaused.value || document.hidden || now.value < session.ready_at) return
    if (session.step === session.repetitions - 1) void completeSession()
    else if (session.mode === 'auto') void stepSession()
  }, 250)
})
onBeforeUnmount(() => {
  if (ticker) clearInterval(ticker)
  if (poller) clearInterval(poller)
  if (noticeTimer) clearTimeout(noticeTimer)
  promptAnimation?.cancel()
  window.removeEventListener('practicepreferenceschange', reloadPracticePreferences)
})
</script>

<template>
  <main class="practice-layout">
    <div class="practice-main-column">
      <section class="stage-main" tabindex="0" :role="activeSession && (remaining > 0 || activeSession.mode === 'auto') ? 'region' : 'button'" :aria-label="ft(activeSession && remaining > 0 ? `正在进行第 ${step + 1} 次练习，等待倒计时` : `开始第 ${activeSession ? Math.min(step + 2, repetitions) : 1} 次练习`)" @click="stageClick" @keydown="stageKey">
        <div class="stage-content">
          <div v-if="!completed">
            <h1 ref="promptElement" class="landing-prompt" aria-live="polite" aria-atomic="true">{{ prompt }}</h1>
            <p class="landing-sub"><span>{{ hint }}</span><span>{{ remaining > 0 ? `${remaining} 秒` : '' }}</span></p>
            <button v-if="activeSession?.mode === 'auto'" class="btn-secondary auto-stop-button" type="button" data-interactive @click="autoPaused = !autoPaused">{{ autoPaused ? '继续自动练习' : '停止自动练习' }}</button>
            <button v-if="activeSession" class="btn-secondary auto-stop-button" type="button" data-interactive :disabled="busy" @click="abandon">放弃本轮</button>
            <div v-if="activeSession" class="dots-progress" aria-label="练习进度"><span v-for="index in repetitions" :key="index" :class="{ active: index - 1 <= step }" /></div>
          </div>
          <section v-else class="completion-container" data-interactive>
            <div class="completion-card"><div class="completion-info">
              <h2 class="completion-title">{{ activeSession?.abandoned ? '本轮已放弃' : '本轮练习完成' }}</h2>
              <p class="completion-reward-text">共完成 {{ completedCount }} 次{{ completedCount === 0 ? '，未产生训练记录。' : uploaded ? '，已上传并计入训练榜。' : '，尚未计入训练榜。' }}</p>
              <div class="completion-actions">
                <button class="btn-secondary" type="button" :disabled="busy" @click="restart">再练一轮</button>
                <button v-if="completedCount > 0 && !uploaded && activeSession?.round_id" class="btn-primary" type="button" :disabled="syncing || wrongUser" @click="upload">{{ training?.user ? '上传训练记录' : '登录后上传' }}</button>
                <RouterLink class="btn-secondary" to="/">返回首页</RouterLink>
                <span class="status-pill" :class="{ credited: uploaded }">{{ statusPill }}</span>
              </div>
              <p class="status-copy" aria-live="polite">{{ resultNote }}</p>
            </div></div>
          </section>
        </div>
      </section>

      <section class="card practice-ranking" data-interactive aria-labelledby="practiceRankingTitle"><div class="practice-ranking-header"><div><h3 id="practiceRankingTitle" class="card-title">每日训练榜</h3><p class="card-subtitle" style="margin:4px 0 0">按今日已上传并通过校验的训练次数排序</p></div><span class="practice-ranking-total">{{ practiceTotal }}</span></div><div class="table-wrap" style="max-height:320px"><table class="rank-table"><thead><tr><th>名次</th><th>用户名</th><th>完成次数</th></tr></thead><tbody><tr v-if="!training?.leaderboard.length"><td colspan="3" style="text-align:center;color:var(--text-dim)">登录后完成训练并上传，即可计入训练榜。</td></tr><tr v-for="record in training?.leaderboard || []" :key="`${record.rank}-${record.username}`" :class="{ 'current-user': record.username === training?.user?.username }"><td>{{ record.rank }}</td><td>{{ record.username === training?.user?.username ? `你 (@${record.username})` : `@${record.username}` }}</td><td>{{ record.count }} 次</td></tr></tbody></table></div></section>
      <section class="card practice-ranking" data-interactive aria-labelledby="totalPracticeRankingTitle"><div class="practice-ranking-header"><div><h3 id="totalPracticeRankingTitle" class="card-title">训练总榜</h3><p class="card-subtitle" style="margin:4px 0 0">按所有日期已上传并通过校验的累计训练次数排序</p></div><span class="practice-ranking-total">{{ allTimeTotal }}</span></div><div class="table-wrap" style="max-height:320px"><table class="rank-table"><thead><tr><th>名次</th><th>用户名</th><th>累计次数</th></tr></thead><tbody><tr v-if="!training?.total_leaderboard.length"><td colspan="3" style="text-align:center;color:var(--text-dim)">登录后完成训练并上传，即可计入训练榜。</td></tr><tr v-for="record in training?.total_leaderboard || []" :key="`${record.rank}-${record.username}`" :class="{ 'current-user': record.username === training?.user?.username }"><td>{{ record.rank }}</td><td>{{ record.username === training?.user?.username ? `你 (@${record.username})` : `@${record.username}` }}</td><td>{{ record.count }} 次</td></tr></tbody></table></div></section>
      <section class="card practice-ranking" data-interactive aria-labelledby="trainingRecordsTitle"><div class="practice-ranking-header"><div><h3 id="trainingRecordsTitle" class="card-title">我的训练记录</h3><p class="card-subtitle" style="margin:4px 0 0">最近 50 轮已上传记录 · 北京时间</p></div></div><div class="table-wrap" style="max-height:320px"><table class="rank-table"><thead><tr><th>开始时间</th><th>结束时间</th><th>次数</th><th>方式</th></tr></thead><tbody><tr v-if="!training?.records.length"><td colspan="4">{{ training?.user ? '暂无已上传的训练记录。' : '登录后可上传并查看你的训练记录。' }}</td></tr><tr v-for="record in training?.records || []" :key="record.round_id"><td>{{ formatTime(record.started_at) }}</td><td>{{ formatTime(record.ended_at) }}</td><td>{{ record.repetitions }} 次</td><td>{{ record.mode === 'auto' ? '自动' : '手动' }}</td></tr></tbody></table></div></section>
    </div>
    <aside aria-label="练习与提醒设置"><PracticeSettings ref="settingsPanel" v-model="settings" /></aside>
  </main>
  <footer class="practice-footer">训练在本地计时；登录后上传起止时间与次数，独立统计，不影响每日打卡。</footer>
  <div v-if="notice" class="toast-notice" role="status" aria-live="polite">{{ notice }}</div>
</template>
