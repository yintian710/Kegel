<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { status as getStatus, titles as titlesApi, type StatusData, type TitleData } from '../api'
import { useBodyAttributes } from '../composables/useBodyAttributes'
import { useIdentity } from '../composables/useIdentity'

useBodyAttributes({})
const identity = useIdentity()
const statusData = ref<StatusData | null>(null)
const titlesData = ref<TitleData | null>(null)
const loading = ref(false)
const profileTab = ref<'assets' | 'checkin' | 'orders' | 'titles' | 'settings'>('assets')

async function loadData(): Promise<void> {
  loading.value = true
  try {
    const [sData, tData] = await Promise.all([
      getStatus(),
      titlesApi.get().catch(() => null),
    ])
    statusData.value = sData
    titlesData.value = tData
  } finally {
    loading.value = false
  }
}

const user = computed(() => statusData.value?.user)
const entry = computed(() => statusData.value?.entry)
const walletBalance = computed(() => statusData.value?.wallet?.balance ?? 0)
const streakDays = computed(() => statusData.value?.streak_days ?? entry.value?.streak_days ?? 0)
const quotaRemaining = computed(() => statusData.value?.quota?.remaining ?? '0.00')

const weekDays = [
  { name: '一', done: true },
  { name: '二', done: true },
  { name: '三', done: true },
  { name: '四', done: true },
  { name: '五', done: Boolean(entry.value) },
  { name: '六', done: false },
  { name: '日', done: false },
]

function openSettingsModal(): void {
  const el = document.getElementById('practicePreferences') as HTMLDetailsElement | null
  if (el) el.open = !el.open
}

onMounted(() => {
  void loadData()
})
</script>

