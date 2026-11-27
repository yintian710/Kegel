<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { AdminUser, AdminWallet } from '../api'
import AdminModal from './AdminModal.vue'

const props = defineProps<{ user: AdminWallet | AdminUser | null; busy: boolean; error: string }>()
const emit = defineEmits<{ submit: [amount: number, secret: string]; cancel: [] }>()

const shown = ref<AdminWallet | AdminUser | null>(props.user)
const amount = ref<number | null>(null)
const secret = ref('')
const quick = [100, 500, 1000, 5000]

const balance = computed(() => (shown.value && 'balance' in shown.value ? shown.value.balance : null))
const valid = computed(() => amount.value !== null && Number.isInteger(amount.value) && amount.value >= 1 && amount.value <= 100000000)

watch(() => props.user, (user) => {
  if (user) {
    shown.value = user
    amount.value = null
    secret.value = ''
  }
})

function submit(): void {
  if (!valid.value || !secret.value || props.busy) return
  emit('submit', amount.value as number, secret.value)
}
</script>

<template>
  <AdminModal :open="!!user" label="增加积分" @close="emit('cancel')">
    <form v-if="shown" @submit.prevent="submit">
      <div class="adm-dialog-head">
        <h2>增加积分</h2>
        <p>
          为 <b>@{{ shown.username }}</b> 增加站内积分<template v-if="balance !== null">，当前余额 {{ balance.toLocaleString() }}</template>。
        </p>
      </div>
      <div class="adm-dialog-body">
        <div class="adm-field">
          <label for="adm-credit-amount">积分数量</label>
          <input
            id="adm-credit-amount"
            v-model.number="amount"
            class="adm-input"
            type="number"
            min="1"
            max="100000000"
            step="1"
            required
          >
          <div class="adm-chips">
            <button v-for="n in quick" :key="n" class="adm-chip" type="button" @click="amount = n">+{{ n }}</button>
          </div>
        </div>
        <div class="adm-field">
          <label for="adm-credit-secret">管理员二级密码</label>
          <input id="adm-credit-secret" v-model="secret" class="adm-input" type="password" autocomplete="off" maxlength="1024" required>
        </div>
        <p v-if="error" class="adm-err" role="alert">{{ error }}</p>
      </div>
      <div class="adm-dialog-foot">
        <button class="adm-btn" type="button" :disabled="busy" @click="emit('cancel')">取消</button>
        <button class="adm-btn primary" type="submit" :disabled="busy || !valid || !secret">
          {{ busy ? '提交中…' : '确认增加' }}
        </button>
      </div>
    </form>
  </AdminModal>
</template>
