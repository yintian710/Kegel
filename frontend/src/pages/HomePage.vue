<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { claim, loginUrl, session as sessionApi, status as getStatus, visit, type CheckinEntry, type Session, type StatusData } from '../api'
import { useBodyAttributes } from '../composables/useBodyAttributes'
import { ft, playFeedbackSound, preferenceQuery, triggerHaptic } from '../composables/usePreferences'
import { useIdentity } from '../composables/useIdentity'
import { readPracticePreferences } from '../composables/useLocalPractice'

useBodyAttributes({ class: 'stage-wrap', data: { step: '0' } })

type CompletionKind = 'server' | 'anonymous' | 'review' | 'closed' | null
const identity = useIdentity()
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
const promptText = ref<string | null>(null)
const contentEl = ref<HTMLElement | null>(null)
let noticeTimer: number | undefined
let timer: number | undefined
let pollTimer: number | undefined
let rafId: number | undefined
let unmounted = false

const userPreferences = computed(() => readPracticePreferences())

const repetitions = computed(() => {
  const value = Number(activeSession.value?.repetitions)
  return Number.isInteger(value) && value >= 1 && value <= 20 ? value : 3
})

const completed = computed(() => {
  return showResult.value || Boolean(activeSession.value?.completed) || Boolean(activeSession.value && activeSession.value.step >= repetitions.value)
})

const remaining = computed(() => activeSession.value ? Math.max(0, Math.ceil((readyAt.value - now.value) / 1000)) : 0)

const totalStepDuration = computed(() => {
  return Number(activeSession.value?.interval_seconds ?? activeSession.value?.min_seconds ?? statusData.value?.min_step_seconds) || 8
})

// 连续平滑进度 (0 -> 1)
const stepStartsAt = computed(() => {
  return readyAt.value - totalStepDuration.value * 1000
})

const smoothProgress = computed(() => {
  if (!activeSession.value || remaining.value <= 0) return completed.value ? 1 : 0
  const duration = totalStepDuration.value * 1000
  const elapsed = Math.max(0, now.value - stepStartsAt.value)
  return Math.min(1, Math.max(0, elapsed / duration))
})

// 三阶段动态色彩及文案 (与练习中心一致)
const currentPhase = computed(() => {
  if (!activeSession.value || remaining.value <= 0) return null
  const percent = smoothProgress.value * 100
  const prefs = userPreferences.value
  const liftEnd = prefs.liftEnd ?? 45
  const relaxEnd = prefs.relaxEnd ?? 85
  const names = prefs.phaseNames || ['提～', '放松', '休息']
  if (percent < liftEnd) {
    return {
      index: 0,
      name: names[0] || '提～',
      color: '#10b981', // 翡翠绿
      glow: 'rgba(16, 185, 129, 0.45)',
      hint: '吸气并轻收 · 维持向上',
    }
  } else if (percent < relaxEnd) {
    return {
      index: 1,
      name: names[1] || '放松',
      color: '#3b82f6', // 湛蓝
      glow: 'rgba(59, 130, 246, 0.45)',
      hint: '呼气缓慢放松 · 保持平稳',
    }
  } else {
    return {
      index: 2,
      name: names[2] || '休息',
      color: '#f59e0b', // 暖金
      glow: 'rgba(245, 158, 11, 0.45)',
      hint: '调息静心 · 准备下一组',
    }
  }
})

function stepHomeSmooth(): void {
  if (unmounted) return
  now.value = Date.now()
  if (activeSession.value && remaining.value > 0 && !completed.value) {
    rafId = requestAnimationFrame(stepHomeSmooth)
  }
}

function kickHomeRaf(): void {
  if (rafId) cancelAnimationFrame(rafId)
  rafId = requestAnimationFrame(stepHomeSmooth)
}

const currentStepText = computed(() => {
  if (completed.value) return '打卡完成'
  if (!activeSession.value) return 'Step 1 of 3'
  const phaseText = currentPhase.value ? ` · ${currentPhase.value.name}` : ''
  return `Step ${Math.min(step.value + 1, repetitions.value)} of ${repetitions.value}${phaseText}`
})

