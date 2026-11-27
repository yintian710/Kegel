<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { ApiError, loginUrl, practice as practiceApi, type PracticeData } from '../api'
import {
  readPracticePreferences,
  savePracticePreferences,
  useLocalPractice,
  type LocalPracticeSession,
  type PracticePreferences,
} from '../composables/useLocalPractice'
import { useBodyAttributes } from '../composables/useBodyAttributes'
import ScrollTable from '../components/ScrollTable.vue'
import { ft, playFeedbackSound, triggerHaptic } from '../composables/usePreferences'

useBodyAttributes({
  class: ['stage-wrap', 'practice-page'],
  data: { page: 'practice', step: '0' },
  htmlClass: 'practice-page-root',
})

const localPractice = useLocalPractice()
const settings = ref<PracticePreferences>(readPracticePreferences())
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
const activeSettingsTab = ref<'presets' | 'custom'>('presets')
const trainingTab = ref<'daily' | 'all' | 'records'>('daily')

// 输入框本地草稿（用于支持用户在输入框里自由修改）
const draftRepetitions = ref(String(settings.value.repetitions))
const draftInterval = ref(String(settings.value.intervalSeconds))

// 快捷预设配置
const presets = [
  { id: 'starter', name: '入门基础', icon: '🌿', repetitions: 3, interval: 3, desc: '3组 · 每组3秒 · 温和建立肌肉控制感' },
  { id: 'regular', name: '日常强化', icon: '⚡', repetitions: 5, interval: 5, desc: '5组 · 每组5秒 · 紧凑有力，增强深层张力' },
  { id: 'endurance', name: '耐力挑战', icon: '⏱️', repetitions: 10, interval: 5, desc: '10组 · 每组5秒 · 强化持久控制耐劳力' },
  { id: 'relax', name: '舒缓恢复', icon: '🧘', repetitions: 3, interval: 4, desc: '3组 · 每组4秒 · 运动后舒展放松' },
]

function applyPreset(p: typeof presets[0]): void {
  draftRepetitions.value = String(p.repetitions)
  draftInterval.value = String(p.interval)
  commitSettings({ repetitions: p.repetitions, intervalSeconds: p.interval })
  notify(`已应用「${p.name}」配置`)
}

let ticker: number | undefined
let poller: number | undefined
let noticeTimer: number | undefined
let rafId: number | undefined

const repetitions = computed(() => activeSession.value?.repetitions || settings.value.repetitions)
const step = computed(() => activeSession.value?.step || 0)
const completed = computed(() => showResult.value || Boolean(activeSession.value?.completed))

// 连续平滑进度 (0 -> 1)
const smoothProgress = computed(() => {
  const session = activeSession.value
  if (!session || remaining.value <= 0 || completed.value) return 0
  const duration = session.interval_seconds * 1000
  const startsAt = session.ready_at - duration
  const elapsed = Math.max(0, now.value - startsAt)
  return Math.min(1, Math.max(0, elapsed / duration))
})

// 三阶段时间与文本指示及动态阶段色彩
const phase = computed(() => {
  const session = activeSession.value
  if (!session || remaining.value <= 0) return null
  const duration = session.interval_seconds * 1000
  const startsAt = session.ready_at - duration
  const liftEnd = startsAt + (duration * session.lift_end) / 100
  const relaxEnd = startsAt + (duration * session.relax_end) / 100
  if (now.value < liftEnd) {
    return {
      index: 0,
      text: session.phase_names[0],
      color: '#10b981', // 翡翠绿
      glow: 'rgba(16, 185, 129, 0.45)',
      startsAt,
      endsAt: liftEnd,
    }
  }
  if (now.value < relaxEnd) {
    return {
      index: 1,
      text: session.phase_names[1],
      color: '#3b82f6', // 湛蓝
      glow: 'rgba(59, 130, 246, 0.45)',
      startsAt: liftEnd,
      endsAt: relaxEnd,
    }
  }
  return {
    index: 2,
    text: session.phase_names[2],
    color: '#f59e0b', // 暖金
    glow: 'rgba(245, 158, 11, 0.45)',
    startsAt: relaxEnd,
    endsAt: session.ready_at,
  }
})

const prompt = computed(() => {
  if (phase.value) return phase.value.text
  if (!activeSession.value) return settings.value.mode === 'auto' ? '自动练习就绪' : '手动练习就绪'
  const current = Math.min(step.value + 1, repetitions.value)
  return activeSession.value.mode === 'auto' ? `第 ${current} 组` : `开始第 ${Math.min(current + 1, repetitions.value)} 组？`
})

const hint = computed(() => {
  if (busy.value) return '正在记录，请稍候…'
  if (autoPaused.value) return '自动练习已暂停，点击下方按钮继续'
  if (!activeSession.value) return settings.value.mode === 'auto' ? '点击下方开始练习，或按空格键启动' : '点击页面或按空格键开始第 1 组'
  if (remaining.value > 0) return phase.value ? `第 ${step.value + 1} 组 · ${phase.value.text} · 剩余 ` : '本组还剩 '
  if (activeSession.value.mode === 'auto' && step.value < repetitions.value - 1) return '正在自动进入下一组…'
  if (step.value < repetitions.value - 1) return `按空格键或点击屏幕，进入第 ${step.value + 2} 组`
  return `${repetitions.value} 组完成，正在确认记录…`
})

const completedCount = computed(() => activeSession.value?.completed_repetitions ?? repetitions.value)
const uploaded = computed(() => Boolean(activeSession.value?.uploaded_user_id))
const wrongUser = computed(() => Boolean(activeSession.value?.owner_id && training.value?.user && activeSession.value.owner_id !== training.value.user.id))
const resultError = computed(() => activeSession.value?.upload_error || uploadError.value || trainingError.value)
const statusPill = computed(() => {
  if (completedCount.value === 0) return '未完成任何次数'
  if (uploaded.value) return '训练记录已上传'
  if (!activeSession.value?.round_id) return '旧记录仅存本地'
  if (syncing.value) return '正在上传…'
  if (resultError.value) return '上传未成功'
  return '等待上传'
})

const resultNote = computed(() => {
  if (completedCount.value === 0) return '未做完的次数不计入记录，可以重新开始一轮。'
  if (!activeSession.value?.round_id) return '旧的本地记录缺少起止时间，无法补传；请重新开始一轮训练。'
  if (wrongUser.value) return '此轮训练属于开始时登录的账号，请切回该账号后上传。'
  if (uploaded.value) return '可在下方查看本轮起止时间和次数；训练不影响每日打卡和积分。'
  return resultError.value || '登录后上传起止时间与次数；每轮需在一小时内完成，并在结束后五分钟内提交。'
})

// 统计指标
const practiceCount = computed(() => {
  const records = training.value?.records ?? []
  return records.reduce((sum, r) => sum + (r.repetitions || 0), 0)
})

const practiceTotal = computed(() => (trainingError.value ? '榜单暂不可用' : training.value?.leaderboard.length ? `今日 · ${training.value.leaderboard.length} 人` : '暂无记录'))
const allTimeTotal = computed(() => (trainingError.value ? '榜单暂不可用' : training.value?.total_leaderboard.length ? `累计 · ${training.value.total_leaderboard.length} 人` : '暂无记录'))