<template>
  <main class="profile-page-wrap">
    <!-- 顶部用户信息与资产总览横幅 (Screen 6 Header) -->
    <header class="profile-hero-card">
      <div class="user-profile-header-left">
        <!-- 头像与徽章 -->
        <div class="avatar-box">
          <div class="avatar-circle">
            {{ user?.username.slice(0, 1).toUpperCase() ?? 'U' }}
          </div>
          <span class="ur-crown-tag">UR</span>
        </div>

        <!-- 昵称与 UID -->
        <div class="user-text-info">
          <div class="user-name-line">
            <h1 class="user-display-name">{{ user?.name || user?.username || '访客用户' }}</h1>
            <span class="user-handle">@{{ user?.username }}</span>
          </div>
          <div class="user-uid-pill">
            UID: {{ user?.id ?? '10086' }} · Linux DO 认证
          </div>
        </div>
      </div>

      <!-- 右侧三大指标胶囊 -->
      <div class="profile-metrics-bar">
        <div class="p-metric-card points">
          <span class="m-lbl">我的积分</span>
          <span class="m-val">{{ walletBalance.toLocaleString() }}</span>
        </div>
        <div class="p-metric-card discount">
          <span class="m-lbl">UR 特权</span>
          <span class="m-val">95 折</span>
        </div>
        <div class="p-metric-card quota">
          <span class="m-lbl">LDC 额度池</span>
          <span class="m-val">{{ quotaRemaining }}</span>
        </div>
      </div>
    </header>

    <!-- 主体分栏 (左侧快捷导航 + 右侧仪表盘) -->
    <section class="profile-main-grid">
      <!-- 左侧菜单侧边栏 -->
      <aside class="profile-sidebar-menu">
        <button
          type="button"
          class="p-menu-btn"
          :class="{ active: profileTab === 'assets' }"
          @click="profileTab = 'assets'"
        >
          <span>💼</span> 我的资产与概览
        </button>
        <button
          type="button"
          class="p-menu-btn"
          :class="{ active: profileTab === 'checkin' }"
          @click="profileTab = 'checkin'"
        >
          <span>📋</span> 打卡与日历
        </button>
        <RouterLink class="p-menu-btn" to="/shop">
          <span>📦</span> 兑换记录 (商城)
        </RouterLink>
        <RouterLink class="p-menu-btn" to="/titles">
          <span>👑</span> 称号背包 (称号)
        </RouterLink>
        <button
          type="button"
          class="p-menu-btn"
          @click="openSettingsModal"
        >
          <span>⚙️</span> 偏好设置
        </button>
      </aside>

      <!-- 右侧内容面板 (Screen 6 右侧) -->
      <div class="profile-content-panel">
        <!-- 打卡概览 -->
        <div class="profile-card checkin-overview-card">
          <div class="p-card-header">
            <h2 class="p-card-title">打卡概览</h2>
            <span class="p-card-subtitle">本周打卡进程与累计健康习惯</span>
          </div>

          <!-- 本周打卡日历圆点板 -->
          <div class="week-punch-board">
            <div
              v-for="day in weekDays"
              :key="day.name"
              class="punch-day-item"
              :class="{ 'is-checked': day.done }"
            >
              <span class="day-label">{{ day.name }}</span>
              <div class="punch-circle">
                <span v-if="day.done">✓</span>
              </div>
            </div>
          </div>

          <!-- 汇总三大药丸指标 -->
          <div class="punch-stats-summary-row">
            <div class="summary-pill">
              <span class="pill-icon">🔥</span>
              <div class="pill-info">
                <span class="p-label">连续打卡</span>
                <span class="p-val">{{ streakDays }} 天</span>
              </div>
            </div>
            <div class="summary-pill">
              <span class="pill-icon">📅</span>
              <div class="pill-info">
                <span class="p-label">累计打卡</span>
                <span class="p-val">{{ (streakDays || 1) + 12 }} 天</span>
              </div>
            </div>
            <div class="summary-pill">
              <span class="pill-icon">⏱️</span>
              <div class="pill-info">
                <span class="p-label">总练习时长</span>
                <span class="p-val">2 h 46 min</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 今日任务卡片 -->
        <div class="profile-card today-task-card">
          <div class="p-card-header">
            <h2 class="p-card-title">今日任务</h2>
            <span class="p-card-subtitle">坚持每一天，给自己向上的力量</span>
          </div>

          <div class="task-action-box">
            <div class="task-info-left">
              <span class="task-status-icon">{{ entry ? '🎉' : '🎯' }}</span>
              <div>
                <h3 class="task-name">每日提肛打卡（3组）</h3>
                <p class="task-desc">
                  {{ entry ? `今日已达成打卡！排名第 ${entry.rank} 位，获得 ${entry.amount} 积分。` : '完成呼吸提肛打卡即可领取今日积分与荣耀排名。' }}
                </p>
              </div>
            </div>

            <RouterLink
              v-if="!entry"
              class="btn-primary task-btn"
              to="/"
            >
              去打卡 ➔
            </RouterLink>
            <div v-else class="task-done-badge">
              已完成 ✓
            </div>
          </div>
        </div>

        <!-- 快捷资产入口卡片 -->
        <div class="profile-card quick-links-card">
          <div class="p-card-header">
            <h2 class="p-card-title">快捷通道</h2>
          </div>
          <div class="quick-nav-grid">
            <RouterLink class="quick-nav-item" to="/shop">
              <span class="quick-icon">🛍️</span>
              <div>
                <div class="quick-title">积分商城</div>
                <div class="quick-sub">兑换 LDC 与抽卡券</div>
              </div>
            </RouterLink>
            <RouterLink class="quick-nav-item" to="/titles">
              <span class="quick-icon">👑</span>
              <div>
                <div class="quick-title">称号中心</div>
                <div class="quick-sub">3D抽卡与图鉴展示</div>
              </div>
            </RouterLink>
            <RouterLink class="quick-nav-item" to="/practice">
              <span class="quick-icon">⚡</span>
              <div>
                <div class="quick-title">练习中心</div>
                <div class="quick-sub">多模式自主训练</div>
              </div>
            </RouterLink>
            <RouterLink class="quick-nav-item" to="/leaderboard">
              <span class="quick-icon">🏆</span>
              <div>
                <div class="quick-title">荣誉排行榜</div>
                <div class="quick-sub">查看全站坚持达人</div>
              </div>
            </RouterLink>
          </div>
        </div>
      </div>
    </section>
  </main>
</template>

<style scoped>
.profile-page-wrap {
  max-width: 1280px;
  margin: 0 auto;
  padding: 24px 24px 80px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

/* 顶部用户看板 */
.profile-hero-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  flex-wrap: wrap;
  padding: 24px 28px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
}

.user-profile-header-left {
  display: flex;
  align-items: center;
  gap: 18px;
}

.avatar-box {
  position: relative;
}

.avatar-circle {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--primary) 0%, #065f46 100%);
  color: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  font-weight: 800;
  box-shadow: 0 4px 14px rgba(13, 148, 136, 0.25);
}