const breathingStateHint = computed(() => {
  if (completed.value) return '今日打卡已达成，身心舒畅'
  if (!started.value) return '点击任意位置或按 Space 开始'
  if (busy.value) return '正在记录，请稍候…'
  if (!activeSession.value) return '点击开始第 1 次提肛'
  if (remaining.value > 0) {
    return currentPhase.value ? currentPhase.value.hint : '吸气并轻收... 维持向上'
  }
  if (step.value < repetitions.value - 1) return `点击进入第 ${step.value + 2} 次`
  return `${repetitions.value} 次完成，正在确认记录…`
})

const countdownFormatted = computed(() => {
  if (!activeSession.value || remaining.value <= 0) return '00:08'
  const s = remaining.value
  return `00:${s < 10 ? '0' : ''}${s}`
})

const rewardRules = computed(() => {
  let start = 1
  const rules = (statusData.value?.reward_tiers || []).map(tier => {
    const label = start === tier.through ? `第 ${start} 名` : `第 ${start}-${tier.through} 名`
    start = tier.through + 1
    return { label, value: `${tier.amount} 积分`, amount: tier.amount }
  })
  return rules
})

const topEntries = computed(() => {
  return (statusData.value?.leaderboard || []).slice(0, 5)
})

function notify(message: string): void {
  notice.value = message
  window.clearTimeout(noticeTimer)
  noticeTimer = window.setTimeout(() => { notice.value = '' }, 4000)
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function applyStatus(data: StatusData): void {
  statusData.value = data
  if (data.user && data.wallet) {
    identity.setWallet(data.wallet)
  }
  if (data.streak_days !== undefined) {
    identity.setStreak(data.streak_days)
  }
}

function applySession(item: Session): void {
  activeSession.value = item
  step.value = item.step
  if (item.wait_seconds > 0) {
    readyAt.value = Date.now() + item.wait_seconds * 1000
    kickHomeRaf()
  } else {
    readyAt.value = Date.now()
  }
  if (item.expires_in) {
    expiresAt.value = Date.now() + item.expires_in * 1000
  }
}

async function pollStatus(): Promise<void> {
  if (polling.value) return
  polling.value = true
  try {
    const data = await getStatus()
    applyStatus(data)
  } catch {
    // 忽略轮询偶发错误
  } finally {
    polling.value = false
  }
}

async function advance(): Promise<void> {
  if (busy.value || completed.value) return
  if (!started.value) {
    started.value = true
    await startSession()
    return
  }
  if (!activeSession.value) {
    await startSession()
    return
  }
  if (remaining.value > 0) return
  if (step.value < repetitions.value - 1) {
    await advanceStep()
  } else {
    await completeSession()
  }
}

async function startSession(): Promise<void> {
  busy.value = true
  try {
    const response = await sessionApi.start()
    applySession(response.session)
    playFeedbackSound('step')
    triggerHaptic(20)
  } catch (error) {
    notify(errorMessage(error))
  } finally {
    busy.value = false
  }
}

async function advanceStep(): Promise<void> {
  if (!activeSession.value) return
  busy.value = true
  try {
    const response = await sessionApi.step(activeSession.value.token)
    applySession(response.session)
    playFeedbackSound('step')
    triggerHaptic(30)
  } catch (error) {
    notify(errorMessage(error))
  } finally {
    busy.value = false
  }
}

async function completeSession(): Promise<void> {
  if (!activeSession.value) return
  busy.value = true
  try {
    const response = await sessionApi.complete(activeSession.value.token)
    applySession(response.session)
    if (response.entry) {
      entry.value = response.entry
      completionKind.value = 'server'
      if (response.entry.streak_days !== undefined) {
        identity.setStreak(response.entry.streak_days)
      }
    }
    showResult.value = true
    playFeedbackSound('complete')
    triggerHaptic([40, 50, 40])
    notify('🎉 恭喜！今日 3 组提肛打卡完成！')
    await pollStatus()
  } catch (error) {
    notify(errorMessage(error))
  } finally {
    busy.value = false
  }
}

async function claimReward(): Promise<void> {
  if (!entry.value) {
    window.location.assign(loginUrl('/'))
    return
  }
  if (busy.value || entry.value.reward_status !== 'unclaimed') return
  busy.value = true
  try {
    const response = await claim()
    entry.value = response.entry
    if (statusData.value) {
      statusData.value.entry = response.entry
      statusData.value.wallet = response.wallet
      statusData.value.quota = response.quota
    }
    identity.setWallet(response.wallet)
    notify('🎉 站内积分领取成功，已存入您的钱包！')
    playFeedbackSound('complete')
    triggerHaptic([30, 40, 30])
  } catch (error) {
    notify(errorMessage(error))
  } finally {
    busy.value = false
    await pollStatus()
  }
}

function stageClick(event: MouseEvent): void {
  if ((event.target as Element).closest('a, button, input, textarea, select, [contenteditable], [data-interactive], .toast-notice')) return
  void advance()
}

function stageKey(event: KeyboardEvent): void {
  if (event.repeat || event.isComposing || event.ctrlKey || event.altKey || event.metaKey || event.shiftKey || ['Tab', 'Escape'].includes(event.key) || (event.target as Element).closest('a, button, input, textarea, select, [contenteditable], [data-interactive]')) return
  if (event.code === 'Space' || event.key === 'Enter') {
    event.preventDefault()
    void advance()
  }
}

onMounted(async () => {
  try {
    const value = await visit()
    applyStatus(value)
    if (value.entry || (value.session?.completed || (value.session && value.session.step >= value.session.repetitions))) {
      started.value = true
      if (value.entry) {
        entry.value = value.entry
        completionKind.value = 'server'
      } else if (value.session) {
        applySession(value.session)
      }
      showResult.value = true
    }
  } catch (error) {
    notify(errorMessage(error))
  }

  timer = window.setInterval(() => {
    now.value = Date.now()
    if (!started.value || busy.value || polling.value || completed.value) return
    if (activeSession.value && expiresAt.value && Date.now() >= expiresAt.value) {
      notify('十分钟未进入下一次，本轮已失效，请重新开始。')
      activeSession.value = null
      started.value = false
      return
    }
    if (activeSession.value && !document.hidden && Date.now() >= readyAt.value && step.value === repetitions.value - 1) {
      void completeSession()
    }
  }, 250)
  pollTimer = window.setInterval(pollStatus, 20_000)
})

onBeforeUnmount(() => {
  unmounted = true
  if (timer) clearInterval(timer)
  if (pollTimer) clearInterval(pollTimer)
  if (noticeTimer) clearTimeout(noticeTimer)
  if (rafId) cancelAnimationFrame(rafId)
})
</script>

<template>
  <main
    class="home-stage-wrap"
    tabindex="0"
    role="button"
    aria-label="打卡中心，按空格键或点击操作"
    @click="stageClick"
    @keydown="stageKey"
  >
    <!-- 空灵禅意背景图腾 (远山、微雾、叠石与荷花枝) -->
    <div class="zen-background-layer" aria-hidden="true">
      <div class="zen-leaf-corner" />
      <div class="zen-mist-hills" />
      <div class="zen-stones-graphic" />
    </div>

    <div ref="contentEl" class="home-content-container">
      <!-- 居中核心打卡舞台 (Hero Stage) -->
      <section class="breathing-hero-stage">
        <div
          class="breathing-ring-card"
          :class="{
            'is-breathing': activeSession && remaining > 0,
            'is-completed': completed
          }"
        >
          <!-- 呼吸光晕与粒子 -->
          <div
            class="ring-glow-halo"
            :style="{
              background: 'radial-gradient(circle, ' + (currentPhase?.glow || (completed ? 'rgba(16, 185, 129, 0.3)' : 'rgba(13, 148, 136, 0.15)')) + ' 0%, transparent 75%)'
            }"
          />

          <!-- 发光 SVG 圆环进度条 -->
          <svg class="breathing-svg" viewBox="0 0 280 280">
            <!-- 背景外细轨道 -->
            <circle class="ring-track" cx="140" cy="140" r="124" />
            <!-- 动态环形进度条 (缓缓匀速旋转 + 随阶段变色) -->
            <circle
              v-if="activeSession && remaining > 0"
              class="ring-indicator"
              cx="140"
              cy="140"
              r="124"
              :stroke="currentPhase?.color || '#10b981'"
              :stroke-dasharray="779"
              :stroke-dashoffset="779 * (1 - smoothProgress)"
              :style="{ filter: 'drop-shadow(0 0 10px ' + (currentPhase?.color || '#10b981') + ')' }"
            />
            <!-- 完成状态下的高光环 -->
            <circle
              v-else-if="completed"
              class="ring-completed-glow"
              cx="140"
              cy="140"
              r="124"
            />
          </svg>

          <!-- 环内核心信息排版 -->
          <div class="ring-inner-box">
            <!-- 顶部动作/健康状态图标 -->
            <div class="ring-icon-box">
              <span v-if="completed">🎉</span>
              <span v-else-if="activeSession && remaining > 0">{{ currentPhase?.index === 0 ? '🫁' : currentPhase?.index === 1 ? '🌊' : '✨' }}</span>
              <span v-else>🌿</span>
            </div>

            <!-- 阶段组数徽章 -->
            <span
              class="ring-step-pill"
              :style="{
                color: currentPhase?.color || (completed ? 'var(--emerald)' : 'var(--primary)'),
                background: (currentPhase?.color || (completed ? '#10b981' : '#0d9488')) + '18',
                borderColor: (currentPhase?.color || (completed ? '#10b981' : '#0d9488')) + '35'
              }"
            >
              {{ currentStepText }}
            </span>

            <!-- 超大等宽倒计时数字 -->
            <div class="ring-timer-digits">
              {{ completed ? '00:00' : countdownFormatted }}
            </div>

            <!-- 呼吸动作指引文案 -->
            <div
              class="ring-instruction"
              :style="{ color: currentPhase?.color || (completed ? 'var(--emerald)' : 'var(--text-main)') }"
            >
              {{ breathingStateHint }}
            </div>
          </div>
        </div>

        <!-- 3步打卡步进小节点 -->
        <div class="step-progress-dots" aria-label="三步练习进程">
          <div
            v-for="idx in repetitions"
            :key="idx"
            class="progress-dot"
            :class="{
              done: completed || (activeSession && idx - 1 < step),
              active: activeSession && idx - 1 === step,
              idle: !activeSession && !completed
            }"
          >
            <span class="dot-num">{{ (completed || (activeSession && idx - 1 < step)) ? '✓' : idx }}</span>
            <span class="dot-text">第 {{ idx }} 组</span>
          </div>
        </div>

        <!-- 快捷操作提示 -->
        <div class="stage-sub-hint">
          <span v-if="!completed">按 <kbd>Space</kbd> 空格键或点击屏幕任意位置进入下一步</span>
          <span v-else class="text-success">🎉 今日打卡任务已顺利达成！请在右侧奖励栏领取积分。</span>
        </div>
      </section>

      <!-- 底部 Bento Grid 双栏展示 (今日排行榜 vs 今日打卡奖励) -->
      <section class="home-bento-grid" data-interactive>
        <!-- 左卡片: 今日排行榜 -->
        <div class="bento-card leaderboard-card">
          <div class="bento-card-header">
            <div class="bento-title-group">
              <span class="bento-icon">🏆</span>
              <h2 class="bento-title">今日排行榜</h2>
              <span class="live-update-badge">
                <span class="live-dot" /> 实时更新
              </span>
            </div>
            <RouterLink class="bento-more-link" to="/leaderboard">
              查看全部 ➔
            </RouterLink>
          </div>

          <div class="leaderboard-list">
            <div
              v-for="item in topEntries"
              :key="item.position"
              class="leaderboard-item"
              :class="{
                'is-skipped': item.skipped,
                'top-1': item.rank === 1,
                'top-2': item.rank === 2,
                'top-3': item.rank === 3,
                'is-self': item.username === statusData?.user?.username
              }"
            >
              <!-- 奖牌/名次 -->
              <div class="rank-medal-box">
                <span v-if="item.rank === 1" class="medal-gold">🥇</span>
                <span v-else-if="item.rank === 2" class="medal-silver">🥈</span>
                <span v-else-if="item.rank === 3" class="medal-bronze">🥉</span>
                <span v-else-if="item.skipped" class="medal-number" title="不计入排名">—</span>
                <span v-else class="medal-number">{{ item.rank }}</span>
              </div>

              <!-- 头像与用户名 -->
              <div class="user-meta">
                <div class="user-avatar-circle">
                  {{ item.username.slice(0, 1).toUpperCase() }}
                </div>
                <div class="user-details">
                  <span class="username-text">@{{ item.username }}</span>
                  <span v-if="item.username === statusData?.user?.username" class="self-tag">你</span>
                </div>
              </div>

              <!-- 连续打卡徽章 (假定默认展示或联动) -->
              <div v-if="item.skipped" class="skipped-tag">不计排名</div>
              <div v-else class="streak-tag">
                <span>🔥 连续打卡</span>
              </div>

              <!-- 奖励积分 -->
              <div class="reward-points">
                +{{ item.amount }} 分
              </div>

              <!-- 完成绿色对勾 -->
              <div class="check-mark">
                ✓
              </div>
            </div>

            <div v-if="!topEntries.length" class="empty-list-hint">
              <span>🌟 今日第一位登顶者虚位以待，快来打卡吧！</span>
            </div>
          </div>
        </div>

        <!-- 右卡片: 今日打卡奖励与领取 -->
        <div class="bento-card rewards-card">
          <div class="bento-card-header">
            <div class="bento-title-group">
              <span class="bento-icon">🎁</span>
              <h2 class="bento-title">今日打卡奖励</h2>
            </div>
            <div class="deadline-pill">
              🕒 开放打卡时间 {{ statusData?.deadline ?? '22:00' }}
            </div>
          </div>

          <!-- 阶梯奖励列表 -->
          <div class="rewards-tiers-list">
            <div
              v-for="tier in rewardRules"
              :key="tier.label"
              class="reward-tier-row"
            >
              <div class="tier-left">
                <span class="crown-icon">👑</span>
                <span class="tier-label">{{ tier.label }}</span>
              </div>
              <div class="tier-amount">
                <strong>{{ tier.amount }}</strong> 积分
              </div>
            </div>
          </div>

          <!-- 打卡结算领奖区 (当用户已完成打卡时高亮) -->
          <div v-if="entry" class="claim-action-panel">
            <div class="claim-info">
              <div class="claim-rank">
                今日排名：<strong v-if="entry.skipped">不计入排名</strong><strong v-else>第 {{ entry.rank }} 位</strong>
              </div>
              <div class="claim-pts">奖励积分：<strong>{{ entry.amount }} 积分</strong></div>
            </div>
            <button
              v-if="entry.reward_status === 'unclaimed'"
              class="btn-primary claim-submit-btn"
              type="button"
              :disabled="busy"
              @click="claimReward"
            >
              {{ busy ? '领取中…' : '立即领取积分 💰' }}
            </button>
            <div v-else class="claimed-badge">
              ✓ 积分已到账
            </div>
          </div>

          <div v-else-if="!statusData?.user" class="login-prompt-box">
            <p>登录 LINUX DO 账号后完成打卡，即可参与每日排位并赢取积分奖励。</p>
            <RouterLink class="btn-primary btn-sm" :to="loginUrl('/')">
              立即登录
            </RouterLink>
          </div>

          <!-- 底部说明信息 -->
          <div class="card-footer-tip">
            <span>💡 提示：每日 {{ statusData?.deadline ?? '22:00' }} 开放打卡，开放后完成打卡即可参与每日积分瓜分。</span>
          </div>
        </div>
      </section>
    </div>

    <!-- 底部轻提示 -->
    <div v-if="notice" class="toast-notice" role="status" aria-live="polite">
      {{ notice }}
    </div>
  </main>