// 三阶段滑块样式
const phaseWidths = computed(() => [
  settings.value.liftEnd,
  settings.value.relaxEnd - settings.value.liftEnd,
  100 - settings.value.relaxEnd,
])
const phaseStyle = computed(() => ({
  '--lift-end': `${settings.value.liftEnd}%`,
  '--relax-end': `${settings.value.relaxEnd}%`,
}))
const phaseLabels = computed(() =>
  settings.value.phaseNames.map((name, index) => {
    const percent = phaseWidths.value[index]!
    return `${name} ${percent}% (${((settings.value.intervalSeconds * percent) / 100).toFixed(1)}s)`
  })
)

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '请求失败，请稍后重试。'
}

function notify(message: string): void {
  notice.value = message
  if (noticeTimer !== undefined) clearTimeout(noticeTimer)
  noticeTimer = window.setTimeout(() => {
    notice.value = ''
  }, 4000)
}

function applySession(session: LocalPracticeSession): void {
  activeSession.value = session
  remaining.value = Math.max(0, Math.ceil(session.wait_seconds))
  showResult.value = session.completed
  if (session.completed) autoPaused.value = false
}

function reset(message?: string): void {
  localPractice.reset()
  activeSession.value = null
  showResult.value = false
  autoPaused.value = false
  remaining.value = 0
  if (message) notify(message)
}

async function refreshTraining(uploadPending = false): Promise<void> {
  try {
    training.value = await practiceApi.get()
    trainingError.value = ''
    if (uploadPending) await syncTraining()
  } catch (error) {
    trainingError.value = errorMessage(error)
  }
}

async function syncTraining(retryRejected = false): Promise<void> {
  if (syncing.value || !training.value?.user) return
  const userId = training.value.user.id
  syncing.value = true
  uploadError.value = ''
  try {
    for (const item of localPractice.pending(userId, retryRejected)) {
      localPractice.bindOwner(item.round_id, userId)
      const { owner_id: _owner, error: _previous, ...body } = item
      try {
        training.value = await practiceApi.upload({ ...body, expected_user_id: userId })
        localPractice.uploaded(item.round_id, userId)
      } catch (error) {
        uploadError.value = errorMessage(error)
        if (error instanceof ApiError && [400, 403, 409].includes(error.status)) {
          localPractice.rejected(item.round_id, uploadError.value)
        } else {
          break
        }
      }
    }
  } finally {
    const local = localPractice.view()
    if (local && local.round_id === activeSession.value?.round_id) applySession(local)
    syncing.value = false
  }
}

function commitSettings(patch: Partial<PracticePreferences>): void {
  const next = { ...settings.value, ...patch }
  settings.value = next
  savePracticePreferences(next)
  triggerHaptic()
}

function updateRepetitions(count: number): void {
  const safe = Math.max(1, Math.min(20, count))
  draftRepetitions.value = String(safe)
  commitSettings({ repetitions: safe })
}

function updateInterval(sec: number): void {
  const safe = Math.max(2, Math.min(10, sec))
  draftInterval.value = String(safe)
  commitSettings({ intervalSeconds: safe })
}

const phaseTrackRef = ref<HTMLElement | null>(null)
const activeDragHandle = ref<'lift' | 'relax' | null>(null)

function updateFromPointer(clientX: number): void {
  if (!phaseTrackRef.value || !activeDragHandle.value) return
  const rect = phaseTrackRef.value.getBoundingClientRect()
  const rawPercent = Math.round(((clientX - rect.left) / rect.width) * 100)
  const percent = Math.max(0, Math.min(100, rawPercent))
  if (activeDragHandle.value === 'lift') {
    commitSettings({ liftEnd: Math.min(settings.value.relaxEnd, Math.max(0, percent)) })
  } else if (activeDragHandle.value === 'relax') {
    commitSettings({ relaxEnd: Math.max(settings.value.liftEnd, Math.min(100, percent)) })
  }
}

function onPointerMove(e: PointerEvent): void {
  updateFromPointer(e.clientX)
}

function onPointerUp(): void {
  activeDragHandle.value = null
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
}

function startDrag(handle: 'lift' | 'relax', e: PointerEvent): void {
  e.preventDefault()
  activeDragHandle.value = handle
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', onPointerUp)
}

function onTrackPointerDown(e: PointerEvent): void {
  if (!phaseTrackRef.value) return
  const rect = phaseTrackRef.value.getBoundingClientRect()
  const percent = Math.max(0, Math.min(100, Math.round(((e.clientX - rect.left) / rect.width) * 100)))
  const distLift = Math.abs(percent - settings.value.liftEnd)
  const distRelax = Math.abs(percent - settings.value.relaxEnd)
  const handle = distLift <= distRelax ? 'lift' : 'relax'
  activeDragHandle.value = handle
  updateFromPointer(e.clientX)
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', onPointerUp)
}

function adjustLift(delta: number): void {
  const next = Math.max(0, Math.min(settings.value.relaxEnd, settings.value.liftEnd + delta))
  commitSettings({ liftEnd: next })
}

function adjustRelax(delta: number): void {
  const next = Math.max(settings.value.liftEnd, Math.min(100, settings.value.relaxEnd + delta))
  commitSettings({ relaxEnd: next })
}

function updateLift(e: Event): void {
  const val = Number((e.target as HTMLInputElement).value)
  commitSettings({ liftEnd: Math.min(settings.value.relaxEnd, val) })
}

function updateRelax(e: Event): void {
  const val = Number((e.target as HTMLInputElement).value)
  commitSettings({ relaxEnd: Math.max(settings.value.liftEnd, val) })
}

function updatePhaseText(idx: number, e: Event): void {
  const defaults = ['提～', '放松', '休息'] as const
  const names = [...settings.value.phaseNames] as [string, string, string]
  names[idx] = (e.target as HTMLInputElement).value.trim() || defaults[idx]!
  commitSettings({ phaseNames: names })
}

function stepSmooth(): void {
  now.value = Date.now()
  if (activeSession.value && remaining.value > 0 && !completed.value) {
    rafId = requestAnimationFrame(stepSmooth)
  }
}

function kickRaf(): void {
  if (rafId) cancelAnimationFrame(rafId)
  rafId = requestAnimationFrame(stepSmooth)
}

async function begin(): Promise<void> {
  showResult.value = false
  playFeedbackSound('step')
  triggerHaptic(30)
  applySession(localPractice.start(settings.value, training.value?.user?.id))
  kickRaf()
}

