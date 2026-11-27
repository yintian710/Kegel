<script setup lang="ts">
import { ref, watch } from 'vue'
import type { PendingAction } from '../composables/useAdmin'
import AdminModal from './AdminModal.vue'

const props = defineProps<{ action: PendingAction | null; busy: boolean; error: string }>()
const emit = defineEmits<{ confirm: [secret: string]; cancel: [] }>()

// 关闭动画期间保留上一次的内容，避免弹层瞬间变空
const shown = ref<PendingAction | null>(props.action)
const secret = ref('')
const checked = ref(false)

watch(() => props.action, (action) => {
  if (action) {
    shown.value = action
    secret.value = ''
    checked.value = false
  }
})

function submit(): void {
  if (!checked.value || props.busy) return
  emit('confirm', secret.value)
}
</script>

<template>
  <AdminModal :open="!!action" :label="shown?.title ?? '确认操作'" @close="emit('cancel')">
    <form v-if="shown" @submit.prevent="submit">
      <div class="adm-dialog-head">
        <h2>{{ shown.title }}</h2>
        <p>{{ shown.description }}</p>
      </div>
      <div class="adm-dialog-body">
        <div v-if="shown.secret" class="adm-field">
          <label for="adm-confirm-secret">管理员二级密码</label>
          <input
            id="adm-confirm-secret"
            v-model="secret"
            class="adm-input"
            type="password"
            autocomplete="off"
            maxlength="1024"
            placeholder="输入二级密码"
          >
        </div>
        <label class="adm-check">
          <input v-model="checked" type="checkbox">
          <span>{{ shown.check }}</span>
        </label>
        <p v-if="error" class="adm-err" role="alert">{{ error }}</p>
      </div>
      <div class="adm-dialog-foot">
        <button class="adm-btn" type="button" :disabled="busy" @click="emit('cancel')">取消</button>
        <button
          class="adm-btn"
          :class="shown.danger ? 'danger solid' : 'primary'"
          type="submit"
          :disabled="busy || !checked"
        >
          {{ busy ? '执行中…' : '确认执行' }}
        </button>
      </div>
    </form>
  </AdminModal>
</template>
