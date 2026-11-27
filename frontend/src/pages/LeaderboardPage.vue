<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { status as getStatus, practice as practiceApi, leaderboard as leaderboardApi, type PracticeData, type StatusData, type StreakBoardData } from '../api'
import ScrollTable from '../components/ScrollTable.vue'
import { useBodyAttributes } from '../composables/useBodyAttributes'
import { useIdentity } from '../composables/useIdentity'

useBodyAttributes({})
const identity = useIdentity()
const statusData = ref<StatusData | null>(null)
const practiceData = ref<PracticeData | null>(null)
const streakData = ref<StreakBoardData | null>(null)
const loading = ref(false)
const activeTab = ref<'today' | 'streak' | 'total'>('today')

async function loadData(): Promise<void> {
  loading.value = true
  try {
    const [sData, pData, kData] = await Promise.all([
      getStatus(),
      practiceApi.get().catch(() => null),
      leaderboardApi.streak().catch(() => null),
    ])
    statusData.value = sData
    practiceData.value = pData
    streakData.value = kData
  } finally {
    loading.value = false
  }
}

const myEntry = computed(() => statusData.value?.entry)
const myRank = computed(() => {
  if (!myEntry.value) return statusData.value?.user ? '未上榜' : '—'
  return myEntry.value.skipped ? '不计排名' : myEntry.value.rank
})
const streakDays = computed(() => statusData.value?.streak_days ?? myEntry.value?.streak_days ?? 0)
const walletBalance = computed(() => statusData.value?.wallet?.balance ?? 0)
const myName = computed(() => statusData.value?.user?.username)

const todayList = computed(() => statusData.value?.leaderboard || [])
const streakList = computed(() => streakData.value?.items || [])
const totalList = computed(() => practiceData.value?.total_leaderboard || [])
// 今日榜的「连续打卡」列取自连续榜的真实天数；不在连续榜（前 50）内的显示 —
const streakByName = computed(() => new Map(streakList.value.map((item) => [item.username, item.streak_days])))

function formatTime(isoStr: string | null | undefined): string {
  if (!isoStr) return '—'
  const date = new Date(isoStr)
  return Number.isNaN(date.getTime()) ? '—' : date.toTimeString().slice(0, 8)
}

onMounted(() => {
  void loadData()
})
</script>