async function stepSession(): Promise<void> {
  const session = activeSession.value
  if (busy.value || !session || Date.now() < session.ready_at) return
  busy.value = true
  try {
    applySession(localPractice.step(session.token))
    playFeedbackSound('step')
    triggerHaptic(30)
    kickRaf()
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
  if (activeSession.value && activeSession.value.expires_at <= Date.now()) {
    reset('十分钟未进入下一次，请从第 1 组重新开始。')
  }
  busy.value = true
  try {
    if (!activeSession.value) {
      await begin()
      return
    }
    if (Date.now() < activeSession.value.ready_at) return
    if (activeSession.value.step === activeSession.value.repetitions - 1) {
      busy.value = false
      await completeSession()
      return
    }
    applySession(localPractice.step(activeSession.value.token))
    playFeedbackSound('step')
    triggerHaptic(30)
  } catch (error) {
    notify(errorMessage(error))
  } finally {
    busy.value = false
  }
}

async function restart(): Promise<void> {
  if (busy.value) return
  if (settings.value.mode === 'manual') {
    reset()
    return
  }
  reset()
  try {
    await begin()
  } catch (error) {
    showResult.value = true
    notify(errorMessage(error))
  }
}

function abandon(): void {
  if (busy.value || !activeSession.value || completed.value) return
  applySession(localPractice.complete(activeSession.value.token, true))
  void refreshTraining(true)
}

async function upload(): Promise<void> {
  await refreshTraining()
  if (!training.value?.user) {
    window.location.assign(loginUrl('/practice'))
    return
  }
  await syncTraining(true)
}

function stageClick(event: MouseEvent): void {
  if ((event.target as Element).closest('a, button, input, textarea, select, summary, [contenteditable], [data-interactive], .toast-notice')) {
    return
  }
  void advance()
}

function stageKey(event: KeyboardEvent): void {
  if (
    event.repeat ||
    event.isComposing ||
    event.ctrlKey ||
    event.altKey ||
    event.metaKey ||
    event.shiftKey ||
    ['Tab', 'Escape', 'Shift', 'Control', 'Alt', 'Meta', 'CapsLock', 'Fn', 'Unidentified'].includes(event.key) ||
    (event.target as Element).closest('a, button, input, textarea, select, summary, [contenteditable], [data-interactive]')
  ) {
    return
  }
  event.preventDefault()
  void advance()
}

function formatTime(value: number): string {
  return new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
}

onMounted(() => {
  const saved = localPractice.view()
  if (saved) {
    applySession(saved)
    if (!saved.completed && saved.ready_at > Date.now()) kickRaf()
  }
  void refreshTraining(true)
  poller = window.setInterval(() => {
    if (!document.hidden) void refreshTraining()
  }, 20_000)
  ticker = window.setInterval(() => {
    now.value = Date.now()
    const session = activeSession.value
    remaining.value = session ? Math.max(0, Math.ceil((session.ready_at - now.value) / 1000)) : 0
    document.body.dataset.step = String(step.value)
    if (!session || completed.value || busy.value) return
    if (session.expires_at <= now.value) {
      reset('十分钟未进入下一次，本轮已失效，请从第 1 组重新开始。')
      return
    }
    if (autoPaused.value || document.hidden || now.value < session.ready_at) return
    if (session.step === session.repetitions - 1) void completeSession()
    else if (session.mode === 'auto') void stepSession()
  }, 250)
})

onBeforeUnmount(() => {
  if (ticker) clearInterval(ticker)
  if (poller) clearInterval(poller)
  if (noticeTimer) clearTimeout(noticeTimer)
  if (rafId) cancelAnimationFrame(rafId)
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
})
</script>

<template>
  <main class="practice-page-container" :class="{ 'is-zen-mode': zenMode }">
    <!-- 顶部练习中心 Header (对齐设计图) -->
    <header class="practice-header-hero">
      <div class="header-hero-left">
        <div class="practice-badge-icon" aria-hidden="true">
          <svg class="lotus-svg" viewBox="0 0 32 32" fill="none">
            <path d="M16 4C16 4 11 12 11 18C11 21.3137 13.2386 24 16 24C18.7614 24 21 21.3137 21 18C21 12 16 4 16 4Z" fill="url(#p-lotus-grad)" />
            <path d="M9 13C9 13 4 18 5 23C5.5 25.5 8 26.5 11 25.5C13 24.8 14.5 23 15 21C13 20 10.5 17.5 9 13Z" fill="url(#p-lotus-grad)" opacity="0.85" />
            <path d="M23 13C23 13 28 18 27 23C26.5 25.5 24 26.5 21 25.5C19 24.8 17.5 23 17 21C19 20 21.5 17.5 23 13Z" fill="url(#p-lotus-grad)" opacity="0.85" />
            <defs>
              <linearGradient id="p-lotus-grad" x1="16" y1="4" x2="16" y2="24" gradientUnits="userSpaceOnUse">
                <stop stop-color="#2dd4bf" />
                <stop offset="1" stop-color="#0d9488" />
              </linearGradient>
            </defs>
          </svg>
        </div>
        <div class="header-hero-headings">
          <div class="hero-title-row">
            <h1 class="practice-main-title">练习中心</h1>
            <span class="hero-sub-pill">本地高精计时 · 独立记录</span>
          </div>
          <p class="practice-subtitle">科学训练 · 循序渐进 · 随时随地建立肌肉力量</p>
        </div>
      </div>

      <!-- 右侧三大指标卡片与专注模式开关 -->
      <div class="header-hero-right">
        <div class="stat-capsule-item">
          <span class="capsule-label">今日训练</span>
          <span class="capsule-val">{{ training?.leaderboard?.find(r => r.username === training?.user?.username)?.count ?? 0 }} <small>次</small></span>
        </div>
        <div class="stat-capsule-item">
          <span class="capsule-label">累计完成</span>
          <span class="capsule-val">{{ practiceCount }} <small>次</small></span>
        </div>
        <button
          type="button"
          class="btn-zen-pill"
          :class="{ active: zenMode }"
          :title="zenMode ? '退出沉浸专注' : '开启沉浸专注'"
          @click="zenMode = !zenMode"
        >
          <span>{{ zenMode ? '✕ 退出专注' : '🧘 禅意专注' }}</span>
        </button>
      </div>
    </header>

    <!-- 主工作区：左侧核心训练舞台 + 右侧参数定制面板 -->
    <div class="practice-core-grid" :class="{ 'zen-expanded': zenMode }">
      <!-- 左侧核心舞台卡片 (Hero Training Card) -->
      <section
        class="practice-stage-card"
        tabindex="0"
        :role="activeSession && (remaining > 0 || activeSession.mode === 'auto') ? 'region' : 'button'"
        @click="stageClick"
        @keydown="stageKey"
      >
        <!-- 状态 A: 尚未开始 (准备卡片，对齐设计图) -->
        <div v-if="!activeSession && !completed" class="stage-view-ready">
          <div class="ready-hero-content">
            <span class="plan-tag-badge">
              {{ settings.mode === 'auto' ? '⏱️ 自动连贯练习' : '🖱️ 手动空格推进' }}
            </span>
            <h2 class="plan-hero-title">自主强化训练</h2>
            <p class="plan-hero-desc">
              专注收缩与放松盆底肌群。建议保持自然呼吸，切勿屏气憋劲。
            </p>

            <!-- 核心规格胶囊 -->
            <div class="plan-specs-row">
              <span class="spec-capsule">🔢 目标 <strong>{{ settings.repetitions }}</strong> 组</span>
              <span class="spec-capsule">⏱️ 每组 <strong>{{ settings.intervalSeconds }}</strong> 秒</span>
              <span class="spec-capsule">🫁 <strong>{{ settings.phaseNames.join(' / ') }}</strong></span>
            </div>

            <!-- 开始按钮与快捷操作 -->
            <div class="plan-actions-row" data-interactive>
              <button
                class="btn-primary btn-start-practice"
                type="button"
                :disabled="busy"
                @click="begin"
              >
                ▶ 开始本轮训练
              </button>
              <span class="key-hint-text">按 <kbd>Space</kbd> 空格键亦可开始</span>
            </div>
          </div>

          <!-- 右侧淡雅荷花半透明立绘装饰 -->
          <div class="ready-artwork-bg" aria-hidden="true">
            <svg class="translucent-lotus" viewBox="0 0 200 200" fill="none">
              <circle cx="100" cy="100" r="80" fill="url(#lotus-art-grad)" opacity="0.12" />
              <path d="M100 20C100 20 65 75 65 115C65 138 80 156 100 156C120 156 135 138 135 115C135 75 100 20 100 20Z" fill="url(#lotus-art-grad)" opacity="0.6" />
              <path d="M50 80C50 80 15 115 22 150C25 166 42 172 62 166C76 161 86 150 90 136C76 130 60 112 50 80Z" fill="url(#lotus-art-grad)" opacity="0.45" />
              <path d="M150 80C150 80 185 115 178 150C175 166 158 172 138 166C124 161 114 150 110 136C124 130 140 112 150 80Z" fill="url(#lotus-art-grad)" opacity="0.45" />
              <defs>
                <linearGradient id="lotus-art-grad" x1="100" y1="20" x2="100" y2="180" gradientUnits="userSpaceOnUse">
                  <stop stop-color="#2dd4bf" />
                  <stop offset="1" stop-color="#0d9488" />
                </linearGradient>
              </defs>
            </svg>
          </div>
        </div>

        <!-- 状态 B: 正在训练中 (动态呼吸环舞台) -->
        <div v-else-if="!completed" class="stage-view-active">
          <div
            class="practice-ring-card"
            :class="{
              'phase-lift': phase?.index === 0,
              'phase-relax': phase?.index === 1,
              'phase-rest': phase?.index === 2
            }"
          >
            <div
              class="ring-glow-halo"
              :style="{
                background: 'radial-gradient(circle, ' + (phase?.glow || 'rgba(13, 148, 136, 0.25)') + ' 0%, transparent 70%)'
              }"
            />

            <!-- 发光 SVG 轨道 -->
            <svg class="ring-svg" viewBox="0 0 260 260">
              <circle class="ring-bg-track" cx="130" cy="130" r="114" />
              <circle
                v-if="remaining > 0"
                class="ring-progress-bar"
                cx="130"
                cy="130"
                r="114"
                :stroke="phase?.color || '#10b981'"
                :stroke-dasharray="716"
                :stroke-dashoffset="716 * (1 - smoothProgress)"
                :style="{ filter: 'drop-shadow(0 0 10px ' + (phase?.color || '#10b981') + ')' }"
              />
            </svg>

            <!-- 环内核心状态信息 -->
            <div class="ring-center-info">
              <span
                class="ring-badge-step"
                :style="{
                  color: phase?.color || 'var(--primary)',
                  background: (phase?.color || '#10b981') + '1a',
                  borderColor: (phase?.color || '#10b981') + '40'
                }"
              >
                第 {{ step + 1 }} / {{ repetitions }} 组 · {{ phase?.text ?? '就绪' }}
              </span>
              <div class="ring-countdown-digits">
                00:0{{ remaining }}
              </div>
              <div class="ring-phase-action" :style="{ color: phase?.color || 'var(--text-main)' }">
                {{ phase ? phase.text : (activeSession ? '进入下一组' : '开始') }}
              </div>
            </div>
          </div>

          <!-- 提示与当前说明 -->
          <h2 class="active-prompt-title">{{ prompt }}</h2>
          <p class="active-hint-sub">{{ hint }}</p>

          <!-- 组数进度节点 -->
          <div class="practice-steps-dots" aria-label="训练进度">
            <span
              v-for="index in repetitions"
              :key="index"
              class="step-dot-item"
              :class="{
                done: index - 1 < step,
                current: index - 1 === step
              }"
            >
              {{ index - 1 < step ? '✓' : index }}
            </span>
          </div>

          <!-- 底部控制按钮行 -->
          <div class="stage-active-controls" data-interactive>
            <button
              v-if="activeSession?.mode === 'auto'"
              class="btn-secondary control-pill"
              type="button"
              @click="autoPaused = !autoPaused"
            >
              {{ autoPaused ? '▶ 继续自动练习' : '⏸ 暂停自动计时' }}
            </button>
            <button
              v-if="activeSession"
              class="btn-secondary control-pill text-danger"
              type="button"
              :disabled="busy"
              @click="abandon"
            >
              ✕ 放弃本轮
            </button>
          </div>
        </div>

        <!-- 状态 C: 本轮结算卡片 (绝非惨白丑陋方块！) -->
        <div v-else class="stage-view-completed" data-interactive>
          <div class="completed-result-card">
            <div class="completed-icon-circle" :class="{ 'is-abandoned': activeSession?.abandoned }">
              <span v-if="activeSession?.abandoned">✋</span>
              <span v-else>🎉</span>
            </div>
            <h2 class="completed-headline">
              {{ activeSession?.abandoned ? '本轮训练已提前终止' : '本轮练习圆满完成！' }}
            </h2>
            <p class="completed-summary-text">
              本次完成 <strong>{{ completedCount }}</strong> 组训练
              <span>{{ completedCount === 0 ? '（未完成有效组数，不计入记录）' : uploaded ? '，数据已同步上传云端训练榜。' : '，可点击下方按钮同步至训练榜。' }}</span>
            </p>

            <!-- 操作按钮组 -->
            <div class="completed-actions-row">
              <button class="btn-primary completed-btn" type="button" :disabled="busy" @click="restart">
                再练一轮 ➔
              </button>
              <button
                v-if="completedCount > 0 && !uploaded && activeSession?.round_id"
                class="btn-secondary completed-btn"
                type="button"
                :disabled="syncing || wrongUser"
                @click="upload"
              >
                {{ training?.user ? (syncing ? '正在同步…' : '立即上传云端 ☁️') : '登录后上传' }}
              </button>
              <RouterLink class="btn-secondary completed-btn" to="/">
                返回打卡首页
              </RouterLink>
            </div>

            <!-- 状态反馈胶囊 -->
            <div class="completed-status-row">
              <span class="status-pill-badge" :class="{ ok: uploaded }">
                ● {{ statusPill }}
              </span>
              <span class="status-note-text">{{ resultNote }}</span>
            </div>
          </div>
        </div>
      </section>

      <!-- 右侧练习参数定制面板 (Zen Mode 下隐藏，优雅嵌入无缝融于页面) -->
      <aside v-show="!zenMode" class="practice-config-sidebar" data-interactive>
        <div class="config-card">
          <div class="config-header">
            <div class="config-title-group">
              <span class="config-icon">⚙️</span>
              <h3 class="config-title">练习参数定制</h3>
            </div>
            <!-- 模式切换 Segmented Toggle -->
            <div class="mode-switch-pill">
              <button
                type="button"
                class="mode-switch-btn"
                :class="{ active: settings.mode === 'manual' }"
                @click="commitSettings({ mode: 'manual' })"
              >
                手动
              </button>
              <button
                type="button"
                class="mode-switch-btn"
                :class="{ active: settings.mode === 'auto' }"
                @click="commitSettings({ mode: 'auto' })"
              >
                自动
              </button>
            </div>
          </div>

          <!-- 快捷预设胶囊列表 -->
          <div class="presets-quick-bar">
            <span class="presets-label">快捷方案：</span>
            <div class="presets-list">
              <button
                v-for="p in presets"
                :key="p.id"
                type="button"
                class="preset-chip"
                :class="{ active: settings.repetitions === p.repetitions && settings.intervalSeconds === p.interval }"
                @click="applyPreset(p)"
              >
                {{ p.icon }} {{ p.name }}
              </button>
            </div>
          </div>

          <!-- 参数调节表单 -->
          <div class="config-fields-list">
            <!-- 组数调节 -->
            <div class="config-field-group">
              <div class="field-label-row">
                <span class="field-label">训练组数 (1–20 组)</span>
                <span class="field-current-val"><strong>{{ settings.repetitions }}</strong> 组</span>
              </div>
              <div class="number-chips-row">
                <button
                  v-for="num in [3, 5, 8, 10, 15, 20]"
                  :key="num"
                  type="button"
                  class="chip-btn"
                  :class="{ active: settings.repetitions === num }"
                  @click="updateRepetitions(num)"
                >
                  {{ num }} 组
                </button>
              </div>
            </div>

            <!-- 每组时长调节 -->
            <div class="config-field-group">
              <div class="field-label-row">
                <span class="field-label">每组时长 (2–10 秒)</span>
                <span class="field-current-val"><strong>{{ settings.intervalSeconds }}</strong> 秒</span>
              </div>
              <div class="number-chips-row">
                <button
                  v-for="sec in [3, 4, 5, 6, 8, 10]"
                  :key="sec"
                  type="button"
                  class="chip-btn"
                  :class="{ active: settings.intervalSeconds === sec }"
                  @click="updateInterval(sec)"
                >
                  {{ sec }} 秒
                </button>
              </div>
            </div>

            <!-- 三阶段比例滑块与分配 -->
            <div class="config-field-group phase-slider-box">
              <div class="field-label-row">
                <span class="field-label">三阶段节奏分配</span>
                <span class="field-sub-note">拖动白色手柄或点击微调</span>
              </div>

              <!-- 双滑块时间轴 -->
              <div
                ref="phaseTrackRef"
                class="phase-timeline-wrapper"
                @pointerdown="onTrackPointerDown"
              >
                <div class="phase-color-track">
                  <span class="segment-color seg-lift" :style="{ width: settings.liftEnd + '%' }" title="提肛阶段" />
                  <span class="segment-color seg-relax" :style="{ width: (settings.relaxEnd - settings.liftEnd) + '%' }" title="放松阶段" />
                  <span class="segment-color seg-rest" :style="{ width: (100 - settings.relaxEnd) + '%' }" title="休息阶段" />
                </div>

                <!-- 手柄 1：提收分界手柄 -->
                <div
                  class="phase-handle-thumb handle-lift"
                  :class="{ dragging: activeDragHandle === 'lift' }"
                  :style="{ left: settings.liftEnd + '%' }"
                  title="提收分界（按住左右拖动）"
                  @pointerdown.stop="startDrag('lift', $event)"
                >
                  <div class="thumb-pill" />
                  <span class="thumb-tooltip">提: {{ settings.liftEnd }}%</span>
                </div>

                <!-- 手柄 2：放松分界手柄 -->
                <div
                  class="phase-handle-thumb handle-relax"
                  :class="{ dragging: activeDragHandle === 'relax' }"
                  :style="{ left: settings.relaxEnd + '%' }"
                  title="放松分界（按住左右拖动）"
                  @pointerdown.stop="startDrag('relax', $event)"
                >
                  <div class="thumb-pill" />
                  <span class="thumb-tooltip">放松: {{ settings.relaxEnd }}%</span>
                </div>
              </div>

              <!-- 阶段卡片与快速微调按钮 -->
              <div class="phase-adjust-cards">
                <!-- 阶段 1：提 -->
                <div class="phase-card-item phase-card-lift">
                  <div class="phase-card-head">
                    <span class="phase-card-tag tag-lift">① 提收</span>
                    <span class="stat-sec">{{ (settings.intervalSeconds * settings.liftEnd / 100).toFixed(1) }}秒</span>
                  </div>
                  <div class="phase-card-stats">
                    <strong class="stat-pct text-lift">{{ settings.liftEnd }}%</strong>
                    <div class="stepper-group">
                      <button type="button" class="stepper-btn" title="减少5%" @click="adjustLift(-5)">-5%</button>
                      <button type="button" class="stepper-btn" title="增加5%" @click="adjustLift(5)">+5%</button>
                    </div>
                  </div>
                  <input
                    class="phase-name-input"
                    type="text"
                    maxlength="16"
                    :value="settings.phaseNames[0]"
                    placeholder="提～"
                    @input="updatePhaseText(0, $event)"
                  />
                </div>

                <!-- 阶段 2：放松 -->
                <div class="phase-card-item phase-card-relax">
                  <div class="phase-card-head">
                    <span class="phase-card-tag tag-relax">② 放松</span>
                    <span class="stat-sec">{{ (settings.intervalSeconds * (settings.relaxEnd - settings.liftEnd) / 100).toFixed(1) }}秒</span>
                  </div>
                  <div class="phase-card-stats">
                    <strong class="stat-pct text-relax">{{ settings.relaxEnd - settings.liftEnd }}%</strong>
                    <div class="stepper-group">
                      <button type="button" class="stepper-btn" title="减少5%" @click="adjustRelax(-5)">-5%</button>
                      <button type="button" class="stepper-btn" title="增加5%" @click="adjustRelax(5)">+5%</button>
                    </div>
                  </div>
                  <input
                    class="phase-name-input"
                    type="text"
                    maxlength="16"
                    :value="settings.phaseNames[1]"
                    placeholder="放松"
                    @input="updatePhaseText(1, $event)"
                  />
                </div>

                <!-- 阶段 3：休息 -->
                <div class="phase-card-item phase-card-rest">
                  <div class="phase-card-head">
                    <span class="phase-card-tag tag-rest">③ 休息</span>
                    <span class="stat-sec">{{ (settings.intervalSeconds * (100 - settings.relaxEnd) / 100).toFixed(1) }}秒</span>
                  </div>
                  <div class="phase-card-stats">
                    <strong class="stat-pct text-rest">{{ 100 - settings.relaxEnd }}%</strong>
                    <span class="auto-calc-badge">自动分配</span>
                  </div>
                  <input
                    class="phase-name-input"
                    type="text"
                    maxlength="16"
                    :value="settings.phaseNames[2]"
                    placeholder="休息"
                    @input="updatePhaseText(2, $event)"
                  />
                </div>
              </div>
            </div>
          </div>

          <div class="config-footer-tip">
            <span>💡 本地高精度计时，完成后可随时上传云端同步训练排位。</span>
          </div>
        </div>
      </aside>
    </div>

    <!-- 下方 Bento 卡片：今日训练榜、训练总榜、我的训练历史 -->
    <section v-show="!zenMode" class="practice-ranking-bento">
      <div class="ranking-tabs-header">
        <button
          type="button"
          class="ranking-tab-btn"
          :class="{ active: trainingTab === 'daily' }"
          @click="trainingTab = 'daily'"
        >
          📅 今日训练榜 <span class="tab-badge-pill">{{ practiceTotal }}</span>
        </button>
        <button
          type="button"
          class="ranking-tab-btn"
          :class="{ active: trainingTab === 'all' }"
          @click="trainingTab = 'all'"
        >
          🌟 训练总榜 <span class="tab-badge-pill">{{ allTimeTotal }}</span>
        </button>
        <button
          type="button"
          class="ranking-tab-btn"
          :class="{ active: trainingTab === 'records' }"
          @click="trainingTab = 'records'"
        >
          📋 我的训练历史
        </button>
      </div>

      <!-- TAB 1: 今日训练榜 -->
      <div v-show="trainingTab === 'daily'" class="ranking-table-card">
        <ScrollTable :min-rows="4" :max-rows="8" :row-height="52">
          <table class="modern-ranking-table">
            <thead>
              <tr>
                <th>名次</th>
                <th>用户名</th>
                <th>今日训练次数</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!training?.leaderboard.length">
                <td colspan="3" class="table-empty-cell">登录后完成训练并上传，即可计入今日训练榜。</td>
              </tr>
              <tr
                v-for="record in training?.leaderboard || []"
                :key="`${record.rank}-${record.username}`"
                :class="{ 'is-self': record.username === training?.user?.username }"
              >
                <td>
                  <span v-if="record.rank === 1" class="medal-gold">🥇 1</span>
                  <span v-else-if="record.rank === 2" class="medal-silver">🥈 2</span>
                  <span v-else-if="record.rank === 3" class="medal-bronze">🥉 3</span>
                  <span v-else class="rank-plain">{{ record.rank }}</span>
                </td>
                <td class="username-cell">
                  @{{ record.username }}
                  <span v-if="record.username === training?.user?.username" class="self-tag">你</span>
                </td>
                <td class="count-cell">{{ record.count }} 次</td>
              </tr>
            </tbody>
          </table>
        </ScrollTable>
      </div>

      <!-- TAB 2: 训练总榜 -->
      <div v-show="trainingTab === 'all'" class="ranking-table-card">
        <ScrollTable :min-rows="4" :max-rows="8" :row-height="52">
          <table class="modern-ranking-table">
            <thead>
              <tr>
                <th>名次</th>
                <th>用户名</th>
                <th>累计训练次数</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!training?.total_leaderboard.length">
                <td colspan="3" class="table-empty-cell">暂无累计训练记录。</td>
              </tr>
              <tr
                v-for="record in training?.total_leaderboard || []"
                :key="`${record.rank}-${record.username}`"
                :class="{ 'is-self': record.username === training?.user?.username }"
              >
                <td>
                  <span v-if="record.rank === 1" class="medal-gold">🥇 1</span>
                  <span v-else-if="record.rank === 2" class="medal-silver">🥈 2</span>
                  <span v-else-if="record.rank === 3" class="medal-bronze">🥉 3</span>
                  <span v-else class="rank-plain">{{ record.rank }}</span>
                </td>
                <td class="username-cell">
                  @{{ record.username }}
                  <span v-if="record.username === training?.user?.username" class="self-tag">你</span>
                </td>
                <td class="count-cell">{{ record.count }} 次</td>
              </tr>
            </tbody>
          </table>
        </ScrollTable>
      </div>

      <!-- TAB 3: 我的历史记录 -->
      <div v-show="trainingTab === 'records'" class="ranking-table-card">
        <ScrollTable :min-rows="4" :max-rows="8" :row-height="52">
          <table class="modern-ranking-table">
            <thead>
              <tr>
                <th>开始时间</th>
                <th>结束时间</th>
                <th>完成次数</th>
                <th>模式</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!training?.records.length">
                <td colspan="4" class="table-empty-cell">
                  {{ training?.user ? '暂无已上传的训练历史记录。' : '登录后可上传并查看您的历史训练记录。' }}
                </td>
              </tr>
              <tr v-for="record in training?.records || []" :key="record.round_id">
                <td class="text-dim">{{ formatTime(record.started_at) }}</td>
                <td class="text-dim">{{ formatTime(record.ended_at) }}</td>
                <td class="count-cell">{{ record.repetitions }} 次</td>
                <td>
                  <span class="mode-pill-badge">{{ record.mode === 'auto' ? '⏱️ 自动' : '🖱️ 手动' }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </ScrollTable>
      </div>
    </section>

    <!-- 底部轻提示 -->
    <div v-if="notice" class="toast-notice" role="status" aria-live="polite">
      {{ notice }}
    </div>
  </main>
</template>

<style scoped>
.practice-page-container {
  max-width: 1320px;
  margin: 0 auto;
  padding: 24px 24px 80px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

/* 顶部 Header Hero (对齐设计图) */
.practice-header-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  flex-wrap: wrap;
  padding: 18px 26px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
}

.header-hero-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.practice-badge-icon {
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

.practice-badge-icon .lotus-svg {
  width: 32px;
  height: 32px;
}

.header-hero-headings {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.hero-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.practice-main-title {
  font-size: 24px;
  font-weight: 800;
  color: var(--text-main);
  margin: 0;
  letter-spacing: -0.02em;
}

.hero-sub-pill {
  font-size: 11px;
  font-weight: 700;
  color: var(--primary);
  background: var(--primary-light);
  border: 1px solid var(--primary-border);
  padding: 2px 8px;
  border-radius: var(--radius-pill);
}

.practice-subtitle {
  font-size: 13px;
  color: var(--text-muted);
  margin: 0;
}

.header-hero-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.stat-capsule-item {
  display: flex;
  flex-direction: column;
  padding: 6px 14px;
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  min-width: 90px;
}

.stat-capsule-item .capsule-label {
  font-size: 11px;
  color: var(--text-muted);
}

.stat-capsule-item .capsule-val {
  font-size: 16px;
  font-weight: 800;
  color: var(--primary);
  font-variant-numeric: tabular-nums;
}

.stat-capsule-item .capsule-val small {
  font-size: 11px;
  color: var(--text-muted);
  font-weight: normal;
}

.btn-zen-pill {
  padding: 8px 16px;
  font-size: 13px;
  font-weight: 600;
  border-radius: var(--radius-pill);
  background: var(--bg-card);
  border: 1px solid var(--border);
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-zen-pill:hover {
  color: var(--text-main);
  border-color: var(--primary-border);
}

.btn-zen-pill.active {
  background: var(--primary);
  color: #ffffff;
  border-color: var(--primary);
  box-shadow: 0 4px 12px rgba(13, 148, 136, 0.3);
}

/* 主工作区两栏 Grid (舞台 65% : 参数 35%) */
.practice-core-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(360px, 1fr);
  gap: 24px;
  align-items: stretch; /* 左右两个框始终等高 */
}

.practice-core-grid.zen-expanded {
  grid-template-columns: 1fr;
  max-width: 900px;
  margin: 0 auto;
  width: 100%;
}

/* 左侧核心舞台卡片 */
.practice-stage-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 36px 32px;
  box-shadow: var(--shadow-card);
  min-height: 440px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  position: relative;
  overflow: hidden;
  outline: none;
}

/* 状态 A: 准备开始卡片 (对齐设计图 Hero 展现) */
.stage-view-ready {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  position: relative;
  z-index: 2;
}

.ready-hero-content {
  max-width: 480px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.plan-tag-badge {
  font-size: 12px;
  font-weight: 700;
  color: var(--primary);
  background: var(--primary-light);
  border: 1px solid var(--primary-border);
  padding: 3px 10px;
  border-radius: var(--radius-pill);
  width: fit-content;
}

.plan-hero-title {
  font-size: 28px;
  font-weight: 800;
  color: var(--text-main);
  margin: 0;
  letter-spacing: -0.02em;
}

.plan-hero-desc {
  font-size: 14px;
  color: var(--text-muted);
  line-height: 1.6;
  margin: 0;
}

.plan-specs-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin: 6px 0;
}

.spec-capsule {
  font-size: 12px;
  color: var(--text-main);
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  padding: 5px 12px;
  border-radius: var(--radius-pill);
}

.spec-capsule strong {
  color: var(--primary);
}

.plan-actions-row {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-top: 10px;
}

.btn-start-practice {
  padding: 12px 36px;
  font-size: 16px;
  font-weight: 700;
  border-radius: var(--radius-pill);
  background: linear-gradient(135deg, #0d9488 0%, #10b981 100%);
  color: #ffffff;
  box-shadow: 0 4px 16px rgba(13, 148, 136, 0.35);
  border: none;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-start-practice:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(13, 148, 136, 0.45);
}

.btn-start-practice:active {
  transform: scale(0.98);
}

.key-hint-text {
  font-size: 12px;
  color: var(--text-dim);
}

.key-hint-text kbd {
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  padding: 2px 6px;
  border-radius: 4px;
  font-family: inherit;
}

.ready-artwork-bg {
  position: absolute;
  right: -20px;
  top: 50%;
  transform: translateY(-50%);
  pointer-events: none;
  z-index: 1;
}

.translucent-lotus {
  width: 260px;
  height: 260px;
}

/* 状态 B: 正在进行中 (大动态呼吸环) */
.stage-view-active {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  width: 100%;
}

.practice-ring-card {
  position: relative;
  width: 260px;
  height: 260px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 20px;
}

.ring-glow-halo {
  position: absolute;
  inset: 15px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(13, 148, 136, 0.25) 0%, transparent 70%);
  filter: blur(14px);
  animation: pulseGlow 3s ease-in-out infinite;
}

.practice-ring-card.phase-lift .ring-glow-halo {
  background: radial-gradient(circle, rgba(16, 185, 129, 0.35) 0%, transparent 70%);
}

.practice-ring-card.phase-relax .ring-glow-halo {
  background: radial-gradient(circle, rgba(59, 130, 246, 0.3) 0%, transparent 70%);
}

.practice-ring-card.phase-rest .ring-glow-halo {
  background: radial-gradient(circle, rgba(245, 158, 11, 0.25) 0%, transparent 70%);
}

@keyframes pulseGlow {
  0%, 100% { transform: scale(0.95); opacity: 0.6; }
  50% { transform: scale(1.08); opacity: 1; }
}

.ring-svg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  transform: rotate(-90deg);
}

.ring-bg-track {
  fill: none;
  stroke: var(--bg-subtle);
  stroke-width: 10;
}

.ring-progress-bar {
  fill: none;
  stroke: var(--primary);
  stroke-width: 10;
  stroke-linecap: round;
  transition: stroke 0.35s ease, filter 0.35s ease;
}

.phase-lift .ring-progress-bar {
  stroke: #10b981;
}

.phase-relax .ring-progress-bar {
  stroke: #3b82f6;
}

.phase-rest .ring-progress-bar {
  stroke: #f59e0b;
}

.ring-center-info {
  position: relative;
  z-index: 2;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.ring-badge-step {
  font-size: 12px;
  font-weight: 700;
  color: var(--primary);
  background: var(--primary-light);
  padding: 2px 10px;
  border-radius: var(--radius-pill);
}

.ring-countdown-digits {
  font-size: 44px;
  font-weight: 900;
  color: var(--text-main);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
}

.ring-phase-action {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-muted);
}

.active-prompt-title {
  font-size: 22px;
  font-weight: 800;
  color: var(--text-main);
  margin: 0 0 6px;
}

.active-hint-sub {
  font-size: 13px;
  color: var(--text-muted);
  margin: 0 0 16px;
}

.practice-steps-dots {
  display: flex;
  gap: 8px;
  align-items: center;
  justify-content: center;
  margin-bottom: 20px;
  flex-wrap: wrap;
}

.step-dot-item {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  font-size: 11px;
  font-weight: 700;
  color: var(--text-dim);
  display: flex;
  align-items: center;
  justify-content: center;
}

.step-dot-item.done {
  background: var(--primary);
  border-color: var(--primary);
  color: #ffffff;
}

.step-dot-item.current {
  border-color: var(--primary);
  color: var(--primary);
  background: var(--primary-light);
  box-shadow: 0 0 0 3px rgba(13, 148, 136, 0.2);
}

.stage-active-controls {
  display: flex;
  align-items: center;
  gap: 12px;
}

.control-pill {
  padding: 8px 18px;
  font-size: 13px;
  font-weight: 600;
  border-radius: var(--radius-pill);
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  cursor: pointer;
}

.control-pill:hover {
  background: var(--bg-card);
  border-color: var(--primary-border);
}

.control-pill.text-danger {
  color: #dc2626;
}

.control-pill.text-danger:hover {
  background: #fef2f2;
  border-color: #fca5a5;
}

/* 状态 C: 优雅大气的结算卡片 */
.stage-view-completed {
  width: 100%;
  display: flex;
  justify-content: center;
  padding: 20px 0;
}

.completed-result-card {
  max-width: 520px;
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 14px;
}

.completed-icon-circle {
  width: 68px;
  height: 68px;
  border-radius: 50%;
  background: var(--primary-light);
  border: 2px solid var(--primary-border);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 34px;
  box-shadow: 0 8px 24px rgba(13, 148, 136, 0.2);
}

.completed-icon-circle.is-abandoned {
  background: rgba(245, 158, 11, 0.15);
  border-color: rgba(245, 158, 11, 0.35);
}

.completed-headline {
  font-size: 24px;
  font-weight: 800;
  color: var(--text-main);
  margin: 0;
}

.completed-summary-text {
  font-size: 14px;
  color: var(--text-muted);
  line-height: 1.6;
  margin: 0;
}

.completed-summary-text strong {
  color: var(--primary);
  font-size: 18px;
}

.completed-actions-row {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  margin-top: 8px;
}

.completed-btn {
  padding: 10px 22px;
  font-size: 14px;
  font-weight: 700;
  border-radius: var(--radius-pill);
}

.completed-status-row {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  align-items: center;
}

.status-pill-badge {
  font-size: 12px;
  font-weight: 700;
  padding: 3px 12px;
  border-radius: var(--radius-pill);
  background: var(--bg-subtle);
  color: var(--text-muted);
}

.status-pill-badge.ok {
  background: rgba(16, 185, 129, 0.12);
  color: #10b981;
}

.status-note-text {
  font-size: 12px;
  color: var(--text-dim);
}

/* 右侧参数定制卡片 (绝非霸屏！) */
.practice-config-sidebar {
  display: flex;
  flex-direction: column;
}

.practice-config-sidebar > .config-card {
  flex: 1;
}

.config-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 24px;
  box-shadow: var(--shadow-card);
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.config-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.config-title-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.config-icon {
  font-size: 18px;
}

.config-title {
  font-size: 16px;
  font-weight: 800;
  color: var(--text-main);
  margin: 0;
}

.mode-switch-pill {
  display: flex;
  background: var(--bg-subtle);
  padding: 3px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--border);
}