</template>

<style scoped>
.home-stage-wrap {
  position: relative;
  min-height: calc(100vh - 65px);
  padding: 30px 24px 60px;
  outline: none;
  overflow: hidden;
}

/* 禅意水墨意境装饰层 */
.zen-background-layer {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  overflow: hidden;
}

.zen-leaf-corner {
  position: absolute;
  top: -20px;
  left: -20px;
  width: 260px;
  height: 260px;
  background: radial-gradient(circle at 20% 20%, rgba(13, 148, 136, 0.12) 0%, transparent 60%);
  border-radius: 50%;
  filter: blur(30px);
}

.zen-mist-hills {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 240px;
  background: linear-gradient(180deg, transparent 0%, rgba(204, 251, 241, 0.25) 100%);
  pointer-events: none;
}

[data-theme="dark"] .zen-mist-hills {
  background: linear-gradient(180deg, transparent 0%, rgba(20, 184, 166, 0.05) 100%);
}

.home-content-container {
  position: relative;
  z-index: 1;
  max-width: 1180px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 36px;
}

/* ================= 核心呼吸舞台 ================= */
.breathing-hero-stage {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 20px 0 10px;
}

.breathing-ring-card {
  position: relative;
  width: 280px;
  height: 280px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.breathing-ring-card:hover {
  transform: scale(1.02);
}

.ring-glow-halo {
  position: absolute;
  inset: 10px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(13, 148, 136, 0.15) 0%, rgba(45, 212, 191, 0.05) 60%, transparent 75%);
  filter: blur(16px);
  transition: all 0.5s ease;
}