<template>
  <main class="leaderboard-page-wrap">
    <!-- 顶部横幅 -->
    <header class="leaderboard-header">
      <div class="header-left">
        <div class="lb-badge-icon">🏆</div>
        <div>
          <h1 class="lb-title">排行榜</h1>
          <p class="lb-subtitle">每日打卡榜、连续打卡榜与总练习榜，见证你的健康成长</p>
        </div>
      </div>

      <!-- 分类 Tabs -->
      <div class="lb-tabs-row">
        <button
          type="button"
          class="lb-tab-pill"
          :class="{ active: activeTab === 'today' }"
          @click="activeTab = 'today'"
        >
          今日打卡榜
        </button>
        <button
          type="button"
          class="lb-tab-pill"
          :class="{ active: activeTab === 'streak' }"
          @click="activeTab = 'streak'"
        >
          连续打卡榜
        </button>
        <button
          type="button"
          class="lb-tab-pill"
          :class="{ active: activeTab === 'total' }"
          @click="activeTab = 'total'"
        >
          总练习榜
        </button>
      </div>
    </header>

    <!-- 主体双栏 (左侧大表 70% + 右侧我的排名 30%) -->
    <section class="lb-content-grid">
      <!-- 左侧数据表格 -->
      <div class="lb-table-card">
        <ScrollTable :min-rows="6" :max-rows="10" :row-height="60">
          <!-- 今日打卡榜 -->
          <table v-if="activeTab === 'today'" class="lb-table">
            <thead>
              <tr>
                <th style="width:70px">排名</th>
                <th>用户</th>
                <th>连续打卡</th>
                <th>完成时间</th>
                <th style="text-align:right">积分奖励</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!todayList.length">
                <td colspan="5" class="table-empty">今日打卡榜暂无数据，快来做第一个打卡登顶的人吧！</td>
              </tr>
              <tr
                v-for="item in todayList"
                :key="item.position"
                :class="{
                  'is-skipped': item.skipped,
                  'top-1': item.rank === 1,
                  'top-2': item.rank === 2,
                  'top-3': item.rank === 3,
                  'is-me': item.username === myName
                }"
              >
                <td>
                  <span v-if="item.rank === 1" class="rank-medal">🥇</span>
                  <span v-else-if="item.rank === 2" class="rank-medal">🥈</span>
                  <span v-else-if="item.rank === 3" class="rank-medal">🥉</span>
                  <span v-else-if="item.skipped" class="rank-num" title="不计入排名">—</span>
                  <span v-else class="rank-num">{{ item.rank }}</span>
                </td>
                <td>
                  <div class="user-cell">
                    <div class="user-avatar-sm">{{ item.username.slice(0, 1).toUpperCase() }}</div>
                    <span class="user-name">@{{ item.username }}</span>
                    <span v-if="item.username === myName" class="me-badge">你</span>
                    <span v-if="item.skipped" class="skipped-badge">不计排名</span>
                  </div>
                </td>
                <td>
                  <span v-if="streakByName.get(item.username)" class="streak-pill">🔥 {{ streakByName.get(item.username) }} 天</span>
                  <span v-else class="text-dim">—</span>
                </td>
                <td class="text-dim">{{ formatTime(item.completed_at) }}</td>
                <td style="text-align:right">
                  <span class="reward-pts">+{{ item.amount }}</span>
                </td>
              </tr>
            </tbody>
          </table>

          <!-- 连续打卡榜 -->
          <table v-else-if="activeTab === 'streak'" class="lb-table">
            <thead>
              <tr>
                <th style="width:70px">排名</th>
                <th>用户</th>
                <th>连续打卡</th>
                <th style="text-align:right">今日状态</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!streakList.length">
                <td colspan="4" class="table-empty">暂无连续打卡记录。</td>
              </tr>
              <tr
                v-for="item in streakList"
                :key="item.position"
                :class="{
                  'is-skipped': item.skipped,
                  'top-1': item.rank === 1,
                  'top-2': item.rank === 2,
                  'top-3': item.rank === 3,
                  'is-me': item.username === myName
                }"
              >
                <td>
                  <span v-if="item.rank === 1" class="rank-medal">🥇</span>
                  <span v-else-if="item.rank === 2" class="rank-medal">🥈</span>
                  <span v-else-if="item.rank === 3" class="rank-medal">🥉</span>
                  <span v-else-if="item.skipped" class="rank-num" title="不计入排名">—</span>
                  <span v-else class="rank-num">{{ item.rank }}</span>
                </td>
                <td>
                  <div class="user-cell">
                    <div class="user-avatar-sm">{{ item.username.slice(0, 1).toUpperCase() }}</div>
                    <span class="user-name">@{{ item.username }}</span>
                    <span v-if="item.username === myName" class="me-badge">你</span>
                    <span v-if="item.skipped" class="skipped-badge">不计排名</span>
                  </div>
                </td>
                <td><span class="streak-pill">🔥 {{ item.streak_days }} 天</span></td>
                <td style="text-align:right" :class="item.done_today ? 'reward-pts' : 'text-dim'">
                  {{ item.done_today ? '今日已打卡' : '今日待打卡' }}
                </td>
              </tr>
            </tbody>
          </table>

          <!-- 总练习榜 -->
          <table v-else class="lb-table">
            <thead>
              <tr>
                <th style="width:70px">排名</th>
                <th>用户</th>
                <th style="text-align:right">累计练习</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!totalList.length">
                <td colspan="3" class="table-empty">暂无累计练习记录。</td>
              </tr>
              <tr
                v-for="item in totalList"
                :key="item.rank"
                :class="{
                  'top-1': item.rank === 1,
                  'top-2': item.rank === 2,
                  'top-3': item.rank === 3,
                  'is-me': item.username === myName
                }"
              >
                <td>
                  <span v-if="item.rank === 1" class="rank-medal">🥇</span>
                  <span v-else-if="item.rank === 2" class="rank-medal">🥈</span>
                  <span v-else-if="item.rank === 3" class="rank-medal">🥉</span>
                  <span v-else class="rank-num">{{ item.rank }}</span>
                </td>
                <td>
                  <div class="user-cell">
                    <div class="user-avatar-sm">{{ item.username.slice(0, 1).toUpperCase() }}</div>
                    <span class="user-name">@{{ item.username }}</span>
                    <span v-if="item.username === myName" class="me-badge">你</span>
                  </div>
                </td>
                <td style="text-align:right">
                  <span class="reward-pts">{{ item.count }} 次</span>
                </td>
              </tr>
            </tbody>
          </table>
        </ScrollTable>
      </div>

      <!-- 右侧侧边卡片: 我的排名 (Screen 5 核心) -->
      <aside class="my-rank-sidebar-card">
        <div class="my-rank-header">
          <span class="my-rank-title-icon">🏆</span>
          <h2 class="my-rank-title">我的排名</h2>
        </div>

        <div class="my-rank-hero-display">
          <div class="rank-number-big">
            {{ myRank }}
          </div>
        </div>

        <div class="my-rank-stats-grid">
          <div class="rank-stat-item">
            <span class="stat-lbl">🔥 连续打卡</span>
            <span class="stat-v">{{ streakDays }} 天</span>
          </div>
          <div class="rank-stat-item">
            <span class="stat-lbl">🪙 站内积分</span>
            <span class="stat-v">{{ walletBalance.toLocaleString() }} 分</span>
          </div>
          <div class="rank-stat-item">
            <span class="stat-lbl">⏱️ 今日打卡</span>
            <span class="stat-v" :class="{ 'text-primary': myEntry }">
              {{ myEntry ? '已完成 ✓' : '尚未打卡' }}
            </span>
          </div>
        </div>

        <div class="my-rank-action">
          <RouterLink v-if="!myEntry" class="btn-primary btn-block" to="/">
            前往今日打卡 ➔
          </RouterLink>
          <RouterLink v-else class="btn-secondary btn-block" to="/shop">
            前往积分商城 ➔
          </RouterLink>
        </div>
      </aside>
    </section>
  </main>
