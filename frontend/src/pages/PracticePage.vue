<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ApiError, loginUrl, practice as practiceApi, type PracticeData } from '../api'
import PracticeSettings from '../components/PracticeSettings.vue'
import { readPracticePreferences, useLocalPractice, type LocalPracticeSession, type PracticePreferences } from '../composables/useLocalPractice'
import { useBodyAttributes } from '../composables/useBodyAttributes'
import { ft, playFeedbackSound, triggerHaptic } from '../composables/usePreferences'

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
const zenMode = ref(false)
const trainingTab = ref<'daily' | 'all' | 'records'>('daily')

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
  playFeedbackSound('step')
  triggerHaptic(30)
  applySession(localPractice.start(settings.value, training.value?.user?.id))
}
async function stepSession(): Promise<void> {
  const session = activeSession.value
  if (busy.value || !session || Date.now() < session.ready_at) return
  busy.value = true
  try {
    applySession(localPractice.step(session.token))
    playFeedbackSound('step')
    triggerHaptic(30)
  } catch (error) {
    autoPaused.value = session.mode === 'auto'
    notify(errorMessage(error))
  } finally {
    busy.value = false
  }
}
async function completeSession(): Promise<void> {
  const session = activeSession.value
  if (busy.value || !session || session.step !== session.repetitions - 1 || Date.now() < session.ready_at) return
  busy.value = true
  try {
    applySession(localPractice.complete(session.token))
    playFeedbackSound('complete')
    triggerHaptic([30, 60, 40])
  } catch (error) {
    autoPaused.value = session.mode === 'auto'
    notify(errorMessage(error))
  } finally {
    busy.value = false
  }
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
    playFeedbackSound('step')
    triggerHaptic(30)
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
  <main class="practice-layout" :class="{ 'is-zen-mode': zenMode }">
    <div class="practice-main-column">
      <section
        class="stage-main"
        tabindex="0"
        :role="activeSession && (remaining > 0 || activeSession.mode === 'auto') ? 'region' : 'button'"
        :aria-label="ft(activeSession && remaining > 0 ? `正在进行第 ${step + 1} 次练习，等待倒计时` : `开始第 ${activeSession ? Math.min(step + 2, repetitions) : 1} 次练习`)"
        @click="stageClick"
        @keydown="stageKey"
      >
        <!-- 专注模式切换按钮 -->
        <div class="practice-top-bar" data-interactive>
          <button
            type="button"
            class="btn-zen-mode"
            :class="{ active: zenMode }"
            :title="zenMode ? '退出专注模式' : '进入沉浸专注训练'"
            @click="zenMode = !zenMode"
          >
            <span>{{ zenMode ? '✕ 退出专注' : '🧘 禅意专注' }}</span>
          </button>
        </div>

        <div class="stage-content">
          <!-- 练习进行中 -->
          <div v-if="!completed" class="hero-stage-box">
            <!-- 练习动态节拍光环 -->
            <div class="breathing-ring-wrapper" :class="{ 'is-active': activeSession && remaining > 0, 'phase-lift': phase?.index === 0, 'phase-relax': phase?.index === 1, 'phase-rest': phase?.index === 2 }">
              <div class="breathing-glow-aura" />
              <svg class="breathing-ring-svg" viewBox="0 0 240 240">
                <circle class="ring-bg" cx="120" cy="120" r="102" />
                <circle
                  v-if="activeSession && remaining > 0"
                  class="ring-progress-bar"
                  cx="120"
                  cy="120"
                  r="102"
                  :stroke-dasharray="640"
                  :stroke-dashoffset="640 - (640 * (activeSession.interval_seconds > 0 ? ((activeSession.interval_seconds - remaining) / activeSession.interval_seconds) : 0))"
                />
              </svg>
              <div class="ring-inner-content">
                <span v-if="phase" class="ring-phase-badge">
                  第 {{ step + 1 }} / {{ repetitions }} 次 · {{ phase.text }}
                </span>
                <span v-else class="ring-phase-badge">
                  {{ settings.mode === 'auto' ? '自动练习就绪' : '手动练习就绪' }}
                </span>
                <div v-if="remaining > 0" class="ring-timer-text">
                  00:0{{ remaining }}
                </div>
                <div v-else class="ring-idle-icon">
                  🧘
                </div>
                <span class="ring-action-hint">
                  {{ phase ? phase.text : (activeSession ? '进入下一次' : '点击开始') }}
                </span>
              </div>
            </div>

            <h1 ref="promptElement" class="landing-prompt" aria-live="polite" aria-atomic="true">
              {{ prompt }}
            </h1>
            <p class="landing-sub">
              <span>{{ hint }}</span>
              <span v-if="remaining > 0" style="margin-left:4px">{{ remaining }} 秒</span>
            </p>

            <div class="practice-controls-row" data-interactive>
              <button
                v-if="activeSession?.mode === 'auto'"
                class="btn-secondary auto-stop-button"
                type="button"
                @click="autoPaused = !autoPaused"
              >
                {{ autoPaused ? '▶ 继续自动练习' : '⏸ 暂停自动练习' }}
              </button>
              <button
                v-if="activeSession"
                class="btn-secondary auto-stop-button btn-abandon"
                type="button"
                :disabled="busy"
                @click="abandon"
              >
                放弃本轮
              </button>
            </div>

            <!-- 进度指示 -->
            <div v-if="activeSession" class="step-nodes-container" aria-label="练习进度">
              <div
                v-for="index in repetitions"
                :key="index"
                class="step-node-item"
                :class="{
                  completed: index - 1 < step,
                  current: index - 1 === step,
                  pending: index - 1 > step
                }"
              >
                <div class="step-node-bubble">
                  <span v-if="index - 1 < step">✓</span>
                  <span v-else>{{ index }}</span>
                </div>
                <span class="step-node-label">{{ index }}</span>
              </div>
            </div>

            <div v-if="activeSession" class="dots-progress" aria-hidden="true" style="display:none">
              <span v-for="index in repetitions" :key="index" :class="{ active: index - 1 <= step }" />
            </div>
          </div>

          <!-- 练习完成结算卡片 -->
          <section v-else class="completion-container" data-interactive>
            <div class="completion-card">
              <div class="completion-check-wrap">
                <div class="check-aura" />
                <div class="check-circle" :style="{ background: activeSession?.abandoned ? 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)' : undefined }">
                  <span v-if="activeSession?.abandoned" style="font-size:32px">✋</span>
                  <svg v-else fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                </div>
              </div>
              <div class="completion-info">
                <h2 class="completion-title">{{ activeSession?.abandoned ? '本轮已提前终止' : '🎉 本轮练习圆满完成' }}</h2>
                <p class="completion-reward-text">
                  共完成 <b>{{ completedCount }}</b> 次{{ completedCount === 0 ? '，未产生训练记录。' : uploaded ? '，已同步计入训练榜。' : '，尚未同步至训练榜。' }}
                </p>
                <div class="completion-actions">
                  <button class="btn-primary" type="button" :disabled="busy" @click="restart">再练一轮 ➔</button>
                  <button
                    v-if="completedCount > 0 && !uploaded && activeSession?.round_id"
                    class="btn-secondary"
                    type="button"
                    :disabled="syncing || wrongUser"
                    @click="upload"
                  >
                    {{ training?.user ? '立即上传云端' : '登录后上传' }}
                  </button>
                  <RouterLink class="btn-secondary" to="/">返回打卡首页</RouterLink>
                  <span class="status-pill" :class="{ credited: uploaded }">{{ statusPill }}</span>
                </div>
                <p class="status-copy" aria-live="polite">{{ resultNote }}</p>
              </div>
            </div>
          </section>
        </div>
      </section>

      <!-- 排行榜与记录卡片 (Zen Mode 下隐藏) -->
      <section v-show="!zenMode" class="card practice-ranking-box" data-interactive>
        <div class="home-tabs-header" style="margin-bottom:18px">
          <button
            type="button"
            class="home-tab-btn"
            :class="{ active: trainingTab === 'daily' }"
            @click="trainingTab = 'daily'"
          >
            📅 今日训练榜 <span class="tab-badge">{{ practiceTotal }}</span>
          </button>
          <button
            type="button"
            class="home-tab-btn"
            :class="{ active: trainingTab === 'all' }"
            @click="trainingTab = 'all'"
          >
            🌟 训练总榜 <span class="tab-badge">{{ allTimeTotal }}</span>
          </button>
          <button
            type="button"
            class="home-tab-btn"
            :class="{ active: trainingTab === 'records' }"
            @click="trainingTab = 'records'"
          >
            📋 我的训练历史
          </button>
        </div>

        <!-- TAB 1: 今日训练榜 -->
        <div v-show="trainingTab === 'daily'">
          <div class="table-wrap" style="max-height:340px">
            <table class="rank-table">
              <thead>
                <tr><th>名次</th><th>用户名</th><th>今日训练次数</th></tr>
              </thead>
              <tbody>
                <tr v-if="!training?.leaderboard.length">
                  <td colspan="3" style="text-align:center;color:var(--text-dim);padding:24px">登录后完成训练并上传，即可计入训练榜。</td>
                </tr>
                <tr
                  v-for="record in training?.leaderboard || []"
                  :key="`${record.rank}-${record.username}`"
                  :class="{ 'current-user': record.username === training?.user?.username }"
                >
                  <td>{{ record.rank }}</td>
                  <td>{{ record.username === training?.user?.username ? `你 (@${record.username})` : `@${record.username}` }}</td>
                  <td style="font-weight:700;color:var(--primary)">{{ record.count }} 次</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- TAB 2: 训练总榜 -->
        <div v-show="trainingTab === 'all'">
          <div class="table-wrap" style="max-height:340px">
            <table class="rank-table">
              <thead>
                <tr><th>名次</th><th>用户名</th><th>累计训练次数</th></tr>
              </thead>
              <tbody>
                <tr v-if="!training?.total_leaderboard.length">
                  <td colspan="3" style="text-align:center;color:var(--text-dim);padding:24px">登录后完成训练并上传，即可计入训练榜。</td>
                </tr>
                <tr
                  v-for="record in training?.total_leaderboard || []"
                  :key="`${record.rank}-${record.username}`"
                  :class="{ 'current-user': record.username === training?.user?.username }"
                >
                  <td>{{ record.rank }}</td>
                  <td>{{ record.username === training?.user?.username ? `你 (@${record.username})` : `@${record.username}` }}</td>
                  <td style="font-weight:700;color:var(--primary)">{{ record.count }} 次</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- TAB 3: 我的历史记录 -->
        <div v-show="trainingTab === 'records'">
          <div class="table-wrap" style="max-height:340px">
            <table class="rank-table">
              <thead>
                <tr><th>开始时间</th><th>结束时间</th><th>完成次数</th><th>练习方式</th></tr>
              </thead>
              <tbody>
                <tr v-if="!training?.records.length">
                  <td colspan="4" style="text-align:center;color:var(--text-dim);padding:24px">{{ training?.user ? '暂无已上传的训练记录。' : '登录后可上传并查看你的训练记录。' }}</td>
                </tr>
                <tr v-for="record in training?.records || []" :key="record.round_id">
                  <td>{{ formatTime(record.started_at) }}</td>
                  <td>{{ formatTime(record.ended_at) }}</td>
                  <td style="font-weight:700">{{ record.repetitions }} 次</td>
                  <td><span class="status-pill">{{ record.mode === 'auto' ? '自动' : '手动' }}</span></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </div>

    <!-- 右侧设置侧边栏 (Zen Mode 下隐藏) -->
    <aside v-show="!zenMode" aria-label="练习与提醒设置">
      <PracticeSettings ref="settingsPanel" v-model="settings" />
    </aside>
  </main>
  <footer class="practice-footer">训练在本地精准计时；登录后上传起止时间与次数，独立统计，不影响每日打卡。</footer>
  <div v-if="notice" class="toast-notice" role="status" aria-live="polite">{{ notice }}</div>
</template>