.breathing-ring-card.is-breathing .ring-glow-halo {
  background: radial-gradient(circle, rgba(13, 148, 136, 0.28) 0%, rgba(45, 212, 191, 0.12) 60%, transparent 80%);
  animation: pulseAura 4s infinite ease-in-out;
}

@keyframes pulseAura {
  0%, 100% { transform: scale(0.96); opacity: 0.7; }
  50% { transform: scale(1.06); opacity: 1; }
}

.breathing-svg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  transform: rotate(-90deg);
}

.ring-track {
  fill: none;
  stroke: rgba(13, 148, 136, 0.15);
  stroke-width: 8;
}

[data-theme="dark"] .ring-track {
  stroke: rgba(20, 184, 166, 0.2);
}

.ring-indicator {
  fill: none;
  stroke: #10b981;
  stroke-width: 8;
  stroke-linecap: round;
  transition: stroke 0.35s ease, filter 0.35s ease;
}

.ring-completed-glow {
  fill: none;
  stroke: var(--emerald);
  stroke-width: 8;
  filter: drop-shadow(0 0 8px rgba(16, 185, 129, 0.6));
}

.ring-inner-box {
  position: relative;
  z-index: 2;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 20px;
}

.ring-icon-box {
  font-size: 26px;
  line-height: 1;
  margin-bottom: 6px;
}