</template>

<style scoped>
.leaderboard-page-wrap {
  max-width: 1280px;
  margin: 0 auto;
  padding: 24px 24px 80px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

/* 顶部横幅 */
.leaderboard-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  flex-wrap: wrap;
  padding: 18px 24px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 14px;
}

.lb-badge-icon {
  width: 42px;
  height: 42px;
  border-radius: var(--radius-sm);
  background: var(--primary-light);
  border: 1px solid var(--primary-border);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
}

.lb-title {
  font-size: 20px;
  font-weight: 700;
  margin: 0;
  color: var(--text-main);
}

.lb-subtitle {
  font-size: 13px;
  color: var(--text-muted);
  margin: 2px 0 0;
}

.lb-tabs-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.lb-tab-pill {
  padding: 7px 16px;
  border-radius: var(--radius-pill);
  font-size: 13px;
  font-weight: 600;
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.2s ease;
}

.lb-tab-pill:hover {
  color: var(--text-main);
}

.lb-tab-pill.active {
  background: var(--primary);
  color: #ffffff;
  border-color: var(--primary);
  box-shadow: 0 2px 8px rgba(13, 148, 136, 0.25);
}

/* 双栏 Grid */
.lb-content-grid {
  display: grid;
  grid-template-columns: 1fr 340px;
  gap: 24px;
  align-items: start;
}

/* 左侧表格卡片 */
.lb-table-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
  box-shadow: var(--shadow-card);
}

.table-scroll {
  overflow-x: auto;
}

.lb-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.lb-table th {
  text-align: left;
  padding: 10px 14px;
  font-size: 12px;
  color: var(--text-dim);
  border-bottom: 1px solid var(--border);
}

.lb-table td {
  padding: 12px 14px;
  border-bottom: 1px solid var(--border-light);
  color: var(--text-main);
}

.lb-table tr.is-skipped {
  opacity: 0.5;
  filter: grayscale(1);
}

.skipped-badge {
  padding: 1px 8px;
  border-radius: 9999px;
  background: var(--bg-subtle);
  color: var(--text-dim);
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.lb-table tr.top-1 {
  background: linear-gradient(90deg, rgba(254, 243, 199, 0.3) 0%, transparent 100%);
}

.rank-medal {
  font-size: 18px;
}

.rank-num {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-dim);
}

.user-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.user-avatar-sm {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--primary) 0%, #065f46 100%);
  color: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
}

.user-name {
  font-weight: 600;
}

.me-badge {
  font-size: 10px;
  background: var(--primary);
  color: #ffffff;
  padding: 1px 4px;
  border-radius: 3px;
}

.streak-pill {
  font-size: 11px;
  font-weight: 600;
  color: #b45309;
  background: var(--amber-light);
  padding: 3px 8px;
  border-radius: 4px;
  white-space: nowrap;
}

.reward-pts {
  font-weight: 800;
  color: var(--primary);
  font-variant-numeric: tabular-nums;
  font-size: 14px;
}

.table-empty {
  text-align: center;
  padding: 40px;
  color: var(--text-dim);
}

/* 右侧我的排名卡片 */
.my-rank-sidebar-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 24px;
  box-shadow: var(--shadow-card);
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.my-rank-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.my-rank-title-icon {
  font-size: 18px;
}

.my-rank-title {
  font-size: 16px;
  font-weight: 700;
  margin: 0;
}

.my-rank-hero-display {
  display: flex;
  align-items: baseline;
  gap: 12px;
  padding: 14px 0 6px;
}

.rank-number-big {
  font-size: 48px;
  font-weight: 800;
  color: var(--primary);
  line-height: 1;
  letter-spacing: -0.03em;
  font-variant-numeric: tabular-nums;
}

.trend-pill {
  font-size: 12px;
  font-weight: 700;
  color: var(--emerald);
  background: var(--emerald-light);
  padding: 3px 8px;
  border-radius: var(--radius-pill);
}

.my-rank-stats-grid {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.rank-stat-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  background: var(--bg-subtle);
  border-radius: var(--radius-sm);
  font-size: 13px;
}

.stat-lbl {
  color: var(--text-muted);
}

.stat-v {
  font-weight: 700;
  color: var(--text-main);
}

.btn-block {
  width: 100%;
  text-align: center;
  padding: 10px;
  font-size: 13px;
}

@media (max-width: 900px) {
  .lb-content-grid {
    grid-template-columns: 1fr;
  }
}
</style>
