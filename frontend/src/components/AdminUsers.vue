<script setup lang="ts">
import { computed, ref } from 'vue'
import type { AdminUser, AdminWallet } from '../api'
import AdminIcon from './AdminIcon.vue'
import { initial } from './adminFormat'

const props = defineProps<{ wallets: AdminWallet[]; users: AdminUser[] | null; creditEnabled: boolean; busy: boolean }>()
const emit = defineEmits<{ search: [query: string]; credit: [user: AdminWallet | AdminUser] }>()

const query = ref('')
const searched = ref('')
const shown = computed<(AdminWallet | AdminUser)[]>(() => props.users ?? props.wallets)

function submit(): void {
  const q = query.value.trim()
  if (!q) return
  searched.value = q
  emit('search', q)
}
</script>

<template>
  <div class="adm-card">
    <div class="adm-card-head">
      <div>
        <h3>用户与积分</h3>
        <p class="sub">
          {{ creditEnabled ? '搜索用户后可增加积分，每次操作都需要二级密码。' : '尚未配置二级密码，暂不能增加积分。' }}
        </p>
      </div>
      <form class="adm-search" style="max-width: 360px" @submit.prevent="submit">
        <AdminIcon name="search" />
        <input v-model="query" class="adm-input" type="search" maxlength="128" placeholder="搜索用户名，回车确认" aria-label="搜索用户名">
      </form>
    </div>
    <p style="margin: 12px 20px 0; font-size: 12px; color: var(--text-dim)">
      {{ users ? `「${searched}」的搜索结果：${users.length} 位（最多 50 位）` : `余额排行：显示 ${wallets.length} 位用户` }}
    </p>
    <div class="adm-tablewrap" style="margin-top: 10px; max-height: 620px">
      <table class="adm-table">
        <thead><tr><th>用户</th><th>用户 ID</th><th>站内积分余额</th><th class="r">操作</th></tr></thead>
        <tbody>
          <tr v-if="!shown.length"><td colspan="4" class="adm-empty">没有找到用户</td></tr>
          <tr v-for="user in shown" :key="user.user_id">
            <td><span class="adm-user"><span class="adm-avatar">{{ initial(user.username) }}</span>@{{ user.username }}</span></td>
            <td class="mono muted">{{ user.user_id }}</td>
            <td><b v-if="'balance' in user">{{ user.balance.toLocaleString() }}</b><span v-else class="muted">—</span></td>
            <td class="r">
              <button class="adm-btn sm" type="button" :disabled="busy || !creditEnabled" @click="emit('credit', user)">
                <AdminIcon name="plus" /> 加积分
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