.ring-step-pill {
  font-size: 12px;
  font-weight: 600;
  color: var(--primary);
  background: var(--primary-light);
  border: 1px solid var(--primary-border);
  padding: 2px 10px;
  border-radius: var(--radius-pill);
  margin-bottom: 6px;
}

.ring-timer-digits {
  font-size: 42px;
  font-weight: 800;
  letter-spacing: -0.02em;
  color: var(--text-main);
  font-variant-numeric: tabular-nums;
  line-height: 1.1;
  margin-bottom: 6px;
}

.ring-instruction {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-muted);
  max-width: 170px;
  line-height: 1.4;
}

/* 进度小节点 */
.step-progress-dots {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-top: 24px;
}

.progress-dot {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-muted);
}

.dot-num {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  background: var(--bg-card);
  border: 1px solid var(--border);
  color: var(--text-dim);
  transition: all 0.2s ease;
}

.progress-dot.active .dot-num {
  background: var(--primary);
  border-color: var(--primary);
  color: #ffffff;
  box-shadow: 0 0 10px rgba(13, 148, 136, 0.4);
}

.progress-dot.done .dot-num {
  background: var(--emerald-light);
  border-color: var(--emerald);
  color: var(--emerald);
}

.progress-dot.active {
  color: var(--primary);
  font-weight: 600;
}

