<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AdminConfirm from '../components/AdminConfirm.vue'
import AdminCreditDialog from '../components/AdminCreditDialog.vue'
import AdminDashboard from '../components/AdminDashboard.vue'
import AdminIcon, { type AdminIconName } from '../components/AdminIcon.vue'
import AdminLogs from '../components/AdminLogs.vue'
import AdminRules from '../components/AdminRules.vue'
import AdminShop from '../components/AdminShop.vue'
import AdminUsers from '../components/AdminUsers.vue'
import type { AdminTab } from '../components/adminFormat'
import { useAdmin } from '../composables/useAdmin'
import '../styles/admin.css'

const route = useRoute()
const router = useRouter()
const a = useAdmin()

const tabs: Array<{ key: AdminTab; label: string; icon: AdminIconName; title: string; desc: string }> = [
  { key: 'dashboard', label: '概览', icon: 'dashboard', title: '概览', desc: '今日运行状态与待处理事项' },
  { key: 'rules', label: '打卡规则', icon: 'rules', title: '打卡规则', desc: '开放时间、排名奖励、访问审核与不发货名单' },
  { key: 'shop', label: '商店', icon: 'shop', title: '商店与订单', desc: '商品上下架、兑换订单与人工对账' },
  { key: 'users', label: '用户与积分', icon: 'users', title: '用户与积分', desc: '查询用户并手动增加积分' },
  { key: 'logs', label: '记录', icon: 'logs', title: '记录', desc: '每日奖励领取与练习触发明细' },
]

const tab = computed<AdminTab>(() => {
  const value = String(route.query.tab ?? '')
  return tabs.some((t) => t.key === value) ? (value as AdminTab) : 'dashboard'
})
const current = computed(() => tabs.find((t) => t.key === tab.value)!)

function go(next: AdminTab): void {
  void router.replace({ path: '/admin', query: next === 'dashboard' ? {} : { tab: next } })
}

// 侧栏角标：规则页=待审核访问，商店页=待核对订单
function badge(key: AdminTab): number {
  if (key === 'rules') return a.flaggedVisits.value.length
  if (key === 'shop') return a.uncertainOrders.value.length
  return 0
}

onMounted(a.init)
</script>

<template>
  <div class="adm">
    <!-- 无权限 / 加载失败 -->
    <div v-if="!a.data.value && !a.loading.value" class="adm-card adm-denied" style="grid-column: 1 / -1">
      <h1>无法进入管理后台</h1>
      <p role="alert">{{ a.denied.value || '请先登录管理员账号。' }}</p>
      <RouterLink class="adm-btn" to="/">返回首页</RouterLink>
    </div>

    <!-- 首次加载骨架 -->
    <template v-else-if="!a.data.value">
      <div class="adm-skel" style="height: 300px" />
      <div style="display: flex; flex-direction: column; gap: 16px">
        <div class="adm-skel" style="height: 56px; width: 40%" />
        <div class="adm-skel" style="height: 120px" />
        <div class="adm-skel" style="height: 280px" />
      </div>
    </template>

    <template v-else>
      <aside class="adm-side" aria-label="管理后台导航">
        <div class="adm-side-title">管理后台</div>
        <button
          v-for="t in tabs"
          :key="t.key"
          class="adm-nav"
          :class="{ on: tab === t.key }"
          type="button"
          :aria-current="tab === t.key ? 'page' : undefined"
          @click="go(t.key)"
        >
          <AdminIcon :name="t.icon" />
          {{ t.label }}
          <span v-if="badge(t.key)" class="adm-count">{{ badge(t.key) }}</span>
        </button>
        <div class="adm-side-foot">
          <RouterLink class="adm-nav" to="/"><AdminIcon name="home" /> 返回站点</RouterLink>
        </div>
      </aside>

      <main class="adm-main">
        <header class="adm-head">
          <div>
            <h1>{{ current.title }}</h1>
            <p>{{ current.desc }}</p>
          </div>
          <div class="adm-head-actions">
            <button class="adm-btn" type="button" :disabled="a.busy.value" @click="a.reload()">
              <AdminIcon name="refresh" :class="{ 'adm-spin': a.busy.value }" /> 刷新
            </button>
          </div>
        </header>

        <AdminDashboard
          v-if="tab === 'dashboard'"
          :data="a.data.value"
          :uncertain="a.uncertainOrders.value"
          :flagged="a.flaggedVisits.value"
          :busy="a.busy.value"
          @open="a.openToday"
          @goto="go"
        />
        <AdminRules
          v-else-if="tab === 'rules'"
          :settings="a.data.value.settings"
          :visits="a.data.value.visits"
          :busy="a.busy.value"
          @save-base="a.saveBase"
          @save-rewards="a.saveRewards"
          @save-no-payout="a.saveNoPayout"
          @review="a.review"
        />
        <AdminShop
          v-else-if="tab === 'shop'"
          :products="a.data.value.products"
          :purchases="a.data.value.purchases"
          :busy="a.busy.value"
          @save="a.saveProduct"
          @archive="a.archiveProduct"
          @reconcile="a.reconcile"
          @check="a.checkOrder"
          @check-all="a.checkAll"
        />
        <AdminUsers
          v-else-if="tab === 'users'"
          :wallets="a.data.value.wallets"
          :users="a.users.value"
          :credit-enabled="a.data.value.admin_credit_enabled"
          :busy="a.busy.value"
          @search="a.search"
          @credit="a.openCredit"
        />
        <AdminLogs
          v-else
          :rewards="a.data.value.rewards"
          :triggers="a.data.value.practice_triggers"
        />
      </main>
    </template>

    <AdminConfirm :action="a.pending.value" :busy="a.busy.value" :error="a.confirmError.value" @confirm="a.confirmAsk" @cancel="a.cancelAsk" />
    <AdminCreditDialog :user="a.creditTarget.value" :busy="a.busy.value" :error="a.creditError.value" @submit="a.submitCredit" @cancel="a.closeCredit" />

    <div class="adm-toasts" role="status" aria-live="polite">
      <div v-for="t in a.toasts.value" :key="t.id" class="adm-toast" :class="t.tone" @click="a.dismissToast(t.id)">{{ t.text }}</div>
    </div>
  </div>
</template>