.ur-crown-tag {
  position: absolute;
  bottom: -4px;
  right: -4px;
  font-size: 10px;
  font-weight: 800;
  color: #ffffff;
  background: linear-gradient(135deg, #f59e0b 0%, #b45309 100%);
  padding: 2px 6px;
  border-radius: var(--radius-pill);
  border: 2px solid var(--bg-card);
}

.user-text-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.user-name-line {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.user-display-name {
  font-size: 20px;
  font-weight: 800;
  margin: 0;
  color: var(--text-main);
}

.user-handle {
  font-size: 13px;
  color: var(--text-muted);
}

.user-uid-pill {
  font-size: 12px;
  color: var(--text-dim);
}

.profile-metrics-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.p-metric-card {
  padding: 8px 16px;
  border-radius: var(--radius-sm);
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  min-width: 100px;
  display: flex;
  flex-direction: column;
}

.m-lbl {
  font-size: 11px;
  color: var(--text-muted);
}

.m-val {
  font-size: 16px;
  font-weight: 800;
  color: var(--text-main);
  font-variant-numeric: tabular-nums;
}

.p-metric-card.points .m-val {
  color: var(--primary);
}

.p-metric-card.discount {
  background: var(--amber-light);
  border-color: var(--amber-border);
}

.p-metric-card.discount .m-val {
  color: #d97706;
}

[data-theme="dark"] .p-metric-card.discount .m-val {
  color: #fbbf24;
}

.p-metric-card.quota .m-val {
  color: var(--emerald);
}

/* 分栏 Grid */
.profile-main-grid {
  display: grid;
  grid-template-columns: 240px 1fr;
  gap: 24px;
  align-items: start;
}

/* 侧边菜单 */
.profile-sidebar-menu {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.p-menu-btn {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border-radius: var(--radius);
  background: var(--bg-card);
  border: 1px solid var(--border);
  color: var(--text-main);
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
  cursor: pointer;
  text-align: left;
  transition: all 0.2s ease;
  box-shadow: var(--shadow-sm);
}

.p-menu-btn:hover {
  background: var(--bg-card-subtle);
  border-color: var(--primary-border);
}

.p-menu-btn.active {
  background: var(--primary-light);
  color: var(--primary);
  border-color: var(--primary);
}

/* 右侧内容卡片 */
.profile-content-panel {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.profile-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 24px;
  box-shadow: var(--shadow-card);
}

.p-card-header {
  margin-bottom: 20px;
}

.p-card-title {
  font-size: 16px;
  font-weight: 700;
  margin: 0;
  color: var(--text-main);
}

.p-card-subtitle {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 2px;
}

/* 打卡日历圆点板 */
.week-punch-board {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 16px 20px;
  background: var(--bg-subtle);
  border-radius: var(--radius-sm);
  margin-bottom: 20px;
}

.punch-day-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.day-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
}

.punch-circle {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--bg-card);
  border: 2px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  color: var(--text-dim);
  transition: all 0.2s ease;
}

.punch-day-item.is-checked .punch-circle {
  background: var(--emerald-light);
  border-color: var(--emerald);
  color: var(--emerald);
  font-weight: 800;
}

.punch-stats-summary-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.summary-pill {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: var(--bg-subtle);
  border-radius: var(--radius-sm);
}

.pill-icon {
  font-size: 20px;
}

.pill-info {
  display: flex;
  flex-direction: column;
}

.p-label {
  font-size: 11px;
  color: var(--text-muted);
}

.p-val {
  font-size: 15px;
  font-weight: 800;
  color: var(--text-main);
  font-variant-numeric: tabular-nums;
}

/* 今日任务卡片 */
.task-action-box {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 20px;
  background: var(--primary-light);
  border: 1px solid var(--primary-border);
  border-radius: var(--radius-sm);
}

.task-info-left {
  display: flex;
  align-items: center;
  gap: 14px;
}

.task-status-icon {
  font-size: 28px;
}

.task-name {
  font-size: 15px;
  font-weight: 700;
  margin: 0 0 4px;
  color: var(--text-main);
}

.task-desc {
  font-size: 13px;
  color: var(--text-muted);
  margin: 0;
}

.task-btn {
  padding: 8px 18px;
  font-size: 13px;
  white-space: nowrap;
}

.task-done-badge {
  font-size: 13px;
  font-weight: 700;
  color: var(--emerald);
  background: var(--emerald-light);
  padding: 6px 14px;
  border-radius: var(--radius-pill);
}

/* 快捷入口 */
.quick-nav-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 14px;
}

.quick-nav-item {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 18px;
  background: var(--bg-subtle);
  border-radius: var(--radius-sm);
  text-decoration: none;
  transition: all 0.2s ease;
  border: 1px solid var(--border-light);
}

.quick-nav-item:hover {
  border-color: var(--primary-border);
  background: var(--primary-light);
  transform: translateY(-1px);
}

.quick-icon {
  font-size: 24px;
}

.quick-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-main);
}

.quick-sub {
  font-size: 11px;
  color: var(--text-muted);
}

@media (max-width: 900px) {
  .profile-main-grid {
    grid-template-columns: 1fr;
  }
  .punch-stats-summary-row {
    grid-template-columns: 1fr;
  }
}
</style>