.progress-dot.done {
  color: var(--text-main);
}

.stage-sub-hint {
  margin-top: 14px;
  font-size: 13px;
  color: var(--text-muted);
}

.stage-sub-hint kbd {
  display: inline-block;
  padding: 2px 6px;
  font-size: 11px;
  font-family: inherit;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 4px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}

/* ================= 底部 Bento 双栏 ================= */
.home-bento-grid {
  display: grid;
  grid-template-columns: 1.15fr 0.85fr;
  gap: 24px;
  align-items: stretch;
}

.bento-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 22px 24px;
  box-shadow: var(--shadow-card);
  display: flex;
  flex-direction: column;
}

.bento-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 18px;
}

.bento-title-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.bento-icon {
  font-size: 18px;
}

.bento-title {
  font-size: 16px;
  font-weight: 700;
  margin: 0;
  color: var(--text-main);
}

.live-update-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: 600;
  color: var(--emerald);
  background: var(--emerald-light);
  padding: 2px 8px;
  border-radius: var(--radius-pill);
}

.live-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--emerald);
  animation: liveBlink 2s infinite ease-in-out;
}

@keyframes liveBlink {
  0%, 100% { opacity: 0.4; }
  50% { opacity: 1; }
}

.bento-more-link {
  font-size: 12px;
  font-weight: 600;
  color: var(--primary);
  text-decoration: none;
}