.mode-switch-btn {
  padding: 4px 12px;
  font-size: 12px;
  font-weight: 600;
  border-radius: var(--radius-pill);
  border: none;
  background: none;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.2s ease;
}

.mode-switch-btn.active {
  background: var(--bg-card);
  color: var(--primary);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08);
}

/* 快捷方案横条 */
.presets-quick-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.presets-label {
  font-size: 12px;
  color: var(--text-dim);
}

.presets-list {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.preset-chip {
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 600;
  border-radius: var(--radius-sm);
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  color: var(--text-main);
  cursor: pointer;
  transition: all 0.2s ease;
}

.preset-chip:hover {
  border-color: var(--primary-border);
}

.preset-chip.active {
  background: var(--primary-light);
  border-color: var(--primary);
  color: var(--primary);
}

/* 表单字段组 */
.config-fields-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.config-field-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.field-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.field-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-main);
}

.field-current-val {
  font-size: 13px;
  color: var(--text-muted);
}

.field-current-val strong {
  color: var(--primary);
}

.field-sub-note {
  font-size: 11px;
  color: var(--text-dim);
}

.number-chips-row {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.chip-btn {
  padding: 5px 12px;
  font-size: 12px;
  font-weight: 600;
  border-radius: var(--radius-pill);
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  color: var(--text-main);
  cursor: pointer;
  transition: all 0.2s ease;
}

.chip-btn:hover {
  border-color: var(--primary-border);
}

.chip-btn.active {
  background: var(--primary);
  color: #ffffff;
  border-color: var(--primary);
}

/* 三阶段滑块与微调组件 */
.phase-slider-box {
  padding: 16px;
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.phase-timeline-wrapper {
  position: relative;
  height: 36px;
  margin: 4px 0 8px;
  display: flex;
  align-items: center;
  cursor: pointer;
  user-select: none;
}

.phase-color-track {
  position: absolute;
  left: 0;
  right: 0;
  height: 12px;
  border-radius: 8px;
  display: flex;
  overflow: hidden;
  box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.15);
}

.segment-color {
  height: 100%;
  transition: width 0.05s linear;
}

.seg-lift {
  background: linear-gradient(90deg, #10b981 0%, #059669 100%);
}

.seg-relax {
  background: linear-gradient(90deg, #38bdf8 0%, #2563eb 100%);
}

.seg-rest {
  background: linear-gradient(90deg, #fbbf24 0%, #d97706 100%);
}

/* 优雅触感手柄 (白色药丸 + 翡翠绿边框 + 投影) */
.phase-handle-thumb {
  position: absolute;
  top: 50%;
  transform: translate(-50%, -50%);
  width: 28px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: ew-resize;
  z-index: 10;
  touch-action: none;
}

.phase-handle-thumb .thumb-pill {
  width: 14px;
  height: 28px;
  border-radius: 6px;
  background: #ffffff;
  border: 2.5px solid var(--primary);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.28);
  transition: transform 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
}

.phase-handle-thumb:hover .thumb-pill,
.phase-handle-thumb.dragging .thumb-pill {
  transform: scale(1.18);
  border-color: #047857;
  box-shadow: 0 0 0 4px rgba(13, 148, 136, 0.25), 0 4px 12px rgba(0, 0, 0, 0.3);
}

.thumb-tooltip {
  position: absolute;
  bottom: calc(100% + 4px);
  left: 50%;
  transform: translateX(-50%);
  padding: 2px 7px;
  background: var(--text-main);
  color: var(--bg);
  border-radius: 4px;
  font-size: 11px;
  font-weight: 700;
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.15s ease;
  white-space: nowrap;
}

.phase-handle-thumb:hover .thumb-tooltip,
.phase-handle-thumb.dragging .thumb-tooltip {
  opacity: 1;
}

/* 三阶段独立微调卡片 (卡片化 + 步进器 + 标签) */
.phase-adjust-cards {
  display: grid;
  /* 空间不够时整张卡换到下一行，而不是把卡片内的文字挤到换行 */
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 10px;
}

.phase-card-item {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  box-shadow: var(--shadow-sm);
  transition: border-color 0.2s ease;
}

.phase-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  min-height: 26px; /* 第三张卡没有微调按钮，也与前两张等高 */
}

.phase-card-tag {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: var(--radius-pill);
  white-space: nowrap;
}

.tag-lift {
  background: rgba(16, 185, 129, 0.14);
  color: #10b981;
}

.tag-relax {
  background: rgba(59, 130, 246, 0.14);
  color: #3b82f6;
}

.tag-rest {
  background: rgba(245, 158, 11, 0.14);
  color: #d97706;
}

.auto-calc-badge {
  font-size: 11px;
  color: var(--text-dim);
  white-space: nowrap;
}

.stepper-group {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: 4px;
}

.stepper-btn {
  min-width: 34px;
  padding: 3px 6px;
  font-size: 11px;
  font-weight: 700;
  border-radius: 4px;
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  color: var(--text-main);
  cursor: pointer;
  transition: all 0.15s ease;
}

.stepper-btn:hover {
  background: var(--primary-light);
  border-color: var(--primary-border);
  color: var(--primary);
}

.phase-card-stats {
  display: flex;
  align-items: center;
  min-height: 28px;
  justify-content: space-between;
  gap: 4px;
}

.stat-pct {
  font-size: 16px;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
}

.text-lift { color: #10b981; }
.text-relax { color: #3b82f6; }
.text-rest { color: #d97706; }

.stat-sec {
  font-size: 12px;
  color: var(--text-dim);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.phase-name-input {
  width: 100%;
  box-sizing: border-box;
  margin-top: auto; /* 三张卡输入框始终贴底对齐 */
  padding: 6px 8px;
  border-radius: var(--radius-xs);
  border: 1px solid var(--border);
  background: var(--bg-subtle);
  font-size: 12px;
  color: var(--text-main);
  outline: none;
  transition: all 0.2s ease;
}

.phase-name-input:focus {
  border-color: var(--primary);
  background: var(--bg-card);
  box-shadow: 0 0 0 2px rgba(13, 148, 136, 0.15);
}

.config-footer-tip {
  font-size: 11px;
  color: var(--text-dim);
  text-align: center;
  border-top: 1px solid var(--border-light);
  padding-top: 12px;
}

/* 下方 Bento 榜单 */
.practice-ranking-bento {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 24px;
  box-shadow: var(--shadow-card);
}

.ranking-tabs-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}

.ranking-tab-btn {
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

.ranking-tab-btn.active {
  background: var(--primary-light);
  color: var(--primary);
  border-color: var(--primary-border);
}

.tab-badge-pill {
  font-size: 11px;
  font-weight: 700;
  background: var(--bg-card);
  padding: 1px 6px;
  border-radius: var(--radius-pill);
}

.ranking-table-card {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}

.table-scroll-wrap {
  overflow-x: auto;
}

.modern-ranking-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.modern-ranking-table th {
  text-align: left;
  padding: 12px 16px;
  font-size: 12px;
  color: var(--text-muted);
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--border);
}

.modern-ranking-table td {
  padding: 14px 16px;
  border-bottom: 1px solid var(--border-light);
  color: var(--text-main);
}

.modern-ranking-table tr:hover td {
  background: var(--primary-light);
}

.modern-ranking-table tr.is-self td {
  background: rgba(13, 148, 136, 0.08);
}

.table-empty-cell {
  text-align: center;
  padding: 36px !important;
  color: var(--text-dim);
}

.medal-gold { color: #d97706; font-weight: 800; }
.medal-silver { color: #64748b; font-weight: 800; }
.medal-bronze { color: #b45309; font-weight: 800; }
.rank-plain { font-weight: 700; color: var(--text-dim); }

.username-cell {
  font-weight: 600;
}

.self-tag {
  font-size: 10px;
  color: #ffffff;
  background: var(--primary);
  padding: 1px 6px;
  border-radius: var(--radius-pill);
  margin-left: 6px;
}

.count-cell {
  font-weight: 800;
  color: var(--primary);
  font-variant-numeric: tabular-nums;
}

/* Toast */
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
@media (max-width: 960px) {
  .practice-core-grid {
    grid-template-columns: 1fr;
  }
  .stage-view-ready {
    flex-direction: column;
    align-items: flex-start;
  }
  .ready-artwork-bg {
    display: none;
  }
  .practice-header-hero {
    flex-direction: column;
    align-items: stretch;
  }
  .header-hero-right {
    justify-content: space-between;
  }
}
</style>