.bento-more-link:hover {
  text-decoration: underline;
}

/* 排行榜单项样式 */
.leaderboard-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.leaderboard-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  border-radius: var(--radius-sm);
  background: var(--bg-card-subtle);
  border: 1px solid var(--border-light);
  transition: all 0.2s ease;
}

.leaderboard-item:hover {
  border-color: var(--primary-border);
  background: var(--bg-card);
  transform: translateX(2px);
}

.leaderboard-item.is-skipped {
  opacity: 0.5;
  filter: grayscale(1);
}

.skipped-tag {
  padding: 2px 8px;
  border-radius: 9999px;
  background: var(--bg-subtle);
  color: var(--text-dim);
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.leaderboard-item.top-1 {
  background: linear-gradient(90deg, rgba(254, 243, 199, 0.35) 0%, var(--bg-card-subtle) 100%);
  border-color: rgba(245, 158, 11, 0.3);
}

.rank-medal-box {
  width: 24px;
  text-align: center;
  font-size: 16px;
  font-weight: 700;
}

.medal-number {
  font-size: 13px;
  color: var(--text-dim);
}

.user-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
}

.user-avatar-circle {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--primary) 0%, #065f46 100%);
  color: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  flex-shrink: 0;
}

.username-text {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-main);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.self-tag {
  font-size: 10px;
  color: #ffffff;
  background: var(--primary);
  padding: 1px 4px;
  border-radius: 3px;
  margin-left: 4px;
}

.streak-tag {
  font-size: 11px;
  color: #b45309;
  background: var(--amber-light);
  padding: 2px 6px;
  border-radius: 4px;
  white-space: nowrap;
}

.reward-points {
  font-size: 13px;
  font-weight: 700;
  color: var(--primary);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.check-mark {
  color: var(--emerald);
  font-weight: 800;
  font-size: 14px;
}

.empty-list-hint {
  padding: 24px;
  text-align: center;
  font-size: 13px;
  color: var(--text-dim);
}

/* 奖励卡片 */
.deadline-pill {
  font-size: 12px;
  color: var(--text-muted);
  background: var(--bg-subtle);
  padding: 3px 8px;
  border-radius: var(--radius-pill);
}

.rewards-tiers-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 18px;
}

.reward-tier-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  background: var(--bg-subtle);
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-light);
}

.tier-left {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-main);
}

.crown-icon {
  font-size: 15px;
}

.tier-amount {
  font-size: 13px;
  color: var(--text-muted);
}

.tier-amount strong {
  font-size: 15px;
  font-weight: 800;
  color: var(--primary);
  font-variant-numeric: tabular-nums;
}

.claim-action-panel {
  margin-top: auto;
  padding: 14px;
  border-radius: var(--radius-sm);
  background: var(--primary-light);
  border: 1px solid var(--primary-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.claim-info {
  font-size: 13px;
  color: var(--text-main);
}

.claim-info strong {
  color: var(--primary);
  font-weight: 700;
}

.claim-submit-btn {
  padding: 8px 16px;
  font-size: 13px;
  white-space: nowrap;
}

.claimed-badge {
  font-size: 13px;
  font-weight: 700;
  color: var(--emerald);
}

.login-prompt-box {
  margin-top: auto;
  padding: 12px;
  background: var(--bg-subtle);
  border-radius: var(--radius-sm);
  font-size: 12px;
  color: var(--text-muted);
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.card-footer-tip {
  margin-top: 14px;
  font-size: 11px;
  color: var(--text-dim);
}

@media (max-width: 860px) {
  .home-bento-grid {
    grid-template-columns: 1fr;
  }
}
</style>
